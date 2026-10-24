"""Frontend-only acceptance host: real S12 API/index with synthetic local logs.

The temporary asset shim is deliberately not application/runtime integration.
Agent 1 owns serving local.html/assets and CSP in the production handler.
"""
from http.server import ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_api import ApiFixture
from test_index import counter, claude
from usage_api_http import handler_class, LocalSessions


def main():
    fixture = ApiFixture()
    fixture.setUp()
    item = counter(1010000, 10, cached=1000000, output=1830000)
    item['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 1260000
    first = counter(505000, 5, cached=500000, output=915000)
    first['payload']['info']['total_token_usage']['reasoning_output_tokens'] = 630000
    fixture.write(events=[first, item])
    (fixture.claude / 'a.jsonl').write_text(json.dumps(claude()) + '\n', encoding='utf-8')
    fixture.store.import_settings()
    fixture.jobs.start()
    dashboard = ROOT / 'dashboard'
    assets = {'/' : dashboard / 'local.html'}
    for name in ('local-app.js', 'local-session.js', 'local-view.js', 'v1-client.js', 'v1-schema.js', 'format.js', 'style.css'):
        assets['/' + name] = dashboard / name
    for path in (dashboard / 'assets').iterdir():
        if path.is_file():
            assets['/assets/' + path.name] = path
    base = handler_class(fixture.service)

    class FrontendTestHandler(base):
        def dispatch(self, method):
            if method == 'GET' and self.path in assets:
                self.boundary()
                path = assets[self.path]
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                body = path.read_bytes()
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().dispatch(method)

    server = ThreadingHTTPServer(('127.0.0.1', 0), FrontendTestHandler)
    server.sessions = LocalSessions()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(json.dumps({'origin': 'http://127.0.0.1:' + str(server.server_port), 'launch': server.sessions.issue()}), flush=True)
    try:
        # Each line asks for a fresh synthetic one-use browser handoff, or Quit.
        for line in sys.stdin:
            if line.strip() == 'quit':
                break
            if line.strip() == 'launch':
                print(json.dumps({'launch': server.sessions.issue()}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        fixture.doCleanups()


if __name__ == '__main__':
    main()
