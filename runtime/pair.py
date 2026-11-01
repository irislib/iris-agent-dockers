"""Operator-only pairing, called through docker exec with JSON on stdin."""
import json
import os
import sys
import time
from pathlib import Path
from broker import STATE, iris, validate_chat, connect

CHARSET='qpzry9x8gf2tvdw0s3jn54khce6mua7l'
def npub_hex(value):
    if not value.startswith('npub1') or value.lower()!=value or len(value)!=63:
        raise ValueError('Expected an npub')
    data=[CHARSET.index(c) for c in value[5:]]
    hrp=[ord(c)>>5 for c in 'npub']+[0]+[ord(c)&31 for c in 'npub']
    chk=1
    for v in hrp+data:
        top=chk>>25; chk=((chk&0x1ffffff)<<5)^v
        for i,g in enumerate([0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3]):
            if (top>>i)&1: chk^=g
    if chk!=1: raise ValueError('Invalid npub checksum')
    acc=0;bits=0;out=[]
    for v in data[:-6]:
        acc=(acc<<5)|v;bits+=5
        if bits>=8: bits-=8;out.append((acc>>bits)&255)
    if len(out)!=32 or (acc&((1<<bits)-1)): raise ValueError('Invalid npub data')
    return bytes(out).hex()

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
