"""Network namespace firewall. The agent never has NET_ADMIN or NET_RAW."""
import ipaddress
import os
import subprocess
from pathlib import Path

BLOCKED_V4 = ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8',
              '169.254.0.0/16','172.16.0.0/12','192.0.0.0/24','192.0.2.0/24',
              '192.168.0.0/16','198.18.0.0/15','198.51.100.0/24','203.0.113.0/24',
              '224.0.0.0/4','240.0.0.0/4']

def rules(extra=()):
    lines = ['*filter', ':INPUT DROP [0:0]', ':FORWARD DROP [0:0]', ':OUTPUT DROP [0:0]',
             '-A INPUT -i lo -j ACCEPT', '-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
             '-A OUTPUT -o lo -j ACCEPT',
             '-A OUTPUT -d 172.30.240.2 -p tcp --dport 11434 -j ACCEPT']
    for cidr in [*BLOCKED_V4, *extra]:
        network = ipaddress.ip_network(cidr, strict=False)
        if network.version == 4:
            lines.append(f'-A OUTPUT -d {network} -j REJECT')
    lines += ['-A OUTPUT -j ACCEPT', 'COMMIT']
    return '\n'.join(lines) + '\n'

def main():
    subprocess.run(['iptables-restore'], input=rules(os.environ.get('BLOCK_HOST_IPS','').split()), text=True, check=True)
    # No IPv6 bypass, including mapped/NAT64/link-local/multicast addresses.
    subprocess.run(['ip6tables-restore'], input='*filter\n:INPUT DROP [0:0]\n:FORWARD DROP [0:0]\n:OUTPUT DROP [0:0]\n-A INPUT -i lo -j ACCEPT\n-A OUTPUT -o lo -j ACCEPT\nCOMMIT\n', text=True, check=True)
    Path('/tmp/ready').touch()
    os.execvp('sleep', ['sleep', 'infinity'])

if __name__ == '__main__':
    main()
