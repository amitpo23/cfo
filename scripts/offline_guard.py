"""Process-local isolation for the offline route audit; never load real provider keys."""
import ast
import os
from pathlib import Path
import socket


def isolate_offline_audit():
    config = ast.parse((Path(__file__).resolve().parents[1] / 'src/cfo/config.py').read_text())
    for node in ast.walk(config):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if any(word in name for word in ('api_key', 'secret', 'client_id', 'user_id', 'password', 'access_token')):
                os.environ[name.upper()] = ''
    os.environ['AUTH_BYPASS_ENABLED'] = 'false'
    os.environ.pop('VERCEL', None)
    os.environ.pop('VERCEL_ENV', None)
    local = {'localhost','127.0.0.1','::1','testserver',''}
    real_dns = socket.getaddrinfo
    real_socket = socket.socket

    def check(host):
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name not in local:
            raise RuntimeError('External network is disabled in the offline route audit')

    def dns(host, *args, **kwargs):
        check(host)
        return real_dns(host, *args, **kwargs)

    class LocalSocket(real_socket):
        def connect(self, address):
            if isinstance(address, tuple):
                check(address[0])
            return super().connect(address)

        def connect_ex(self, address):
            if isinstance(address, tuple):
                check(address[0])
            return super().connect_ex(address)

    socket.getaddrinfo = dns
    socket.socket = LocalSocket
