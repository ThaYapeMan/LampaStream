"""Root migration must not strand a service-owned grid behind its stable lock."""
import asyncio
import os
from pathlib import Path

import pytest

from lampastream.grid.cache import GridCache
from lampastream.grid.database import GridDatabase
from lampastream.grid.permissions import check_access, owned_files, set_owner
from lampastream.lms_grid import LmsGridAdapter


@pytest.mark.serial
def test_permission_failure_marks_fetch_failed_and_logs_once(tmp_path, monkeypatch, caplog):
    path = tmp_path/'grids.db'
    GridDatabase.create(path)
    original = os.open
    def denied(file, *args, **kwargs):
        if str(file) == str(path)+'.lock':
            raise PermissionError('root-owned 0600 lock')
        return original(file, *args, **kwargs)
    monkeypatch.setattr(os, 'open', denied)
    async def run():
        adapter = LmsGridAdapter('127.0.0.1', cache=GridCache(tmp_path))
        try:
            adapter.select('track', 100)
            await asyncio.wait_for(adapter.queue.join(), 5)
            assert adapter.state == 'failed'
        finally:
            await adapter.close()
    asyncio.run(run())
    failures = [r for r in caplog.records if 'Library grid unavailable' in r.message]
    assert len(failures) == 1
    assert isinstance(failures[0].exc_info[1], PermissionError)


def test_ownership_inventory_and_check(tmp_path):
    path = tmp_path/'grids.db'
    assert owned_files(path) == (path, Path(str(path)+'.lock'),
                                 Path(str(path)+'.restore-pending'))
    GridDatabase.create(path)
    with pytest.raises(PermissionError):
        check_access(path)
    set_owner(path, os.getuid(), os.getgid())
    check_access(path)
    assert path.stat().st_mode & 0o777 == 0o640
    assert Path(str(path)+'.lock').stat().st_mode & 0o777 == 0o600


@pytest.mark.serial
@pytest.mark.skipif(os.geteuid() != 0,
                    reason='Requires root to create root-owned database and chown directory')
@pytest.mark.parametrize('database_exists', [False, True])
def test_root_lease_uses_service_directory_owner(tmp_path, database_exists):
    path = tmp_path/'grids.db'
    if database_exists:
        GridDatabase.create(path)
    os.chown(tmp_path, 65534, 65534)
    try:
        with GridDatabase(path).lease():
            lock = Path(str(path)+'.lock').stat()
            assert (lock.st_uid, lock.st_gid) == (65534, 65534)
    finally:
        os.chown(tmp_path, 0, 0)


@pytest.mark.skipif(os.geteuid() == 0,
                    reason='Root bypasses mode bits; root lease is tested separately')
def test_check_fails_on_unreadable_lock(tmp_path):
    path = tmp_path/'grids.db'
    GridDatabase.create(path)
    lock = Path(str(path)+'.lock')
    lock.touch(mode=0o600)
    lock.chmod(0)
    try:
        with pytest.raises(PermissionError):
            check_access(path)
    finally:
        lock.chmod(0o600)


def test_installer_reconciles_immediately_and_checks_as_service():
    script = (Path(__file__).resolve().parents[1]/'scripts/install-lampastream.sh').read_text()
    after = script.split('-m lampastream.grid.migration', 1)[1]
    assert after.index('-m lampastream.grid.permissions own') < after.index('chown lampastream:')
    assert 'runuser -u lampastream -- "$environment/bin/python"' in script
    assert '-m lampastream.grid.permissions check' in script
    assert '/var/lib/lampastream /var/lib/lampastream/grids' in script
