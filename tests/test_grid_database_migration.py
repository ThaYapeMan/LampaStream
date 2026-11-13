"""One-time explicit migration retains aliases and obsolete results, without dual read."""
import hashlib
import json
import tarfile
from dataclasses import replace

import pytest
from test_grid import grid

from lampastream.grid.database import GridDatabase
from lampastream.grid.migration import migrate


def test_once_backed_up_and_old_versions_retained(tmp_path):
    legacy = tmp_path/'grids'
    legacy.mkdir()
    for version, key in [('old', 'b'), (grid().analyser_version, 'a')]:
        value = replace(grid(), file_sha256=key*64, analyser_version=version).to_dict()
        # Historical analyser versions are numeric in the GRID-01 cache.
        if version == 'old':
            value['analyser_version'] = '1'
        (legacy/f'{key*64}.json').write_text(json.dumps(value))
    alias = hashlib.sha256(b'track').hexdigest()
    (legacy/f'identity-{alias}.json').write_text(json.dumps(dict(sha256='a'*64)))
    originals = {p.name: p.read_bytes() for p in legacy.glob('*.json')}
    destination = tmp_path/'grids.db'
    assert migrate(legacy, destination)
    assert GridDatabase(destination).get('track') == grid()
    assert not migrate(legacy, destination)
    archives = list(tmp_path.glob('*.tar'))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as backup:
        assert {m.name: backup.extractfile(m).read() for m in backup.getmembers()} == originals
    with GridDatabase(destination).connect() as db:
        row = db.execute("SELECT superseded FROM grids WHERE analyser_version='1'").fetchone()
        assert row == (1,)
    # Runtime ignores retained historical JSON even if it changes afterwards.
    (legacy/('a'*64+'.json')).write_text('invalid')
    assert GridDatabase(destination).get('track') == grid()


def test_bad_cache_leaves_backup_and_no_database(tmp_path):
    legacy = tmp_path/'grids'
    legacy.mkdir()
    (legacy/('a'*64+'.json')).write_text('invalid')
    destination = tmp_path/'grids.db'
    with pytest.raises(ValueError):
        migrate(legacy, destination)
    assert not destination.exists()
    assert len(list(tmp_path.glob('*.tar'))) == 1
