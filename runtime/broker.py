"""Iris CLI transport owned by the operator, outside the agent's filesystem.

Only one authenticated direct-chat ID is accepted. There is deliberately no
recipient argument, invite endpoint, arbitrary CLI endpoint or credential API.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = Path(os.environ.get('BRIDGE_STATE','/state'))
LOCK = threading.RLock()

def iris(*args, timeout=90):
    result = subprocess.run(['iris','--json','--no-background-sync',*args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Iris command failed; inspect the private transport log')
    value = json.loads(result.stdout)
    if value.get('ok') is False:
        raise RuntimeError('Iris command did not succeed')
    return value.get('data',value)

def connect():
    db = sqlite3.connect(STATE/'bridge.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, reply TEXT, sent_id TEXT)')
    return db

def pairing():
    value = json.loads((STATE/'pairing.json').read_text())
    owner = value['owner_hex']
    if len(owner) != 64 or any(c not in '0123456789abcdef' for c in owner):
        raise ValueError('Invalid owner')
    if value['chat_id'] != owner:
        raise ValueError('Only the approved direct conversation is allowed')
    return value

def validate_chat(chat, owner):
    if chat.get('kind') != 'direct' or chat.get('chat_id') != owner:
        raise ValueError('Unapproved conversation')

def incoming(message, owner):
    return (message.get('chat_id') == owner and message.get('is_outgoing') is False
            and not message.get('deleted_for_everyone') and bool(message.get('body','').strip()))

def refresh():
    p = pairing()
    data = iris('read',p['chat_id'],'--limit','1000')
    validate_chat(data['chat'],p['owner_hex'])
    with LOCK, connect() as db:
        for message in data['messages']:
            if incoming(message,p['owner_hex']):
                db.execute('INSERT OR IGNORE INTO jobs(id,body,status,created) VALUES (?,?,?,?)',
                           (message['id'], message['body'], 'new', message.get('created_at_secs',time.time())))
    return data['messages']

def complete(payload):
    if set(payload) != {'job_id','text'} or not isinstance(payload['text'],str) or not 0 < len(payload['text']) <= 60000:
        raise ValueError('Expected a job ID and reply text only')
    p = pairing()
    with LOCK, connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?',(payload['job_id'],)).fetchone()
        if not row or row['status'] not in ('running','reply_pending','done'):
            raise ValueError('Unknown or inactive job')
        if row['status'] == 'done': return {'status':'done','message_id':row['sent_id']}
        if row['reply'] and row['reply'] != payload['text']:
            raise ValueError('A different reply is already pending')
        # Persist intent before sending. On retry inspect history, never resend blindly.
        had_intent = bool(row['reply'])
        db.execute('UPDATE jobs SET reply=?,status=? WHERE id=?',(payload['text'],'reply_pending',row['id']))
        db.commit()
        history = iris('read',p['chat_id'],'--limit','1000')
        validate_chat(history['chat'],p['owner_hex'])
        matches = [m for m in history['messages'] if m.get('is_outgoing') and m.get('body') == payload['text']
                   and m.get('created_at_secs',0) >= row['created']-1]
        if had_intent and matches:
            sent = matches[-1]
        else:
            # No caller-provided destination can enter this argv.
            sent = iris('send',p['chat_id'],payload['text'])
        message = sent.get('message',sent)
        db.execute('UPDATE jobs SET status=?,sent_id=? WHERE id=?',('done',message.get('id'),row['id']))
        return {'status':'done','message_id':message.get('id'),'delivery':message.get('delivery','unconfirmed')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def respond(self,status,value):
        encoded=json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(encoded)))
        self.end_headers(); self.wfile.write(encoded)
    def do_GET(self):
        try:
            if self.path == '/health':
                p = pairing()
                self.respond(200,{'paired':True}); return
            if self.path != '/next':
                self.respond(404,{}); return
            pairing()
            with LOCK, connect() as db:
                pending=db.execute("SELECT * FROM jobs WHERE status IN ('running','reply_pending') ORDER BY created,id LIMIT 1").fetchone()
                if pending:
                    self.respond(200,{'job_id':pending['id'],'text':pending['body'],'interrupted':True,'reply':pending['reply']})
                    return
                row=db.execute("SELECT * FROM jobs WHERE status='new' ORDER BY created,id LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
                    if not row['id'].startswith('operator:'):
                        iris('seen',pairing()['chat_id'],row['id'])
                    self.respond(200,{'job_id':row['id'],'text':row['body']})
                else: self.respond(200,{'job_id':None})
        except FileNotFoundError: self.respond(503,{'error':'Not paired'})
        except Exception: self.respond(503,{'error':'Transport unavailable'})
    def do_POST(self):
        if self.path != '/complete': self.respond(404,{}); return
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<262144 or self.headers.get('Transfer-Encoding'): raise ValueError()
            value=complete(json.loads(self.rfile.read(n)))
            self.respond(200,value)
        except (ValueError,KeyError,TypeError): self.respond(403,{'error':'Request is not allowed'})
        except Exception: self.respond(503,{'error':'Reply pending; delivery not yet confirmed'})

def poll():
    while True:
        try: refresh()
        except FileNotFoundError: pass
        except Exception: print('Iris receive check pending',flush=True)
        time.sleep(4)

def main():
    os.umask(0o077)
    STATE.mkdir(parents=True,exist_ok=True)
    # Never replace an existing identity. Only initialize a new, empty profile.
    profile=Path(os.environ['IRIS_DATA_DIR'])
    if not profile.exists() or not any(profile.iterdir()):
        iris('account','create','--name',os.environ['AGENT_NAME'])
    log=open(STATE/'transport.log','a')
    service=subprocess.Popen(['iris','--json','service','run'],stdout=log,stderr=log)
    ready=False
    for _ in range(60):
        if service.poll() is not None: raise RuntimeError('Iris service exited')
        try:
            status=iris('service','status',timeout=5)
            if status.get('running',status.get('ready',False)):
                ready=True;break
        except Exception: pass
        time.sleep(1)
    if not ready: raise RuntimeError('Iris service did not become ready')
    with connect(): pass
    def supervise():
        service.wait()
        os._exit(1)
    threading.Thread(target=supervise,daemon=True).start()
    threading.Thread(target=poll,daemon=True).start()
    print('Iris transport started; owner-only bridge listening',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()

if __name__=='__main__': main()
