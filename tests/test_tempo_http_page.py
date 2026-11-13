"""Provider page transport checks against loopback only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import httpx
import pytest

from lampastream.tempo_metadata.http_page import fetch

pytestmark = pytest.mark.serial


@pytest.fixture
def page_server():
    release = Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == '/slow':
                release.wait(2)
            status = int(self.path[1:]) if self.path[1:].isdigit() else 200
            body = b'<html>loopback transport test</html>'
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()


def test_success_encodes_query_and_preserves_injected_client(page_server):
    base, requests = page_server
    with httpx.Client(trust_env=False) as client:
        page = fetch(base + '/search', params={'q': 'artist & title'}, client=client)
        assert page.status == 'ready'
        assert page.http_status == 200
        assert page.body == '<html>loopback transport test</html>'
        assert requests == ['/search?q=artist+%26+title']
        assert page.payload()['url'] == page.url
        assert not client.is_closed


@pytest.mark.parametrize('code, expected', [
    (401, 'blocked'), (403, 'blocked'), (429, 'blocked'),
    (404, 'not_found'), (500, 'http_error'),
])
def test_http_failures_are_clean_results(page_server, code, expected):
    base, requests = page_server
    with httpx.Client(trust_env=False) as client:
        page = fetch(f'{base}/{code}', client=client)
    assert page.status == expected
    assert page.http_status == code
    assert page.body == ''
    assert len(requests) == 1


def test_bounded_body(page_server):
    base, _ = page_server
    with httpx.Client(trust_env=False) as client:
        page = fetch(base, client=client, max_bytes=8)
    assert page.status == 'too_large'
    assert page.body == ''


def test_timeout_is_clean_result_without_retry(page_server):
    base, requests = page_server
    with httpx.Client(trust_env=False) as client:
        page = fetch(base + '/slow', client=client, timeout=.05)
    assert page.status == 'timeout'
    assert page.body == ''
    assert requests == ['/slow']
