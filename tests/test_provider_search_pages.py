"""Owner-recorded search results; no external requests in tests."""
import os
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from lampastream.grid.database import GridDatabase
from lampastream.tempo_metadata import beatport, songbpm
from lampastream.tempo_metadata.registry import Identity
from lampastream.tempo_metadata.store import ProviderStore

CASES = [
    ('songbpm', songbpm, 'songbpm-search-mau-p.html',
     Identity('hint:mau', 'Mau P', 'Just A Little Bit More', 214), {'tempo': 128.}),
    ('beatport', beatport, 'beatport-search-scarface.html',
     Identity('hint:scarface', 'Darius Syrossian', 'Scarface', 380),
     {'tempo': 128, 'key': 'C Minor', 'genre': 'Tech House'}),
]


@pytest.fixture(params=CASES, ids=['songbpm', 'beatport'])
def recorded(request):
    directory = os.environ.get('LAMPASTREAM_PROVIDER_FIXTURES')
    if not directory:
        pytest.skip('Set LAMPASTREAM_PROVIDER_FIXTURES to owner-recorded provider pages')
    name, module, filename, identity, fields = request.param
    path = Path(directory)/filename
    if not path.is_file():
        pytest.skip(f'Owner-recorded provider page missing: {path}')
    return name, module, path.read_text(), identity, fields


def test_recorded_parser_matches_identity_not_search_rank(recorded):
    _, module, html, identity, fields = recorded
    result = module.parse(html, identity)
    assert result.fields == fields
    assert result.raw_payload
    assert module.parse(html, replace(identity, artist='Different artist')).fields == {}
    assert module.parse(html, replace(identity, title='Different title')).status == 'not_found'
    assert module.parse('<html>changed layout</html>', identity).status == 'layout_changed'


@pytest.mark.serial
def test_recorded_fetch_and_persistence_loopback(recorded, tmp_path):
    name, module, html, identity, fields = recorded
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(('GET', self.path, ''))
            self.respond()

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length'])).decode()
            requests.append(('POST', self.path, body))
            self.respond()

        def respond(self):
            body = html.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(trust_env=False, follow_redirects=True) as client:
            url = f'http://127.0.0.1:{server.server_port}/searches'
            store = ProviderStore(GridDatabase.create(tmp_path/'grid.db'),
                                  options={name: {'url': url, 'client': client}},
                                  clock=lambda: 1000.)
            assert not store.lookup(name, identity)
            store.configure(name, enabled=True)
            assert store.lookup(name, identity)
            assert store.resolve(identity)['fields'] == fields
            rows = store.display_rows(identity)
            assert rows[0]['fields'] == fields
            assert rows[0]['fetched_at'] == 1000.
            assert not store.resolve(identity)['redistributable']
            assert not store.lookup(name, replace(identity, tags={'BPM': 90}))
            assert len(requests) == 1
            method, path, body = requests[0]
            if name == 'songbpm':
                assert method == 'POST'
                assert parse_qs(body) == {'query': [f'{identity.artist} {identity.title}']}
            else:
                assert method == 'GET'
                assert parse_qs(urlsplit(path).query) == {
                    'q': [f'{identity.artist} {identity.title}']}
            assert next(p for p in store.list() if p['name'] == name)['lookup']['status'] == 'ready'
            store.configure(name, enabled=False)
            assert store.display_rows(identity) == []
            with pytest.raises(ValueError):
                store.configure(name, consent=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('module', [songbpm, beatport])
@pytest.mark.parametrize('status', [403, 404, 429, 500])
def test_adapter_http_status_is_clean(module, status):
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(status))) as client:
        result = module.Adapter(client=client).lookup(Identity('x', 'Artist', 'Title'))
    assert result.fields == {}
    assert result.status in ('blocked', 'not_found', 'http_error')


@pytest.mark.parametrize('module', [songbpm, beatport])
def test_timeout_does_not_escape_adapter(module):
    def timeout(request):
        raise httpx.ReadTimeout('loopback timeout simulation', request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = module.Adapter(client=client).lookup(Identity('x', 'Artist', 'Title'))
    assert result.fields == {}
    assert result.status == 'timeout'


@pytest.mark.parametrize('name', ['songbpm', 'beatport'])
def test_no_result_status_cached_and_rate_limited(tmp_path, name):
    requests = []
    def blocked(request):
        requests.append(request)
        return httpx.Response(403)
    now = [1000.]
    with httpx.Client(transport=httpx.MockTransport(blocked)) as client:
        store = ProviderStore(GridDatabase.create(tmp_path/'grid.db'),
                              options={name: {'client': client}}, clock=lambda: now[0])
        store.configure(name, enabled=True)
        identity = Identity('one', 'Artist', 'Title')
        assert not store.lookup(name, identity)
        assert not store.lookup(name, replace(identity, key='two'))  # global rate limit
        now[0] += 2
        assert not store.lookup(name, identity)  # negative result TTL
        assert len(requests) == 1
        assert next(p for p in store.list() if p['name'] == name)['lookup']['status'] == 'blocked'
        now[0] += 86400
        assert not store.lookup(name, identity)
        assert len(requests) == 2
