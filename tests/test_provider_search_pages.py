"""Owner-recorded search results; no external requests in tests."""
import json
import os
import subprocess
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
     Identity('hint:mau', 'Mau P', 'Just A Little Bit More', 214),
     {'tempo': 128., 'match': 'exact', 'key': 'C♯/D♭', 'duration': 214}),
    ('beatport', beatport, 'beatport-search-scarface.html',
     Identity('hint:scarface', 'Darius Syrossian', 'Scarface', 380),
     {'tempo': 128, 'key': 'C Minor', 'genre': 'Tech House',
      'match': 'exact', 'duration': 380.666}),
    ('songbpm', songbpm, 'songbpm-search-mau-p-live-2026-11-13.html', None,
     {'tempo': 128., 'key': 'C♯/D♭', 'duration': 214, 'match': 'base_title'}),
    ('beatport', beatport, 'beatport-search-mau-p-live-2026-11-13.html', None,
     {'tempo': 128, 'key': 'Gb Major', 'genre': 'Dance / Pop',
      'duration': 381.221, 'match': 'exact'}),
]


@pytest.fixture(params=CASES, ids=['songbpm', 'beatport', 'songbpm-live', 'beatport-live'])
def recorded(request):
    directory = os.environ.get('LAMPASTREAM_PROVIDER_FIXTURES')
    if not directory:
        pytest.skip('Set LAMPASTREAM_PROVIDER_FIXTURES to owner-recorded provider pages')
    name, module, filename, identity, fields = request.param
    path = Path(directory)/filename
    if identity is None:
        audio = Path(directory).parent / 'lights-01/mau-p-just-a-little-bit-more-extended.flac'
        duration = float(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', str(audio)]))
        identity = Identity('hint:mau-live', 'Mau P', 'Just A Little Bit More (Extended)', duration)
    return name, module, path.read_text(), identity, fields


def test_recorded_parser_matches_identity_not_search_rank(recorded):
    _, module, html, identity, fields = recorded
    result = module.parse(html, identity)
    assert result.fields == fields
    assert result.raw_payload
    other = replace(identity, artist='Different artist', duration=None)
    assert module.parse(html, other).fields == {}
    assert module.parse(html, replace(identity, title='Different title')).status == 'not_found'
    assert module.parse('<html>changed layout</html>', identity).status == 'unreadable'


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


def beatport_page(*tracks):
    payload = {'props': {'pageProps': {'dehydratedState': {'queries': [
        {'state': {'data': {'tracks': {'data': tracks}}}},
    ]}}}}
    return '<script id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'


def track(*, mix='', duration=200, tempo=128, key='Gb Maj', genre='Dance / Pop', **extra):
    return dict({'track_name': 'Night – Drive', 'mix_name': mix, 'length': duration * 1000,
                 'bpm': tempo, 'key_name': key, 'genre': [{'genre_name': genre}],
                 'artists': [{'artist_name': 'Other', 'artist_type_name': 'Artist'},
                             {'artist_name': 'Béa', 'artist_type_name': 'Artist'}]}, **extra)


def song(*, artist='LES PAUL', title='Love Sneakin’ Up On You', duration='3:26', bpm=96):
    return (f'<a href="/@example/song"><p>{artist}</p><p>{title}</p>'
            f'<span>Key</span><span>G</span><span>Duration</span><span>{duration}</span>'
            f'<span>BPM</span><span>{bpm}</span></a>')


@pytest.mark.parametrize('suffix', ['(Extended)', '(Extended Version)', '- Extended Mix'])
def test_separate_mix_equivalence_and_artist_credits(suffix):
    result = beatport.parse(beatport_page(track(mix='Extended Mix')), Identity(
        'night', 'Unknown & Someone', f'Night — Drive (feat. Bea) {suffix}', 300))
    assert result.fields == dict(tempo=128, duration=200, key='Gb Maj',
                                 genre='Dance / Pop', match='exact')


def test_plain_and_original_mix():
    identity = Identity('mic', 'Lucas Alexander', 'Mic Check (Original Mix)')
    assert songbpm.parse(song(artist='Lucas Alexander', title='Mic Check'),
                         identity).fields['match'] == 'exact'
    assert beatport.parse(beatport_page(track(mix='Original Mix')),
                          Identity('night', 'Bea', 'Night - Drive')).fields['match'] == 'exact'


def test_isrc_precedes_artist_and_title_and_remixer_is_excluded():
    remix = track(isrc='GBABC2600001', artists=[
        {'artist_name': 'Bea', 'artist_type_name': 'Remixer'}])
    identity = Identity('night', 'Bea', 'Night - Drive')
    assert beatport.parse(beatport_page(remix), identity).status == 'not_found'
    identity = replace(identity, title='Different title', isrc='gb-abc-26-00001')
    assert beatport.parse(beatport_page(track(), remix), identity).fields['match'] == 'isrc'


def test_version_then_unique_duration_then_consensus():
    identity = Identity('night', 'Bea', 'Night Drive (Extended)', 201)
    exact = track(mix='Extended', duration=320, tempo=130)
    near = track(mix='Original Mix', duration=201, tempo=122)
    far = track(mix='Club Mix', duration=220, tempo=128)
    result = beatport.parse(beatport_page(near, exact), identity)
    assert (result.fields['match'], result.fields['tempo']) == ('exact', 130)
    result = beatport.parse(beatport_page(exact, track(mix='Extended Mix')), identity)
    assert (result.fields['match'], result.fields['tempo']) == ('exact', 128)
    result = beatport.parse(beatport_page(far, near), identity)
    assert (result.fields['match'], result.fields['tempo']) == ('duration', 122)
    other = track(mix='Radio Edit', duration=170, tempo=128.5, key='A Minor')
    result = beatport.parse(beatport_page(other, far), identity)
    assert result.fields == dict(match='base_title', tempo=128, genre='Dance / Pop')
    assert beatport.parse(beatport_page(exact, track(mix='Extended Mix')),
                          replace(identity, duration=None)).status == 'ambiguous'
    assert beatport.parse(beatport_page(near, far),
                          replace(identity, duration=None)).status == 'ambiguous'


def test_album_artist_and_unique_title_duration():
    identity = Identity('paul', 'Sting & Joss Stone', "Love Sneakin' Up On You", 205.56)
    album = songbpm.parse(song(), replace(identity, album_artist='Les Paul & Friends'))
    assert album.fields['match'] == 'exact'
    guest = songbpm.parse(song(), identity)
    assert guest.fields['match'] == 'title_duration'
    assert guest.fields['artist'] == 'LES PAUL'
    assert guest.confidence < album.confidence
    assert songbpm.parse(song() + song(artist='Different'), identity).status == 'not_found'
    assert songbpm.parse(song(), replace(identity, duration=None)).status == 'not_found'


def test_songbpm_versionless_short_release_gives_base_title():
    identity = Identity('example', 'Example', 'Number One (Extended)', 381)
    result = songbpm.parse(song(artist='Example', title='Number One', duration='3:34'), identity)
    assert result.fields == dict(match='base_title', tempo=96., key='G', duration=214)


@pytest.mark.parametrize('module, empty', [(beatport, beatport_page()),
                                           (songbpm, '<p>No results found</p>')])
def test_unreadable_versus_empty(module, empty):
    identity = Identity('x', 'Artist', 'Title')
    assert module.parse('<html><p>Layout changed</p></html>', identity).status == 'unreadable'
    assert module.parse(empty, identity).status == 'not_found'


@pytest.mark.parametrize('name', ['songbpm', 'beatport'])
def test_adapter_version_and_retention(tmp_path, name, caplog):
    from lampastream.grid.database import identity_hash
    from lampastream.tempo_metadata.registry import PROVIDERS
    caplog.set_level('INFO', logger='lampastream.tempo_metadata')
    identity = Identity('one', 'Bea', 'Night Drive', 200)
    current = [1000.]
    statuses = [200, 500]
    html = (song(artist='Bea', title='Night Drive', duration='3:20')
            if name == 'songbpm' else beatport_page(track()))
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(statuses.pop(0), text=html))) as client:
        database = GridDatabase.create(tmp_path/'grid.db')
        store = ProviderStore(database, options={name: {'client': client}},
                              clock=lambda: current[0])
        store.configure(name, enabled=True)
        with database.connect() as db:
            db.execute('INSERT INTO lookups VALUES(?,?,?,?,?,?,0)',
                       (identity_hash(identity.key), name, '{"artist":"Bea","title":"Night Drive"}',
                        'not_found', 990., 991.))
        assert store.lookup(name, identity)
        assert 'query="Bea Night Drive" http=200' in caplog.messages[-1]
        assert 'candidates=1 accepted=' in caplog.messages[-1]
        assert 'match=exact tempo=' in caplog.messages[-1]
        with database.connect() as db:
            query = json.loads(db.execute('SELECT query_json FROM lookups').fetchone()[0])
            assert query['adapter_version'] == PROVIDERS[name].adapter_version == 2
            query.pop('adapter_version')
            db.execute('UPDATE lookups SET query_json=?', (json.dumps(query),))
        assert not store.lookup(name, identity)
        assert len(caplog.records) == 1
        current[0] += 86401
        assert not store.lookup(name, identity)
        assert 'http=500' in caplog.messages[-1]
        assert 'accepted=- reason=http_error' in caplog.messages[-1]
        assert len(caplog.records) == 2
        assert not store.lookup(name, identity)
        row, = store.display_rows(identity)
        assert row['stale'] and row['age_s'] == 86401.
        assert row['fetched_at'] == 1000.
        assert row['fields']['match'] == 'exact'
        assert store.resolve(identity)['fields'] == row['fields']
