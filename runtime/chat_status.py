"""Read-only operator diagnostics. Never return messages, invites or secret keys.

Sent via docker exec stdin so host-side status works without replacing images.
The policy identity is only returned to the local launcher for setup validation.
This is not an endpoint available to the agent.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request

STATE = Path('/state')


def iris(*args):
    p = subprocess.run(['iris', '--json', '--no-background-sync', *args],
                       capture_output=True, text=True, timeout=15)
    if p.returncode:
        raise RuntimeError('Iris command unavailable')
    result = json.loads(p.stdout)
    if result.get('status') == 'error':
        raise RuntimeError('Iris command unavailable')
    return result.get('data', {})


def collect():
    result = {'paired': False, 'service_ready': False, 'bridge_ready': False,
              'connected_servers': 0, 'counts': {}, 'reported_errors': 0,
              'last_delivery': None}
    try:
        policy = json.loads((STATE / 'pairing.json').read_text())
        owner = policy['owner_hex']
        if len(owner) != 64 or any(c not in '0123456789abcdef' for c in owner) or policy['chat_id'] != owner:
            raise ValueError()
        result.update(paired=True, owner_hex=owner)
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError):
        result['problem'] = 'Invalid pairing policy'
        return result
    try:
        status = iris('service', 'status')
        result['service_ready'] = bool(status.get('running') and status.get('account_loaded') and status.get('network_ready'))
        result['connected_servers'] = status.get('connected_servers', 0)
    except Exception:
        result['problem'] = 'Iris service unavailable'
    if result['paired']:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3) as response:
                health = json.load(response)
                result['bridge_ready'] = health.get('paired') is True
                result['working'] = health.get('working', False)
        except Exception:
            pass
    if (STATE / 'bridge.sqlite3').exists():
        try:
            db = sqlite3.connect((STATE / 'bridge.sqlite3').as_uri()+'?mode=ro', uri=True, timeout=3)
            try:
                result['counts'] = dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
                result['reported_errors'] = db.execute("SELECT count(*) FROM jobs WHERE reply LIKE 'I could not finish%' OR reply LIKE 'My previous task was interrupted%'").fetchone()[0]
            finally:
                db.close()
        except sqlite3.Error:
            result['problem'] = 'Task status unavailable'
    if result['paired'] and result['service_ready']:
        try:
            history = iris('read', result['owner_hex'], '--limit', '20')
            if history['chat']['kind'] != 'direct' or history['chat']['chat_id'] != result['owner_hex']:
                raise ValueError()
            result['last_delivery'] = next((m['delivery'] for m in reversed(history['messages']) if m['is_outgoing']), None)
        except Exception:
            result['problem'] = 'Message receipts unavailable'
    return result


if __name__ == '__main__':
    print(json.dumps(collect()))
