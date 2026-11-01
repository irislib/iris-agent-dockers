"""One-time Iris setup and concise, read-only chat diagnostics."""
import getpass
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from launchers import chat
from runtime.identity import npub_hex, hex_npub

ROOT = Path(__file__).resolve().parents[1]
AGENTS = chat.AGENTS


def installed_models():
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            return [model['name'] for model in json.load(response)['models']]
    except (OSError, ValueError, KeyError) as error:
        raise ValueError('Cannot reach local Ollama. Start Ollama, then run setup again.') from error


def configure_model(requested):
    path = ROOT / '.env'
    text = path.read_text() if path.exists() else ''
    match = re.search(r'^KAT_MODEL=(.+)$', text, re.M)
    existing = match.group(1).strip().strip('"\'') if match else None
    if requested and existing and requested != existing:
        raise ValueError('This setup already uses a different model. Setup preserves existing model settings.')
    models = installed_models()
    model = requested or existing
    if not model:
        kats = [name for name in models if 'kat' in name.casefold()]
        if len(kats) != 1:
            raise ValueError('Choose an installed model with --model MODEL (see ollama list).')
        model = kats[0]
    if model not in models:
        raise ValueError('The selected model is not installed in local Ollama. Setup does not download models.')
    if not re.fullmatch(r'[A-Za-z0-9_./:@+\-]+', model):
        raise ValueError('Unsupported model tag; use the exact tag from ollama list.')
    if not existing:
        if text and not text.endswith('\n'):
            text += '\n'
        text += f'KAT_MODEL={model}\n'
        if not re.search(r'^BLOCK_HOST_IPS=', text, re.M):
            text += 'BLOCK_HOST_IPS=\n'
        # Create private settings without changing an operator's other settings.
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(text)
        path.chmod(0o600)
    return model


def prepare(selected, model=None):
    if subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError('Start Docker Desktop, then run setup again.')
    model = configure_model(model)
    images = ['iris-agent-support:local', 'iris-agent-iris:local', *['iris-agent-'+a+':local' for a in selected]]
    missing = any(subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode for image in images)
    if missing:
        if shutil.disk_usage(ROOT).free < 20*1024**3:
            raise ValueError('Building the agent images needs more free space; keep at least 20 GiB free before setup.')
        print('Preparing the missing agent images...', flush=True)
        chat.main('build', selected[0] if len(selected) == 1 else None)
    print('Using local Ollama: '+model, flush=True)
    for agent in selected:
        chat.up(agent)


def status_for(agent):
    def running(service):
        return bool(chat.compose('ps', '--status', 'running', '-q', service, capture_output=True, text=True).stdout.strip())
    state = {'container_running': running(agent), 'transport_running': running(agent+'-iris')}
    if not state['transport_running']:
        return state
    try:
        result = chat.compose('exec', '-T', agent+'-iris', 'python3', '-',
                              input=(ROOT/'runtime/chat_status.py').read_text(),
                              capture_output=True, text=True, timeout=45)
        state.update(json.loads(result.stdout))
    except (subprocess.SubprocessError, ValueError):
        state['problem'] = 'Chat status unavailable'
    return state


def status_line(agent, state):
    counts = state.get('counts', {})
    active = sum(counts.get(name, 0) for name in ('new', 'running', 'reply_pending'))
    if not state.get('container_running'):
        readiness = 'stopped'
    elif state.get('transport_running') is False:
        readiness = 'chat service stopped'
    elif state.get('problem'):
        readiness = state['problem']
    elif not state.get('paired'):
        readiness = 'not paired'
    elif not state.get('service_ready') or not state.get('bridge_ready'):
        readiness = 'connecting'
    else:
        readiness = 'working' if active or state.get('working') else 'ready'
    receipt = {'seen':'last reply seen', 'received':'last reply delivered',
               'sent':'last reply sent; receipt unconfirmed', 'queued':'last reply queued',
               'pending':'last reply pending', 'failed':'last reply failed'}.get(state.get('last_delivery'), 'no confirmed reply receipt')
    pieces = [f'{agent}: {readiness}', f'{counts.get("done",0)} handled', receipt]
    if active:
        pieces.append(f'{active} active/queued')
    if state.get('reported_errors'):
        pieces.append(f'{state["reported_errors"]} recorded task error(s); see agents logs {agent}')
    return ' | '.join(pieces)


def show_status(selected=chat.AGENTS):
    for agent in selected:
        print(status_line(agent, status_for(agent)), flush=True)
    return 0


def wait_ready(agent):
    deadline = time.monotonic()+90
    while True:
        state = status_for(agent)
        if state.get('container_running') and state.get('service_ready') and (not state.get('paired') or state.get('bridge_ready')):
            return state
        if time.monotonic() >= deadline:
            raise ValueError(f'{agent} chat is not ready yet. Run agents logs {agent}, then rerun setup; its identity is preserved.')
        time.sleep(2)


def setup(agent=None, *, owner=None, invite=None, model=None):
    selected = (agent,) if agent else AGENTS
    expected = npub_hex(owner) if owner else None
    prepare(selected, model)
    states = {a:wait_ready(a) for a in selected}
    saved = {s['owner_hex'] for s in states.values() if s.get('paired')}
    if len(saved)>1 or (expected and saved and saved!={expected}):
        raise ValueError('An agent is already paired to a different contact. Setup will not change its contact policy.')
    missing = [a for a in selected if not states[a].get('paired')]
    if missing:
        if not owner and saved:
            owner = hex_npub(next(iter(saved)))
        if not owner:
            if not sys.stdin.isatty():
                raise ValueError('First setup needs --owner YOUR_NPUB. You will be asked for the private invite once.')
            owner = input('Your Iris user ID (npub): ').strip()
        npub_hex(owner)
        invite = invite or getpass.getpass('Your private Iris invite: ')
        if not invite.strip():
            raise ValueError('An Iris invite is required for first contact.')
        for a in missing:
            chat.main('pair', a, owner=owner, invite=invite)
        print('Paired. Each new agent will introduce itself in Iris; send it a task there.', flush=True)
    else:
        print('Already paired. Existing identities, conversations and sessions are preserved.', flush=True)
    return show_status(selected)
