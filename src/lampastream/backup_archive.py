"""Full configuration/grid backups with bounded RAM and recoverable publication.

The current configuration JSON format remains independently usable. ZIP bundles
add a SQLite online snapshot. Restore publishes the database before the atomic
configuration commit; a durable journal selects rollback or completion after a
crash. No audio, source activation or historical schema conversion is involved.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from .backup import (
    MAX_BACKUP_BYTES,
    BackupError,
    decode_backup,
    encode_backup,
    export_configuration,
    restore_configuration,
    validate_backup,
)
from .grid.database import DATABASE_VERSION, DDL, GridDatabase
from .storage import Storage

FORMAT = 'lampastream-full-backup'
VERSION = 1
MAX_ARCHIVE_BYTES = 64*1024**3
MEMBERS = {'configuration.json', 'grids.db', 'manifest.json'}


def database_path():
    return GridDatabase().path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _copy(source, target, *, owner=None):
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as out, Path(source).open('rb') as incoming:
        if owner is not None:
            os.fchown(out.fileno(), owner.st_uid, owner.st_gid)
            os.fchmod(out.fileno(), owner.st_mode & 0o777)
        shutil.copyfileobj(incoming, out, length=1024**2)
        out.flush()
        os.fsync(out.fileno())


def _temporary(parent, prefix):
    descriptor, name = tempfile.mkstemp(dir=parent, prefix=prefix, suffix='.db')
    os.close(descriptor)
    Path(name).unlink()
    return Path(name)


def _schema(connection):
    return connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                              "ORDER BY type,name").fetchall()


def validate_database(path):
    """Only our exact current schema is accepted; no SQL from the upload executes."""
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA query_only=ON')
            if db.execute('PRAGMA user_version').fetchone() != (DATABASE_VERSION,):
                raise ValueError('version')
            with closing(sqlite3.connect(':memory:')) as reference:
                reference.executescript(DDL)
                if _schema(db) != _schema(reference):
                    raise ValueError('schema')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('integrity')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('references')
    except (OSError, ValueError, sqlite3.Error):
        raise BackupError('Invalid or non-current grid database') from None


def export_archive(storage, destination, *, grids=None):
    """Write a new ZIP without retaining SQLite pages or ZIP bytes in RAM."""
    grids = Path(grids) if grids is not None else database_path()
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix='lampastream-backup-') as directory:
        directory = Path(directory)
        configuration = directory/'configuration.json'
        snapshot = directory/'grids.db'
        with Storage.configuration_transaction():
            _write(configuration, encode_backup(export_configuration(storage)))
            try:
                if grids.exists():
                    GridDatabase(grids).backup(snapshot)
                else:
                    GridDatabase.create(snapshot)
            except (sqlite3.Error, ValueError):
                raise BackupError('Grid database cannot be backed up') from None
        validate_database(snapshot)
        manifest = dict(format=FORMAT, version=VERSION,
                        sha256={name: digest(directory/name)
                                for name in ('configuration.json', 'grids.db')})
        _write(directory/'manifest.json', json.dumps(manifest).encode())
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w+b') as stream:
                with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    for name in sorted(MEMBERS):
                        archive.write(directory/name, arcname=name)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def _unpack(source, directory):
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != len(MEMBERS) or {entry.filename for entry in entries} != MEMBERS:
                raise ValueError('members')
            total = sum(entry.file_size for entry in entries)
            if total > MAX_ARCHIVE_BYTES or any(entry.flag_bits & 1 for entry in entries):
                raise ValueError('size/encryption')
            limits = {'configuration.json': MAX_BACKUP_BYTES,
                      'manifest.json': 4096, 'grids.db': MAX_ARCHIVE_BYTES}
            for entry in entries:
                if entry.file_size > limits[entry.filename]:
                    raise ValueError('size')
                descriptor = os.open(directory/entry.filename,
                                     os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as out, archive.open(entry) as incoming:
                    written = 0
                    while block := incoming.read(1024**2):
                        written += len(block)
                        if written > limits[entry.filename]:
                            raise ValueError('size')
                        out.write(block)
                    out.flush()
                    os.fsync(out.fileno())
            manifest = json.loads((directory/'manifest.json').read_bytes())
            if (manifest.get('format') != FORMAT or manifest.get('version') != VERSION
                    or manifest.get('sha256') != {
                        name: digest(directory/name)
                        for name in ('configuration.json', 'grids.db')}):
                raise ValueError('manifest')
            backup = decode_backup((directory/'configuration.json').read_bytes())
            validate_database(directory/'grids.db')
            return backup
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        raise BackupError('Invalid full backup: check archive, schema and checksums') from None


def _journal_path(configuration):
    return configuration.with_name(configuration.name+'.restore-pending.json')


def recover_restore(configuration, *, database_locked=False, rollback=False):
    """Called before configuration reads; recovery uses only private local files."""
    configuration = Path(configuration)
    journal = _journal_path(configuration)
    database = GridDatabase(database_path())
    marker = database.restore_marker
    if not journal.exists() and not marker.exists():
        return
    with Storage.configuration_transaction():
        if not database_locked:
            with database.lease(exclusive=True):
                return recover_restore(configuration, database_locked=True, rollback=rollback)
        try:
            if marker.exists():
                marked_configuration = json.loads(marker.read_bytes())['configuration']
                if marked_configuration != str(configuration.absolute()):
                    if journal.exists():
                        raise BackupError('Another full restore is pending for this database')
                    return
            if not journal.exists():
                # Death after journal removal but before marker cleanup. Block
                # database users until the configuration commit is durable.
                _sync_directory(configuration.parent)
                marker.unlink(missing_ok=True)
                _sync_directory(database.path.parent)
                return
        except (OSError, ValueError, KeyError, TypeError):
            raise BackupError('Full restore recovery marker is invalid') from None
        try:
            state = json.loads(journal.read_bytes())
            target = Path(state['database'])
            safety = Path(state['database_safety']) if state['database_safety'] else None
            staging = Path(state['database_staging'])
            # Paths are produced locally, never by ZIP contents. Reject an
            # edited journal instead of allowing it to name arbitrary files.
            if (target != database_path().absolute()
                    or staging.parent != target.parent
                    or not staging.name.startswith('.grid-restore-')
                    or (safety is not None and (safety.parent != target.parent
                        or not safety.name.startswith('.grid-safety-')))):
                raise ValueError('journal paths')
            current = digest(configuration)
            identical_commit = (not rollback
                and state['configuration_before'] == state['configuration_after']
                and target.exists() and digest(target) == state['database_after'])
            if current == state['configuration_before'] and not identical_commit:
                if safety is None:
                    target.unlink(missing_ok=True)
                else:
                    replacement = _temporary(target.parent, '.grid-recover-')
                    try:
                        _copy(safety, replacement, owner=safety.stat())
                        os.replace(replacement, target)
                    finally:
                        replacement.unlink(missing_ok=True)
                _sync_directory(target.parent)
            elif current == state['configuration_after']:
                if not target.exists() or digest(target) != state['database_after']:
                    raise ValueError('committed database missing')
            else:
                raise ValueError('configuration changed outside restore')
            # Ensure the configuration commit is durable before forgetting the
            # transaction. A failed cleanup simply leaves recoverable evidence.
            _sync_directory(configuration.parent)
            staging.unlink(missing_ok=True)
            journal.unlink()
            _sync_directory(configuration.parent)
            marker.unlink(missing_ok=True)
            _sync_directory(target.parent)
        except (OSError, ValueError, KeyError, TypeError):
            raise BackupError('Full restore recovery is pending; stop writers and retry') from None


def restore_archive(storage, source, *, check=False):
    """Restore both files while idle/offline; retain both pre-restore snapshots."""
    configuration = storage.path if isinstance(storage, Storage) else Path(storage)
    with tempfile.TemporaryDirectory(prefix='lampastream-restore-') as directory:
        directory = Path(directory)
        backup = _unpack(source, directory)
        if check:
            return None
        with Storage.configuration_transaction():
            recover_restore(configuration)
            target = database_path().absolute()
            target.parent.mkdir(parents=True, exist_ok=True)
            with GridDatabase(target).lease(exclusive=True):
                marker = GridDatabase(target).restore_marker
                if marker.exists():
                    raise BackupError('Another full restore is pending for this database')
                staging = _temporary(target.parent, '.grid-restore-')
                safety = None
                journal = _journal_path(configuration)
                journal_ready = False
                marker_staging = None
                try:
                    owner = target.stat() if target.exists() else configuration.stat()
                    _copy(directory/'grids.db', staging, owner=owner)
                    if target.exists():
                        safety = _temporary(target.parent, '.grid-safety-')
                        GridDatabase(target).backup(safety, locked=True)
                        os.chown(safety, owner.st_uid, owner.st_gid)
                    raw = (json.dumps(validate_backup(backup), indent=2, sort_keys=True,
                                      allow_nan=False)+'\n').encode()
                    state = dict(configuration_before=digest(configuration),
                                 configuration_after=hashlib.sha256(raw).hexdigest(),
                                 database=str(target),
                                 database_safety=str(safety) if safety else None,
                                 database_staging=str(staging), database_after=digest(staging))
                    _write(journal, json.dumps(state).encode())
                    config_owner = configuration.stat()
                    os.chown(journal, config_owner.st_uid, config_owner.st_gid)
                    _sync_directory(target.parent)
                    _sync_directory(configuration.parent)
                    journal_ready = True
                    marker_staging = _temporary(target.parent, '.grid-marker-')
                    _write(marker_staging, json.dumps({
                        'configuration': str(configuration.absolute())}).encode())
                    os.chown(marker_staging, config_owner.st_uid, config_owner.st_gid)
                    os.replace(marker_staging, marker)
                    _sync_directory(target.parent)
                    os.replace(staging, target)
                    _sync_directory(target.parent)
                    result = restore_configuration(storage, backup)
                except BaseException as error:
                    if journal_ready:
                        recover_restore(configuration, database_locked=True, rollback=True)
                    else:
                        journal.unlink(missing_ok=True)
                    if (not isinstance(error, BackupError)
                            and isinstance(error, (OSError, sqlite3.Error, ValueError))):
                        raise BackupError('Full restore could not commit; safety copies retained') \
                            from None
                    raise
                finally:
                    if marker_staging is not None:
                        marker_staging.unlink(missing_ok=True)
                    if not journal.exists():
                        staging.unlink(missing_ok=True)
                # The configuration rename is the commit. Cleanup failure cannot
                # turn a committed restore into an ambiguous error response.
                try:
                    recover_restore(configuration, database_locked=True)
                except BackupError:
                    pass
                return result



def main():
    import argparse

    from .backup import configuration_lease
    parser = argparse.ArgumentParser(description='Full configuration and grid database backup')
    parser.add_argument('--config', type=Path,
                        default=Path(os.environ.get('LAMPASTREAM_CONFIG',
                                                    '/etc/lampastream/config.json')))
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('export').add_argument('file', type=Path)
    restore = actions.add_parser('import')
    restore.add_argument('file', type=Path)
    restore.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        if not args.config.is_file():
            raise BackupError('Current configuration file does not exist')
        if args.action == 'export':
            export_archive(Storage(args.config), args.file)
            print('Full backup exported (0600); includes controller credentials and grids')
        elif args.check:
            restore_archive(args.config, args.file, check=True)
            print('Full backup schema and checksums valid; nothing changed')
        else:
            with configuration_lease(args.config):
                restore_archive(args.config, args.file)
            print('Configuration and grids restored; safety copies retained; runtime inactive')
    except (BackupError, OSError, ValueError):
        parser.exit(1, 'Full backup operation failed safely; check input and runtime ownership\n')


if __name__ == '__main__':
    main()
