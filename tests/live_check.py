"""Run actual network/process boundary probes inside each agent container."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
compose=['docker','compose','-f',str(ROOT/'compose.yaml')]
probe=r'''
import json,os,socket,urllib.request,urllib.error
from pathlib import Path
checks={}
def blocked(host,port):
    try:
        with socket.create_connection((host,port),timeout=2): return False
    except OSError:return True
for host,port in [('host.docker.internal',11434),('host.docker.internal',22),('host.docker.internal',80),('192.168.65.1',80),('172.30.240.1',80),('172.30.240.2',22),('10.0.0.1',4173),('100.64.0.1',80),('169.254.169.254',80),('224.0.0.251',5353)]:
    checks[f'blocked:{host}:{port}']=blocked(host,port)
checks['other-agent-blocked']=blocked('172.30.240.20' if os.environ['AGENT_BACKEND']=='hermes' else '172.30.240.10',8765)
checks['internet']=urllib.request.urlopen('https://example.com',timeout=15).status==200
with urllib.request.urlopen('http://172.30.240.2:11434/api/tags',timeout=15) as r:
    models=json.load(r)['models'];checks['kat-only']=len(models)==1 and models[0]['name']==os.environ['KAT_MODEL']
for route in ['/api/pull','/api/delete']:
    try:
        urllib.request.urlopen(urllib.request.Request('http://172.30.240.2:11434'+route,data=json.dumps({'model':os.environ['KAT_MODEL']}).encode()),timeout=5)
        checks['denied:'+route]=False
    except urllib.error.HTTPError as e:checks['denied:'+route]=e.code in (403,501)
checks['no-docker-socket']=not Path('/var/run/docker.sock').exists()
checks['no-iris-keys']=not Path('/state/profile').exists()
status=Path('/proc/self/status').read_text()
cap=int(next(line.split()[1] for line in status.splitlines() if line.startswith('CapBnd:')),16)
checks['no-network-or-mount-capabilities']=not (cap & ((1<<12)|(1<<13)|(1<<21)))
checks['no-new-privileges']='NoNewPrivs:\t1' in status
print(json.dumps(checks))
assert all(checks.values()), checks
'''
selected = sys.argv[1:] or ['hermes', 'openclaw']
if any(agent not in ('hermes', 'openclaw') for agent in selected):
    raise SystemExit('Expected hermes or openclaw')
for agent in selected:
    result=subprocess.run(compose+['exec','-T',agent,'python3','-c',probe],capture_output=True,text=True)
    if result.returncode:
        print(agent,result.stdout,result.stderr);sys.exit(1)
    checks=json.loads(result.stdout)
    print(f'{agent}: {len(checks)} isolation/internet/model checks passed')
    ids=subprocess.check_output(compose+['ps','-q',agent],text=True).strip()
    info=json.loads(subprocess.check_output(['docker','inspect',ids],text=True))[0]
    assert not info['HostConfig']['Privileged']
    assert not info['HostConfig'].get('PortBindings')
    assert all(m['Type']=='volume' for m in info['Mounts'])
print('No host directories, Docker socket, privileged mode or published ports.')
