"""Pinned bridge regressions: the first attempt, never denied recovery, owns the outcome."""
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directsdk

NATIVE = r'''
import json, os, sys, urllib.request, urllib.error
for line in sys.stdin:
    if not json.loads(line).get('shouldQuery') is False:
        break
for _ in range(2):
    try:
        urllib.request.urlopen(urllib.request.Request(os.environ['ANTHROPIC_BASE_URL']+'/v1/messages', data=b'{}'), timeout=5).read()
    except urllib.error.HTTPError as exc:
        error = exc.read().decode()
    except OSError:
        pass
print(json.dumps({'type':'assistant','error':'invalid_request','message':{'content':[{'type':'text','text':error}]}}), flush=True)
print(json.dumps({'type':'result','subtype':'error_during_execution','is_error':True}), flush=True)
'''


@pytest.mark.parametrize('status,partial,expected', [
    (200, '', {}), (200, '  ', {}), (200, '{"x":1}', {'x': 1}),
    (200, '{invalid', None), (429, None, None), (529, None, None),
    (400, None, None), (401, None, None), (413, None, None),
])
def test_first_attempt_owns_outcome(tmp_path, status, partial, expected):
    calls = []
    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            self.end_headers()
            if status != 200:
                self.wfile.write(b'{"error":{"message":"fixture upstream refusal"}}')
                return
            events = [
                {'type':'message_start','message':{'id':'first','role':'assistant','content':[], 'usage':{'input_tokens':1,'output_tokens':1}}},
                {'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'tool_1','name':'mcp__hermes__list_things','input':{}}},
                {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':partial}},
                {'type':'content_block_stop','index':0},
                {'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':1}},
                {'type':'message_stop'},
            ]
            self.wfile.write(''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode())
    peer = ThreadingHTTPServer(('127.0.0.1', 0), Peer)
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    native = tmp_path / 'native.py'
    native.write_text(NATIVE)
    client = directsdk.Client(command=[sys.executable, str(native)], env={
        'PATH':os.defpath, 'HOME':str(tmp_path),
        'ANTHROPIC_BASE_URL':f'http://127.0.0.1:{peer.server_port}'})
    kwargs = dict(model='sonnet', messages=[{'role':'user','content':'fixture'}],
                  tools=[{'type':'function','function':{'name':'list_things','parameters':{'type':'object','properties':{}}}}])
    try:
        if expected is not None:
            result = client.create(**kwargs)
            assert json.loads(result.choices[0].message.tool_calls[0].function.arguments) == expected
            assert result.choices[0].finish_reason == 'tool_calls'
            assert result.usage.native_admission.blocked_requests == 1
        else:
            with pytest.raises(RuntimeError) as raised:
                client.create(**kwargs)
            assert f'first upstream attempt: status {status}' in str(raised.value)
            assert 'native retries denied: 1' in str(raised.value)
            assert raised.value.status_code == (status if status >= 400 else None)
            if status == 200:
                assert 'relay failure JSONDecodeError' in str(raised.value)
        assert len(calls) == 1
    finally:
        client.close()
        peer.shutdown()
        thread.join()
        peer.server_close()
