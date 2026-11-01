#!/usr/bin/env python3
"""OpenCode in a persistent Docker container, using native Ollama."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

IMAGE = 'docker/sandbox-templates:opencode@sha256:7feb9784bc882dbe014888becb65c23e7fb1d1b24169a68d33660fe44476a0b4'
MODELS = {
    'qwen': 'qwen3.8:27b-mlx',
    'kat': 'hf.co/bartowski/Kwaipilot_KAT-Coder-V2.5-Dev-GGUF:Q4_K_M',
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='agents opencode', description=__doc__)
    parser.add_argument('command', nargs='?', choices=['shell', 'up', 'stop', 'status', 'logs'], default='shell')
    parser.add_argument('--workspace', default='default', help='Docker-only workspace name; never a host path')
    parser.add_argument('--doctor', action='store_true', help='Check Docker, installed models, and container access to Ollama')
    argv = sys.argv[1:] if argv is None else argv
    split = argv.index('--') if '--' in argv else len(argv)
    args = parser.parse_args(argv[:split])
    agent_args = argv[split + 1:]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", args.workspace):
        parser.error("Workspace must be a short lowercase name, not a directory path.")
    if not shutil.which('docker'):
        parser.exit(1, 'Docker is missing. Install/start Docker Desktop first.\n')
    if subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        parser.exit(1, 'Start Docker Desktop, then retry.\n')
    model = MODELS['qwen']
    if args.doctor:
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
                installed = {m['name'] for m in json.load(response)['models']}
        except Exception as error:
            parser.exit(1, f'Cannot reach local Ollama. Open Ollama and retry. ({error})\n')
        model = MODELS['qwen']
        if model not in installed:
            parser.exit(1, f'Model not installed: {model}\nInstall it in Ollama first.\n')
        if args.doctor:
            for alias, name in MODELS.items():
                print(f'{alias}: {"installed" if name in installed else "missing"}', flush=True)
            return subprocess.call(['docker', 'run', '--rm', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--entrypoint', 'sh', IMAGE, '-c', 'opencode --version && curl -fsS --max-time 10 http://host.docker.internal:11434/api/tags >/dev/null && echo "Container → Ollama: OK"'])
    identity = 'isolated-' + args.workspace
    config = {
        '$schema': 'https://opencode.ai/config.json',
        'enabled_providers': ['ollama'],
        'model': 'ollama/' + model,
        'small_model': 'ollama/' + model,
        'autoupdate': False,
        'share': 'disabled',
        'permission': 'allow',
        'provider': {'ollama': {
            'npm': '@ai-sdk/openai-compatible',
            'name': 'Ollama local',
            'options': {'baseURL': 'http://host.docker.internal:11434/v1'},
            'models': {name: {'name': alias.upper(), 'limit': {'context': 65536, 'output': 8192}} for alias, name in MODELS.items()},
        }},
    }
    name = 'oc-local-' + identity
    inspected = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True, text=True)
    existing = json.loads(inspected.stdout)[0] if inspected.returncode == 0 else None
    if existing:
        if (existing['Config'].get('Labels') or {}).get('oc-local.lifecycle') != 'persistent-v1':
            parser.exit(1, f'Container {name} is not owned by this persistent launcher. Preserving it.\n')
        if existing['HostConfig'].get('Privileged') or existing['HostConfig'].get('NetworkMode') == 'host':
            parser.exit(1, 'Refusing a privileged container or host networking.\n')
        if any(m['Type'] == 'bind' or 'docker.sock' in m.get('Destination', '') for m in existing.get('Mounts', [])):
            parser.exit(1, 'Refusing a container with host-directory mounts.\n')
    if args.command == 'status':
        print(f"{name}: {existing['State']['Status'] if existing else 'not created'}", flush=True)
        return 0
    if args.command == 'stop':
        return subprocess.call(['docker', 'stop', name]) if existing else 0
    if args.command == 'logs':
        if not existing:
            parser.exit(1, 'OpenCode container has not been created yet.\n')
        return subprocess.call(['docker', 'logs', '--tail', '100', '--follow', name])
    if not existing:
        subprocess.run(['docker', 'run', '--detach', '--restart=unless-stopped',
                        '--name', name, '--label', 'app=oc-local',
                        '--label', 'oc-local.lifecycle=persistent-v1',
                        '--cpus=4', '--memory=6g', '--user=root',
                        '--cap-add=NET_ADMIN', '--device=/dev/net/tun',
                        '--env', 'HOME=/home/agent',
               '--env', 'NVPN_CONFIG_PATH=/var/lib/oc-local-nvpn/config.toml',
                        '--security-opt=no-new-privileges',
                        '--workdir', '/home/agent/workspace',
                        '--mount', f'type=volume,source=oc-local-{identity}-files,target=/home/agent/workspace',
                        '--mount', f'type=volume,source=oc-local-{identity}-sessions,target=/home/agent/.local/share',
                        '--mount', f'type=volume,source=oc-local-{identity}-nvpn,target=/var/lib/oc-local-nvpn',
                        IMAGE, 'sh', '-c', 'if [ -x /usr/local/bin/oc-local-boot ]; then exec /usr/local/bin/oc-local-boot; else exec sleep infinity; fi'], check=True, stdout=subprocess.DEVNULL)
    elif not existing['State']['Running']:
        subprocess.run(['docker', 'start', name], check=True, stdout=subprocess.DEVNULL)
    if args.command == 'up':
        print(f'{name}: running')
        return 0
    write_config = '''import json, pathlib, sys
p = pathlib.Path('/home/agent/.config/opencode/opencode.json')
p.parent.mkdir(parents=True, exist_ok=True)
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg.update(json.load(sys.stdin))
p.write_text(json.dumps(cfg, indent=2) + '\\n')
'''
    subprocess.run(['docker', 'exec', '--interactive', '--user=root', name,
                    'python3', '-c', write_config], input=json.dumps(config), text=True, check=True)
    if subprocess.run(['docker', 'exec', '--user=root', '--env', 'HOME=/home/agent', name, 'sh', '-c', 'command -v tmux'], stdout=subprocess.DEVNULL).returncode:
        print('Installing tmux inside this container...', flush=True)
        subprocess.run(['docker', 'exec', '--user=root', name, 'sh', '-ec',
                        'apt-get update -qq && apt-get install -y --no-install-recommends tmux'], check=True)
    command = ['docker', 'exec', '--interactive', '--user=root',
               '--env', 'HOME=/home/agent',
               '--env', 'NVPN_CONFIG_PATH=/var/lib/oc-local-nvpn/config.toml',
               '--workdir', '/home/agent/workspace',
               '--env', 'OPENCODE_CONFIG_CONTENT=' + json.dumps(config),
               '--env', 'TERM=' + (os.environ.get('TERM') if os.environ.get('TERM') not in (None, '', 'dumb') else 'xterm-256color')]
    if sys.stdin.isatty() and sys.stdout.isatty():
        command.append('--tty')
    command += [name, 'tmux', 'new-session', '-A', '-s', 'work', 'bash', *agent_args]
    print(f'{name}: persistent container, no host directories mounted.\nRun opencode here. Detach with Ctrl+B, then D; reconnect with agents opencode.', flush=True)
    os.execvp(command[0], command)



if __name__ == '__main__':
    sys.exit(main())
