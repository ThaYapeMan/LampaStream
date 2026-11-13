"""Explicit stopped-service cutover from GRID-01 JSON to SQLite.

The exact original cache JSON is archived before import. Old analyser rows are
retained as superseded and are not interpreted by the current runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from . import VERSION, TrackGrid
from .database import GridDatabase


def migrate(directory, destination):
    directory, destination = Path(directory), Path(destination).absolute()
    if destination.exists():
        # Idempotent only after a successful schema-checked cutover.
        database = GridDatabase(destination)
        with database.connect():
            pass
        return False
    files = sorted(directory.glob('*.json'))
    contents = {path.name: path.read_bytes() for path in files}
    digest = hashlib.sha256()
    for name, raw in contents.items():
        digest.update(name.encode())
        digest.update(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if files:
        archive = destination.with_name(f'grids.pre-sqlite.{digest.hexdigest()}.tar')
        if archive.exists():
            with tarfile.open(archive) as backup:
                saved = {member.name: backup.extractfile(member).read()
                         for member in backup.getmembers()}
            if saved != contents:
                raise ValueError('Grid migration backup differs')
        else:
            with tarfile.open(archive, 'x') as backup:
                for path in files:
                    backup.add(path, arcname=path.name, recursive=False)
            os.chmod(archive, 0o600)
    fd, temporary = tempfile.mkstemp(prefix='grids-migration-', dir=destination.parent)
    os.close(fd)
    os.unlink(temporary)
    try:
        database = GridDatabase.create(temporary)
        with database.connect() as db:
            for name, raw in contents.items():
                if name.startswith('identity-'):
                    continue
                value = json.loads(raw)
                key = name.removesuffix('.json')
                if (len(key) != 64 or value['file_sha256'] != key or value.get('provisional')
                        or any(c not in '0123456789abcdef' for c in key)):
                    raise ValueError('Invalid historical grid cache entry')
                obsolete = value['analyser_version'] != VERSION
                if not obsolete:
                    TrackGrid.from_dict(value)
                db.execute('''INSERT INTO grids VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (key, value['analyser_version'], int(value['analyser_version']),
                            raw.decode(), value['timing_basis'], value['confidence'], 'lms-file',
                            value['duration'],
                            value.get('source_sample_rate', value['sample_rate']),
                            value.get('source_channels', 2), 0., 0, int(obsolete)))
            for name, raw in contents.items():
                if not name.startswith('identity-'):
                    continue
                alias = name[len('identity-'):-len('.json')]
                if len(alias) != 64 or any(c not in '0123456789abcdef' for c in alias):
                    raise ValueError('Invalid historical grid alias')
                key = json.loads(raw)['sha256']
                row = db.execute('SELECT analyser_version,duration FROM grids '
                                 'WHERE content_hash=?', (key,)).fetchone()
                if row:
                    db.execute('INSERT INTO identities VALUES(?,?,?,NULL,NULL,NULL,?)',
                               (alias, key, row[0], row[1]))
            db.execute("INSERT INTO maintenance VALUES('json-cutover',0)")
        # The installer owns the lock and stops the service. Detect external
        # changes rather than publishing a database imported from stale bytes.
        if ({path.name: path.read_bytes() for path in directory.glob('*.json')} != contents):
            raise ValueError('Grid cache changed during migration')
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
        Path(temporary+'.lock').unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        changed = migrate(args.directory, args.destination)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f'Grid migration failed safely: {type(error).__name__}\n')
    print('Grid database: migrated' if changed else 'Grid database: current')


if __name__ == '__main__':
    main()
