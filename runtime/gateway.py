"""Start the native Iris channel with existing private state and model settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from worker import BACKEND, HOME, STATE, configure, request


def main():
    os.umask(0o077)
    configure()
    # Never abandon an in-flight legacy task during a migration.
    if (STATE/'pending.json').exists():
        raise RuntimeError('Finish the pending legacy turn before switching to the native gateway.')
    while True:
        try:
            health=request('/channel/health', {})['result']
            owner=health['owner']
            if health['ready'] and len(owner)==64 and all(c in '0123456789abcdef' for c in owner): break
        except Exception: pass
        print('Waiting for the paired Iris transport',flush=True)
        time.sleep(3)

    if BACKEND=='hermes':
        source=Path('/opt/iris-channels/hermes')
        destination=HOME/'plugins/iris-chat-channel'
        manifest=destination/'SOURCE.json'
        if not manifest.exists() or manifest.read_bytes() != (source/'SOURCE.json').read_bytes():
            if destination.exists():
                raise RuntimeError('An existing different Iris plugin needs an explicit operator update.')
            shutil.copytree(source,destination)
        subprocess.run(['hermes','plugins','enable','iris-chat-channel'],check=True)
        os.environ.update(IRIS_CHANNEL_BRIDGE_URL='http://127.0.0.1:8765',IRIS_CHANNEL_OWNER=owner)
        command=['hermes','gateway','run']
    else:
        root=Path(os.environ['OPENCLAW_STATE_DIR'])
        destination=root/'extensions/iris-chat-channel'
        if not destination.exists():
            subprocess.run(['openclaw','plugins','install','--force','--accept-capabilities',
                            '/opt/iris-channels/openclaw.tgz'],check=True)
        expected=json.loads(Path('/opt/iris-channels/hermes/SOURCE.json').read_text())['commit']
        if json.loads((destination/'SOURCE.json').read_text())['commit'] != expected:
            raise RuntimeError('An existing different Iris plugin needs an explicit operator update.')
        cfg=root/'openclaw.json'
        config=json.loads(cfg.read_text())
        channel=config.setdefault('channels',{}).setdefault('iris',{})
        if channel.get('owner',owner)!=owner: raise RuntimeError('Iris owner differs from the saved channel.')
        channel.update(enabled=True,owner=owner,bridgeUrl='http://127.0.0.1:8765')
        # Keep the legacy on-demand behavior when moving to a long-lived gateway.
        # Preserve any deliberate operator choice already in the configuration.
        memory=config.setdefault('plugins',{}).setdefault('entries',{}).setdefault('memory-core',{})
        memory.setdefault('config',{}).setdefault('dreaming',{}).setdefault('enabled',False)
        gateway=config.setdefault('gateway',{})
        gateway['bind']='loopback'
        gateway.setdefault('auth',{'mode':'none'})
        backup=STATE/'pre-native-openclaw.json'
        if not backup.exists(): shutil.copy2(cfg,backup)
        temporary=cfg.with_suffix('.tmp')
        temporary.write_text(json.dumps(config,indent=2)+'\n')
        os.replace(temporary,cfg)
        command=['openclaw','gateway','run']
    print(f'{BACKEND} starting its native Iris channel',flush=True)
    os.execvp(command[0],command)


if __name__=='__main__': main()
