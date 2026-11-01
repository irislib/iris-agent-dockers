"""Manage the existing Iris Compose project without changing its identities."""
import getpass
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ('hermes', 'openclaw')


def compose(*args, **kwargs):
    return subprocess.run(['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), *args],
                          cwd=ROOT, check=True, **kwargs)


def up(agent=None):
    services = ['model-gate', agent + '-net', agent + '-iris', agent] if agent else []
    # Starting a terminal must never replace a running agent or shared model gate.
    compose('up', '-d', '--no-recreate', *services)


def main(action, agent=None, *, owner=None, invite=None, shell_args=()):
    if action == 'up':
        up(agent)
    elif action == 'stop':
        services = [agent, agent + '-iris', agent + '-net'] if agent else []
        compose('stop', *services)
    elif action == 'status':
        services = [agent, agent + '-iris', agent + '-net'] if agent else []
        compose('ps', '--all', *services)
    elif action == 'shell':
        running = compose('ps', '--status', 'running', '-q', agent,
                          capture_output=True, text=True).stdout.strip()
        if not running:
            up(agent)
        flags = [] if sys.stdin.isatty() and sys.stdout.isatty() else ['-T']
        compose('exec', *flags, agent, 'bash', *shell_args)
    elif action == 'logs':
        compose('logs', '--tail', '100', '-f', agent, agent + '-iris')
    elif action == 'pair':
        invite = invite or getpass.getpass('Private Iris invite: ')
        compose('exec', '-T', agent + '-iris', 'python3', '/opt/iris-agent/pair.py',
                input=json.dumps({'owner': owner, 'invite': invite}), text=True)
    elif action == 'check':
        subprocess.run([sys.executable, str(ROOT / 'tests/live_check.py'),
                        *([agent] if agent else [])], cwd=ROOT, check=True)
    elif action == 'build':
        for dockerfile, tag, platform in [
            ('Dockerfile.support', 'iris-agent-support:local', 'linux/amd64'),
            ('Dockerfile.iris', 'iris-agent-iris:local', 'linux/amd64'),
            *[(f'Dockerfile.{name}', f'iris-agent-{name}:local', None)
              for name in ([agent] if agent else AGENTS)],
        ]:
            subprocess.run(['docker', 'build', *(['--platform', platform] if platform else []),
                            '-f', dockerfile, '-t', tag, '.'], cwd=ROOT, check=True)
    else:
        raise ValueError('Unsupported chat-agent action')
    return 0
