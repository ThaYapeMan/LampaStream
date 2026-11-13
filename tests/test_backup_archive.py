"""Full backup failure, recovery and real HTTP checks with isolated SQLite data."""
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_grid import grid

from lampastream import backup_archive as archive
from lampastream.api import router
from lampastream.backup import BackupError
from lampastream.grid.database import GridDatabase
from lampastream.models import Effect
from lampastream.storage import Storage


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path/'grids.db'
    monkeypatch.setenv('LAMPASTREAM_GRIDS_DB', str(path))
    storage = Storage(tmp_path/'config.json')
    storage.save_effect(Effect(id='saved', name='Saved'))
    database = GridDatabase.create(path)
    database.put('saved', grid())
    bundle = tmp_path/'backup.zip'
    archive.export_archive(storage, bundle)
    storage.save_effect(Effect(id='later', name='Later'))
    database.put('later', replace(grid(), file_sha256='b'*64))
    return storage, database, bundle


def test_roundtrip_includes_current_grid_and_retained_history_and_safety(setup):
    storage, database, bundle = setup
    before = storage.path.read_bytes()
    safety = archive.restore_archive(storage, bundle)
    assert safety.read_bytes() == before
    assert storage.get_effect('saved') and not storage.get_effect('later')
    assert database.get('saved') == grid() and database.get('later') is None
    copies = list(database.path.parent.glob('.grid-safety-*.db'))
    assert len(copies) == 1 and GridDatabase(copies[0]).get('later')
    assert not archive._journal_path(storage.path).exists()
    assert not database.restore_marker.exists()
    assert bundle.stat().st_mode & 0o777 == 0o600


def test_same_configuration_still_commits_the_grid_restore(setup):
    storage, database, _ = setup
    bundle = storage.path.parent/'same-config.zip'
    archive.export_archive(storage, bundle)
    database.put('last', replace(grid(), file_sha256='c'*64))
    archive.restore_archive(storage, bundle)
    assert database.get('last') is None


def test_config_commit_failure_rolls_database_back_and_leaves_no_journal(setup, monkeypatch):
    storage, database, bundle = setup
    before = storage.path.read_bytes()
    def fail(*args):
        raise BackupError('injected configuration commit failure')
    monkeypatch.setattr(archive, 'restore_configuration', fail)
    with pytest.raises(BackupError, match='injected'):
        archive.restore_archive(storage, bundle)
    assert storage.path.read_bytes() == before
    assert database.get('later') is not None
    assert not archive._journal_path(storage.path).exists()
    assert not database.restore_marker.exists()


@pytest.mark.parametrize('committed', [False, True])
def test_process_death_at_configuration_seam_recovers_on_next_storage_read(setup, committed):
    storage, database, bundle = setup
    original = storage.path.read_bytes()
    script = '''
import os, sys
from pathlib import Path
from lampastream import backup_archive as archive
from lampastream.storage import Storage
original = archive.restore_configuration
def seam(*args):
    if sys.argv[3] == 'True':
        original(*args)
    os._exit(77)
archive.restore_configuration = seam
archive.restore_archive(Storage(Path(sys.argv[1])), Path(sys.argv[2]))
'''
    result = subprocess.run([sys.executable, '-c', script, str(storage.path), str(bundle),
                             str(committed)], env={**os.environ, 'PYTHONPATH': 'src'}, timeout=20)
    assert result.returncode == 77
    assert archive._journal_path(storage.path).exists()
    assert database.restore_marker.exists()
    with pytest.raises(sqlite3.OperationalError, match='pending'):
        database.maintain()
    reopened = Storage(storage.path)
    if committed:
        assert reopened.get_effect('later') is None
        assert database.get('later') is None
    else:
        assert storage.path.read_bytes() == original
        assert database.get('later') is not None
    assert not archive._journal_path(storage.path).exists()
    assert not database.restore_marker.exists()


def test_invalid_archive_and_unexpected_sql_schema_are_refused_before_mutation(setup, tmp_path):
    storage, database, bundle = setup
    before = storage.path.read_bytes()
    bad = tmp_path/'bad.zip'
    with zipfile.ZipFile(bad, 'w') as output:
        output.writestr('../escape', 'bad')
    with pytest.raises(BackupError):
        archive.restore_archive(storage, bad)
    assert storage.path.read_bytes() == before and database.get('later')
    with database.connect() as connection:
        connection.execute('CREATE TABLE unexpected(value TEXT)')
    with pytest.raises(BackupError, match='database'):
        archive.validate_database(database.path)


def test_full_http_download_restore_and_active_rejection(setup):
    storage, database, bundle = setup
    app = FastAPI()
    app.state.storage = storage
    manager = SimpleNamespace(configuration_restore_ready=False)
    app.state.player_manager = manager
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/api/backup/import', content=bundle.read_bytes(),
                           headers={'Content-Type': 'application/zip'}).status_code == 409
        manager.configuration_restore_ready = True
        response = client.post('/api/backup/import', content=bundle.read_bytes(),
                               headers={'Content-Type': 'application/zip'})
        assert response.status_code == 200, response.text
        assert database.get('later') is None
        response = client.get('/api/backup/export')
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        downloaded = storage.path.parent/'downloaded.zip'
        downloaded.write_bytes(response.content)
        with zipfile.ZipFile(downloaded) as snapshot:
            assert set(snapshot.namelist()) == archive.MEMBERS
            assert json.loads(snapshot.read('manifest.json'))['format'] == archive.FORMAT


def test_corrupt_current_database_reports_fixed_errors_and_leaves_both_files(setup):
    storage, database, bundle = setup
    configuration = storage.path.read_bytes()
    database.path.write_bytes(b'not a database')
    with pytest.raises(BackupError, match='cannot be backed up'):
        archive.export_archive(storage, storage.path.parent/'bad-export.zip')
    with pytest.raises(BackupError, match='could not commit'):
        archive.restore_archive(storage, bundle)
    assert storage.path.read_bytes() == configuration
    assert database.path.read_bytes() == b'not a database'
    assert not archive._journal_path(storage.path).exists()
    assert not database.restore_marker.exists()


def test_death_after_journal_removal_recovers_the_orphan_marker(setup):
    storage, database, bundle = setup
    script = '''
import os, sys
from pathlib import Path
from lampastream import backup_archive as archive
from lampastream.storage import Storage
configuration = Path(sys.argv[1])
journal = archive._journal_path(configuration)
original = Path.unlink
def seam(path, *args, **kwargs):
    result = original(path, *args, **kwargs)
    if path == journal:
        os._exit(78)
    return result
Path.unlink = seam
archive.restore_archive(Storage(configuration), Path(sys.argv[2]))
'''
    result = subprocess.run([sys.executable, '-c', script, str(storage.path), str(bundle)],
                            env={**os.environ, 'PYTHONPATH': 'src'}, timeout=20)
    assert result.returncode == 78
    assert not archive._journal_path(storage.path).exists()
    assert database.restore_marker.exists()
    with pytest.raises(sqlite3.OperationalError, match='pending'):
        database.get('saved')
    Storage(storage.path)
    assert not database.restore_marker.exists()
    assert database.get('saved') is not None and database.get('later') is None
