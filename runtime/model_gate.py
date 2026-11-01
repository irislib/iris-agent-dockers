"""Expose one installed local model. No model management or arbitrary upstream URLs."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

MODEL = os.environ['KAT_MODEL']
UPSTREAM = os.environ.get('OLLAMA_HOST', 'host.docker.internal')
# Serialize the two agents to avoid competing for the same local model/GPU.
INFERENCE = threading.Lock()
ALLOWED = {('GET','/api/tags'),('GET','/api/version'),('GET','/v1/models'),
           ('POST','/api/show'),('POST','/api/chat'),('POST','/v1/chat/completions')}

def validate(method, path, payload):
    if (method, path) not in ALLOWED:
        raise ValueError('Only model discovery and chat inference are allowed')
    if method == 'POST':
        if not isinstance(payload, dict) or payload.get('model', payload.get('name')) != MODEL:
            raise ValueError('Only the configured local model is allowed')
        if path != '/api/show':
            if not isinstance(payload.get('messages'), list):
                raise ValueError('messages must be an array')
            options = payload.get('options', {})
            if not isinstance(options, dict):
                raise ValueError('Invalid options')
            payload['options'] = {k:v for k,v in options.items() if k in ('temperature','top_k','top_p','repeat_penalty','seed','stop')}
            payload['options'].update(num_ctx=65536, num_predict=4096)
            if path == '/api/chat':
                payload['keep_alive'] = '30m'
            else:
                payload['max_tokens'] = max(1,min(int(payload.get('max_tokens',4096)),4096))
                if 'max_completion_tokens' in payload:
                    payload['max_completion_tokens'] = max(1,min(int(payload['max_completion_tokens']),4096))
    return payload

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def do_GET(self): self.proxy()
    def do_POST(self): self.proxy()
    def proxy(self):
        conn = None
        held = False
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 0 or length > 4*1024*1024 or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid request size')
            payload = json.loads(self.rfile.read(length)) if length else None
            payload = validate(self.command, self.path, payload)
            data = json.dumps(payload).encode() if payload is not None else None
            if self.path in ('/api/chat','/v1/chat/completions'):
                held = INFERENCE.acquire(timeout=900)
                if not held: raise ValueError('Model busy; retry later')
            conn = http.client.HTTPConnection(UPSTREAM, 11434, timeout=900)
            conn.request(self.command, self.path, body=data, headers={'Content-Type':'application/json'})
            response = conn.getresponse()
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type','application/json'))
            self.send_header('Connection','close')
            self.end_headers()
            if self.path in ('/api/tags','/v1/models'):
                result = json.loads(response.read())
                key = 'models' if self.path == '/api/tags' else 'data'
                result[key] = [m for m in result.get(key,[]) if m.get('name', m.get('id')) == MODEL]
                self.wfile.write(json.dumps(result).encode())
            else:
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(403, 'Request is not allowed')
        except (OSError, http.client.HTTPException):
            # Do not expose host addresses or request data in logs/errors.
            self.close_connection = True
        finally:
            self.close_connection = True
            if conn: conn.close()
            if held: INFERENCE.release()

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0',11434),Handler).serve_forever()
