"""Isolated SQLite storage contracts; never opens a production database."""
import json
import sqlite3
from dataclasses import replace

import pytest
from test_grid import grid

from lampastream.grid.database import DATABASE_VERSION, GridDatabase, identity_hash


def test_installation_is_explicit_and_runtime_rejects_old_schema(tmp_path):
    path = tmp_path/'grids.db'
    database = GridDatabase(path)
    with pytest.raises(sqlite3.OperationalError):
        database.get('file')
    assert not path.exists()
    GridDatabase.create(path)
    with database.connect() as connection:
        connection.execute('PRAGMA user_version=0')
    with pytest.raises(ValueError, match='migration required'):
        database.get('file')


def test_roundtrip_restart_and_bounded_lru(tmp_path):
    path = tmp_path/'grids.db'
    database = GridDatabase.create(path, limit=2)
    for key in 'ab':
        database.put(key, replace(grid(), file_sha256=key*64))
    assert database.get('a')
    database.put('c', replace(grid(), file_sha256='c'*64))
    assert database.get('b') is None
    assert database.get_hash('b'*64) is None
    assert GridDatabase(path).get('a').file_sha256 == 'a'*64
    assert database.get('c').file_sha256 == 'c'*64
    with database.connect() as connection:
        assert connection.execute('SELECT count(*) FROM grids').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM identities').fetchone()[0] == 2
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_provisional_rejected_and_old_versions_retained(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    with pytest.raises(ValueError, match='provisional'):
        database.put('a', replace(grid(), provisional=True))
    database.put('a', grid())
    old = replace(grid(), analyser_version='old').to_dict()
    with database.connect() as connection:
        connection.execute('''INSERT INTO grids SELECT content_hash,'old',grid_schema_version,
            ?,timing_basis,confidence,source,duration,sample_rate,channels,created,last_used,0
            FROM grids''', (json.dumps(old),))
    database.put('a', grid())
    with database.connect() as connection:
        assert connection.execute("SELECT superseded FROM grids WHERE analyser_version='old'") \
            .fetchone() == (1,)
    assert database.get('a') == grid()


def test_consistent_backup_and_scheduled_vacuum(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    database.put('a', grid())
    assert database.maintain(now=100)
    assert not database.maintain(now=101)
    assert database.maintain(now=100+7*86400)
    destination = tmp_path/'backup.db'
    database.backup(destination)
    assert GridDatabase(destination).get('a') == grid()
    with pytest.raises(FileExistsError):
        database.backup(destination)
    with database.connect() as connection:
        assert connection.execute('PRAGMA user_version').fetchone() == (DATABASE_VERSION,)
        assert connection.execute('SELECT identity_hash FROM identities').fetchone() == (
            identity_hash('a'),)


def test_failed_provider_or_bad_source_cannot_mutate_grid_transaction(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    database.put('a', grid())
    with pytest.raises(sqlite3.IntegrityError):
        database.put('bad', replace(grid(), file_sha256='b'*64), source='unknown')
    assert database.get('bad') is None
    assert database.get('a') == grid()


def test_alias_count_is_bounded_for_identical_content(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db', limit=2)
    for identity in ('one', 'two', 'three'):
        database.put(identity, grid())
    with database.connect() as connection:
        assert connection.execute('SELECT count(*) FROM identities').fetchone() == (2,)
        assert connection.execute('SELECT count(*) FROM grids').fetchone() == (1,)


def test_cache_construction_and_misses_do_not_create_service_directories(tmp_path):
    from lampastream.grid.cache import GridCache
    root = tmp_path/'not-created'
    cache = GridCache(root)
    assert cache.get('missing') is None
    assert cache.get_hash('a'*64) is None
    assert not root.exists()
    cache.put('a', grid())
    assert cache.get('a') == grid()


def test_cache_never_migrates_or_reads_historical_json_at_runtime(tmp_path):
    from lampastream.grid.cache import GridCache
    (tmp_path/('a'*64+'.json')).write_text(json.dumps(grid().to_dict()))
    cache = GridCache(tmp_path)
    assert cache.get_hash('a'*64) is None
    with pytest.raises(ValueError, match='migration required'):
        cache.put('a', grid())
    assert not cache.path.exists()


def test_early_hint_requires_duration_and_remains_provisional_and_source_independent(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    value = replace(grid(), audio_fingerprint=dict(version=1, duration=20., landmarks=()))
    database.put('file', value, artist='Artist', title='Title')
    hint = database.learned_hint(' artist ', 'TITLE', 20.9)
    assert hint is not None and hint.provisional
    assert not database.get('file').provisional
    assert database.learned_hint('Artist', 'Title', 21.1) is None
    assert database.learned_hint('Other', 'Title', 20) is None
    assert database.learned_hint('Artist', 'Title', None) is None
    with pytest.raises(ValueError, match='provisional'):
        database.put('unconfirmed', hint)
    database.put('other-master', replace(value, file_sha256='b'*64),
                 artist='Artist', title='Title')
    assert database.learned_hint('Artist', 'Title', 20) is None


def test_lru_order_is_an_opaque_counter_not_a_listening_timestamp(tmp_path):
    database = GridDatabase.create(tmp_path/'grids.db')
    database.put('a', grid())
    database.get('a')
    with database.connect() as connection:
        assert connection.execute('SELECT last_used FROM grids').fetchone() == (2,)
