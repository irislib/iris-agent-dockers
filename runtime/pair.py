"""Operator-only pairing, called through docker exec with JSON on stdin."""
import json
import os
import sys
import time
from pathlib import Path
from broker import STATE, iris, validate_chat, connect

from identity import npub_hex

def main():
    os.umask(0o077)
    request=json.load(sys.stdin)
    owner=npub_hex(request['owner'])
    target=STATE/'pairing.json'
    if target.exists():
        if json.loads(target.read_text())['owner_hex']!=owner:
            raise ValueError('Already paired to a different owner')
        print('Already paired; identity preserved');return
    result=iris('invite','accept',request['invite'])
    validate_chat(result.get('current_chat') or {},owner)
    target.write_text(json.dumps({'owner_hex':owner,'chat_id':owner}))
    iris('privacy','unknown-users','block')
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO jobs(id,body,status,created) VALUES (?,?,?,?)',
                   ('operator:hello', 'Introduce yourself briefly to your human in this private Iris chat. Say that you are using local KAT through Ollama and are ready for tasks. Keep it to two sentences.', 'new', time.time()))
    print('Paired to the approved identity; introduction queued')

if __name__=='__main__': main()
