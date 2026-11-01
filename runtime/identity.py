"""Pure public-identity encoding shared by operator setup and pairing."""
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


def hex_npub(value):
    """Encode a saved, validated policy identity without asking the user again."""
    raw=bytes.fromhex(value)
    if len(raw)!=32: raise ValueError('Expected a 32-byte identity')
    acc=bits=0;data=[]
    for v in raw:
        acc=(acc<<8)|v;bits+=8
        while bits>=5:
            bits-=5;data.append((acc>>bits)&31)
    if bits:data.append((acc<<(5-bits))&31)
    chk=1
    hrp=[ord(c)>>5 for c in 'npub']+[0]+[ord(c)&31 for c in 'npub']
    for v in hrp+data+[0]*6:
        top=chk>>25;chk=((chk&0x1ffffff)<<5)^v
        for i,g in enumerate([0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3]):
            if (top>>i)&1:chk^=g
    chk^=1
    return 'npub1'+''.join(CHARSET[v] for v in data+[(chk>>(5*(5-i)))&31 for i in range(6)])
