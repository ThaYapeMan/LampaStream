"""Provider lifecycle, recorded acquisition, identity and correction boundary."""
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from lampastream.grid.database import GRID_DDL, GridDatabase, identity_hash
from lampastream.grid.migration import migrate
from lampastream.tempo_metadata.registry import PROVIDERS, Identity
from lampastream.tempo_metadata.store import ProviderStore


def identity():
    return Identity('fp:reference', 'Artist', 'Track', 120.,
                    fingerprint={'duration': 120., 'landmarks': [[i, i] for i in range(32)]})


def store(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    fixture = tmp_path/'provider.json'
    fixture.write_bytes((Path(__file__).parent/'fixtures/metadata/recorded-tempo.json').read_bytes())
    return ProviderStore(database, options={'recorded-fixture': {'fixture': fixture}},
                         allow_test=True, clock=lambda: 1000.)


def test_recorded_fixture_to_metadata_and_resolver(tmp_path):
    service = store(tmp_path)
    assert not service.lookup('recorded-fixture', identity())
    service.configure('recorded-fixture', enabled=True)
    assert service.lookup('recorded-fixture', identity())
    resolved = service.resolve(identity())
    assert resolved['fields'] == {'tempo': 128.}
    assert resolved['provider'] == 'recorded-fixture'
    assert not resolved['redistributable']
    with service.database.connect() as db:
        assert json.loads(db.execute('SELECT raw_payload_json FROM track_metadata').fetchone()[0])[
            'key'] == identity().key
    assert not service.lookup('recorded-fixture', identity())  # TTL retained.


def test_disabled_and_obsolete_rows_kept_and_frozen(tmp_path):
    service = store(tmp_path)
    service.configure('recorded-fixture', enabled=True)
    service.lookup('recorded-fixture', identity())
    service.configure('recorded-fixture', enabled=False)
    assert not service.lookup('recorded-fixture', identity(), force=True)
    assert service.resolve(identity())['fields']['tempo'] == 128.
    service.configure('recorded-fixture', enabled=True)
    assert not service.lookup('recorded-fixture', identity())
    service.specs = {**PROVIDERS, 'recorded-fixture': replace(
        PROVIDERS['recorded-fixture'], status='obsolete')}
    service.clock = lambda: 1.e9
    assert not service.lookup('recorded-fixture', identity(), force=True)
    assert service.resolve(identity())['fields']['tempo'] == 128.
    with service.database.connect() as db:
        assert db.execute('SELECT fetched_at,ttl FROM track_metadata').fetchone() == (1000., 3600.)
    with pytest.raises(ValueError):
        service.configure('recorded-fixture', enabled=True)


def test_active_beats_obsolete_regardless_of_priority_and_owner_wins(tmp_path):
    service = store(tmp_path)
    service.lookup('local-tags', replace(identity(), tags={'TBPM': '126'}))
    service.specs = {**PROVIDERS, 'local-tags': replace(PROVIDERS['local-tags'], status='obsolete')}
    service.configure('recorded-fixture', enabled=True)
    service.lookup('recorded-fixture', identity())
    assert service.resolve(identity())['provider'] == 'recorded-fixture'
    service.lookup('owner', replace(identity(), correction={'tempo': 64., 'phase_offset_s': .02}))
    assert service.resolve(identity())['provider'] == 'owner'
    assert service.resolve(identity())['fields'] == {'tempo': 64., 'phase_offset_s': .02}
    assert not service.resolve(identity())['redistributable']
    service.configure('owner', consent=True)
    assert service.resolve(identity())['redistributable']
    service.configure('owner', consent=False)
    assert not service.resolve(identity())['redistributable']


def test_local_tags_validation_and_hint_cannot_be_an_owner_identity(tmp_path):
    service = store(tmp_path)
    hint = replace(identity(), key='hint:title-and-artist', fingerprint=None, tags={'BPM': '160'})
    assert service.lookup('local-tags', hint)
    assert service.resolve(hint)['fields']['tempo'] == 160.
    assert not service.lookup('owner', replace(hint, correction={'tempo': 80}), force=True)
    assert service.resolve(hint)['provider'] == 'local-tags'
    with pytest.raises(ValueError):
        service.lookup('local-tags', replace(identity(), tags={'TBPM': 'nan'}), force=True)
    assert service.resolve(identity()) is None


def test_schema_one_upgrade_backed_up_atomic_idempotent(tmp_path):
    path = tmp_path/'grids.db'
    with sqlite3.connect(path) as db:
        db.executescript(GRID_DDL)
        db.execute('PRAGMA user_version=1')
        db.execute('INSERT INTO track_metadata VALUES(?,?,?,?,?,?,?,?)',
                   (identity_hash(identity().key), 'owner', 123., 0., '{"tempo":128}', '{}', 1., 0))
    with pytest.raises(ValueError, match='migration required'):
        with GridDatabase(path).connect():
            pass
    assert migrate(tmp_path/'legacy', path)
    assert not migrate(tmp_path/'legacy', path)
    backups = list(tmp_path.glob('grids.db.pre-metadata-v2.*.sqlite'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('PRAGMA user_version').fetchone() == (1,)
    assert ProviderStore(GridDatabase(path)).resolve(identity())['fields'] == {'tempo': 128}


def test_default_external_off_and_test_provider_unavailable_in_production(tmp_path):
    service = ProviderStore(GridDatabase.create(tmp_path/'grids.db'))
    definitions = service.list()
    assert all(not p['enabled'] for p in definitions if p['leaves_lan'])
    assert all(not p['consent'] for p in definitions)
    with pytest.raises(ValueError):
        service.configure('recorded-fixture', enabled=True)
    assert not service.lookup('songbpm', identity(), force=True)
    assert not service.lookup('recorded-fixture', identity(), force=True)
    with pytest.raises(ValueError):
        service.configure('local-tags', enabled=False)


def test_api_fixture_acquisition_owner_controls_and_stale_track_guard(tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from test_grid import grid

    from lampastream.api import router
    from lampastream.storage import Storage
    from lampastream.tempo_metadata.context import current_identity
    from lampastream.track_position import TrackPosition

    service = store(tmp_path)
    fp = dict(duration=20., version=1, landmarks=[[i, i*20] for i in range(32)])
    available = replace(grid(), audio_fingerprint=fp)
    prior = SimpleNamespace(available=available, grid=available)
    manager = SimpleNamespace(track_position=TrackPosition('Track', 'Artist', 0., 20.),
        _active=SimpleNamespace(sync_engine=SimpleNamespace(_analyser=SimpleNamespace(
            _beat_fusion=SimpleNamespace(prior=prior)))))
    current, _ = current_identity(manager)
    fixture = service.options['recorded-fixture']['fixture']
    payload = json.loads(fixture.read_text())
    payload['tracks'][0]['key'] = current.key
    fixture.write_text(json.dumps(payload))
    app = FastAPI()
    app.include_router(router)
    app.state.storage = Storage(tmp_path/'config.json')
    app.state.player_manager = manager
    app.state.tempo_provider_store = service
    with TestClient(app) as client:
        assert client.patch('/api/metadata-providers/recorded-fixture',
                            json={'enabled': True}).status_code == 200
        data = client.get('/api/tempo-metadata').json()
        assert data['confirmed'] and data['tempo'] == 128.
        for action, extra, expected in [('half', {}, 64.), ('double', {}, 128.),
                                        ('tap', {'tempo': 96.}, 96.)]:
            response = client.post('/api/tempo/correction',
                                   json=dict(identity=current.key, action=action, **extra))
            assert response.status_code == 200, response.text
            assert response.json()['tempo'] == expected
            assert response.json()['resolved_tempo']['provider'] == 'owner'
        result = client.post('/api/tempo/correction', json=dict(
            identity=current.key, action='nudge', nudge_ms=20)).json()
        assert result['phase_offset_s'] == .02
        assert client.post('/api/tempo/correction', json=dict(
            identity='fp:old-track', action='nudge', nudge_ms=20)).status_code == 409
        prior.available = prior.grid = None
        assert client.post('/api/tempo/correction', json=dict(
            identity=current.key, action='half')).status_code == 409


def test_invalid_old_schema_does_not_publish_an_upgrade(tmp_path):
    path = tmp_path/'grids.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=1')
        db.execute('CREATE TABLE unexpected(value TEXT)')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Unexpected old grid schema'):
        migrate(tmp_path/'legacy', path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('grids.db.pre-metadata-v2.*'))


def test_file_tag_adapter_uses_recorded_probe_payload_without_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_grid import grid

    from lampastream.tempo_metadata.file_tags import capture
    from lampastream.tempo_metadata.store import fingerprint_key

    service = store(tmp_path)
    fp = dict(duration=20., version=1, landmarks=[[i, i*20] for i in range(32)])
    available = replace(grid(), audio_fingerprint=fp)
    payload = (Path(__file__).parent/'fixtures/metadata/local-tags.json').read_text()
    monkeypatch.setattr('lampastream.tempo_metadata.file_tags.subprocess.run',
                        lambda *a, **kw: SimpleNamespace(stdout=payload))
    capture(tmp_path/'private-file.flac', available, service.database)
    who = Identity(fingerprint_key(fp), fingerprint=fp)
    assert service.resolve(who)['fields'] == {'tempo': 126.}
    with service.database.connect() as db:
        raw = db.execute('SELECT raw_payload_json FROM track_metadata').fetchone()[0]
        assert json.loads(raw) == {'bpm_tag': '126.0'}
        assert 'private-file' not in raw and 'comment' not in raw
    fixture = Path(__file__).parent/'fixtures/metadata/owner-correction.json'
    correction = json.loads(fixture.read_text())
    service.lookup('owner', replace(who, correction=correction), force=True)
    assert service.resolve(who)['fields'] == correction


def test_sender_bpm_metadata_and_unconfirmed_hint_remain_metadata_only(tmp_path):
    from types import SimpleNamespace

    from lampastream.tempo_metadata.context import refresh
    from lampastream.track_position import AirPlayTrackPositionSource, TrackPosition

    # Exercise the real sender metadata decoder without opening a FIFO/socket.
    source = AirPlayTrackPositionSource('/unused')
    source._snapshot = TrackPosition('Track', 'Artist', 0., 120.)
    source._accept_record(('core', 'asbt', (128).to_bytes(2, 'big')))
    assert source.read().tempo_bpm == 128.
    service = store(tmp_path)
    manager = SimpleNamespace(track_position=source.read(), _active=None)
    result = refresh(manager, service)
    assert not result['confirmed']
    assert result['resolved_tempo']['provider'] == 'local-tags'
    assert result['tempo'] == 128.
    with service.database.connect() as db:
        assert db.execute('SELECT count(*) FROM identities').fetchone() == (0,)


def test_rate_limit_is_global_and_failed_refresh_keeps_last_good_row(tmp_path):
    service = store(tmp_path)
    moment = [1000.]
    service.clock = lambda: moment[0]
    service.specs = {**PROVIDERS, 'recorded-fixture': replace(
        PROVIDERS['recorded-fixture'], rate_limit=10., ttl=5.)}
    service.configure('recorded-fixture', enabled=True)
    assert service.lookup('recorded-fixture', identity())
    moment[0] = 1001.
    assert not service.lookup('recorded-fixture', replace(identity(), key='fp:other'), force=True)
    with service.database.connect() as db:
        assert db.execute('SELECT count(*) FROM lookups').fetchone() == (1,)
    fixture = service.options['recorded-fixture']['fixture']
    payload = json.loads(fixture.read_text())
    payload['tracks'][0]['fields']['tempo'] = 'invalid'
    fixture.write_text(json.dumps(payload))
    moment[0] = 1011.
    with pytest.raises(ValueError):
        service.lookup('recorded-fixture', identity())
    assert service.resolve(identity())['fields'] == {'tempo': 128.}
    moment[0] = 1050.
    assert not service.lookup('recorded-fixture', identity(), force=True)
    with service.database.connect() as db:
        assert db.execute('SELECT fetched_at FROM track_metadata').fetchone() == (1000.,)
        assert db.execute('SELECT status FROM lookups').fetchone() == ('failed',)


def test_provisional_grid_hint_cannot_confirm_an_identity():
    from types import SimpleNamespace

    from test_grid import grid

    from lampastream.tempo_metadata.context import current_identity
    from lampastream.track_position import TrackPosition

    fp = dict(duration=20., version=1, landmarks=[[i, i*20] for i in range(32)])
    hint = replace(grid(), provisional=True, audio_fingerprint=fp)
    manager = SimpleNamespace(track_position=TrackPosition('Track', 'Artist', 0., 20.),
        _active=SimpleNamespace(sync_engine=SimpleNamespace(_analyser=SimpleNamespace(
            _beat_fusion=SimpleNamespace(prior=SimpleNamespace(available=hint, grid=hint))))))
    who, _ = current_identity(manager)
    assert who.key.startswith('hint:') and who.fingerprint is None


def test_verified_recording_identity_survives_a_grid_rejection():
    from types import SimpleNamespace

    from test_grid import grid

    from lampastream.tempo_metadata.context import current_identity
    from lampastream.track_position import TrackPosition

    fp = dict(duration=20., version=1, landmarks=[[i, i*20] for i in range(32)])
    verified = replace(grid(), audio_fingerprint=fp)
    source = SimpleNamespace(grid_adapter=SimpleNamespace(grid=verified))
    session = SimpleNamespace(track_source=source, sync_engine=SimpleNamespace(
        _analyser=SimpleNamespace(_beat_fusion=SimpleNamespace(
            prior=SimpleNamespace(available=None, grid=None)))))
    who, _ = current_identity(SimpleNamespace(_active=session,
        track_position=TrackPosition('Track', 'Artist', 0., 20.)))
    assert who.key.startswith('fp:')


def test_empty_local_lookup_is_cached_but_new_sender_bpm_is_observed(tmp_path):
    service = store(tmp_path)
    moment = [1000.]
    service.clock = lambda: moment[0]
    assert not service.lookup('local-tags', identity())
    moment[0] = 1001.
    assert not service.lookup('local-tags', identity())
    with service.database.connect() as db:
        assert db.execute('SELECT requested_at FROM lookups').fetchone() == (1000.,)
    tagged = replace(identity(), tags={'tempo': 130.})
    assert service.lookup('local-tags', tagged)
    assert service.resolve(tagged)['fields']['tempo'] == 130.
    moment[0] = 1002.
    assert not service.lookup('local-tags', tagged)
    with service.database.connect() as db:
        assert db.execute('SELECT requested_at FROM lookups').fetchone() == (1001.,)


def test_full_backup_restores_provider_state_consent_and_owner_rows(tmp_path, monkeypatch):
    from lampastream.backup_archive import export_archive, restore_archive
    from lampastream.models import Effect
    from lampastream.storage import Storage

    service = store(tmp_path)
    monkeypatch.setenv('LAMPASTREAM_GRIDS_DB', str(service.database.path))
    storage = Storage(tmp_path/'config.json')
    storage.save_effect(Effect(id='saved', name='Saved'))
    service.lookup('owner', replace(identity(), correction={'tempo': 64.}), force=True)
    service.configure('owner', consent=True)
    service.configure('recorded-fixture', enabled=True)
    bundle = tmp_path/'providers.zip'
    export_archive(storage, bundle)
    service.lookup('owner', replace(identity(), correction={'tempo': 96.}), force=True)
    service.configure('owner', consent=False)
    service.configure('recorded-fixture', enabled=False)
    restore_archive(storage, bundle)
    assert service.resolve(identity())['fields']['tempo'] == 64.
    assert service.resolve(identity())['redistributable']
    states = {row['name']: row for row in service.list()}
    assert states['owner']['consent'] and states['recorded-fixture']['enabled']
