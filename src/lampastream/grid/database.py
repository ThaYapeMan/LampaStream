"""Versioned grid storage. Audio and source paths never enter this database.

Installation owns migration; runtime opens only the current database schema.
Connections are short lived so the acquisition worker and maintenance can share
one database without sharing Python connection objects between threads.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from . import GRID_SCHEMA_VERSION, VERSION, TrackGrid

DATABASE_VERSION = 1
DDL = """
CREATE TABLE grids (
    content_hash TEXT NOT NULL,
    analyser_version TEXT NOT NULL,
    grid_schema_version INTEGER NOT NULL,
    grid_json TEXT NOT NULL,
    timing_basis TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL CHECK(source IN ('lms-file','airplay-rolling','airplay-learned','shared')),
    duration REAL NOT NULL CHECK(duration > 0),
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    created REAL NOT NULL,
    last_used INTEGER NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0 CHECK(superseded IN (0,1)),
    PRIMARY KEY(content_hash, analyser_version)
);
CREATE TABLE identities (
    identity_hash TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    analyser_version TEXT NOT NULL,
    fingerprint_json TEXT,
    artist TEXT,
    title TEXT,
    duration REAL,
    FOREIGN KEY(content_hash,analyser_version) REFERENCES grids(content_hash,analyser_version)
);
CREATE INDEX identities_fingerprint ON identities(content_hash);
CREATE TABLE track_metadata (
    identity_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    ttl REAL NOT NULL,
    fields_json TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    redistributable INTEGER NOT NULL DEFAULT 0 CHECK(redistributable IN (0,1)),
    PRIMARY KEY(identity_hash,provider)
);
CREATE TABLE lookups (
    identity_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    query_json TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_at REAL NOT NULL,
    retry_after REAL NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(identity_hash,provider)
);
CREATE TABLE maintenance (
    name TEXT PRIMARY KEY,
    completed_at REAL NOT NULL
);
"""


def identity_hash(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()


def encode(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':'))


class GridDatabase:
    def __init__(self, path=None, *, limit=2000):
        path = path if path is not None else os.environ.get(
            'LAMPASTREAM_GRIDS_DB', '/var/lib/lampastream/grids.db')
        self.path = Path(path).absolute()
        if limit < 1:
            raise ValueError('Grid limit must be positive')
        self.limit = limit

    @property
    def restore_marker(self):
        return self.path.with_name(self.path.name+'.restore-pending')

    @contextmanager
    def lease(self, *, exclusive=False):
        """Coordinate online users and whole-file restore across processes."""
        descriptor = os.open(str(self.path)+'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                             0o600)
        try:
            if os.geteuid() == 0:
                owner = self.path.stat() if self.path.exists() else self.path.parent.stat()
                os.fchown(descriptor, owner.st_uid, owner.st_gid)
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            os.close(descriptor)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=5)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            if connection.execute('PRAGMA user_version').fetchone()[0] != DATABASE_VERSION:
                raise ValueError('Grid database migration required')
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def connect(self):
        # Missing installation is a miss/error, never a historical JSON read.
        if not self.path.exists():
            raise sqlite3.OperationalError('Grid database does not exist')
        with self.lease():
            if self.restore_marker.exists():
                raise sqlite3.OperationalError('Grid restore recovery is pending')
            with self._connect() as connection:
                yield connection

    @classmethod
    def create(cls, path, *, limit=2000):
        path = Path(path).absolute()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            database = cls(path, limit=limit)
            with database.connect():
                pass
            return database
        fd, temporary = tempfile.mkstemp(prefix='grids-create-', dir=path.parent)
        os.close(fd)
        try:
            connection = sqlite3.connect(temporary)
            try:
                with connection:
                    connection.executescript(DDL)
                    connection.execute(f'PRAGMA user_version={DATABASE_VERSION}')
            finally:
                connection.close()
            # Publish a complete database, without replacing a concurrent one.
            try:
                os.link(temporary, path)
            except FileExistsError:
                with cls(path, limit=limit).connect():
                    pass
        finally:
            os.unlink(temporary)
        return cls(path, limit=limit)

    def get(self, identity):
        return self._get('i.identity_hash=?', (identity_hash(identity),))

    def get_hash(self, content_hash):
        return self._get('g.content_hash=?', (content_hash,))

    def _get(self, condition, parameters):
        with self.connect() as db:
            row = db.execute(f'''SELECT g.grid_json,g.content_hash,g.analyser_version
                FROM grids g LEFT JOIN identities i
                ON i.content_hash=g.content_hash AND i.analyser_version=g.analyser_version
                WHERE {condition} AND g.analyser_version=? AND g.superseded=0 LIMIT 1''',
                (*parameters, VERSION)).fetchone()
            if row is None:
                return None
            try:
                grid = TrackGrid.from_dict(json.loads(row[0]))
            except (ValueError, TypeError, KeyError):
                return None
            db.execute('UPDATE grids SET last_used='
                       '(SELECT COALESCE(MAX(last_used),0)+1 FROM grids) '
                       'WHERE content_hash=? AND analyser_version=?', (row[1], row[2]))
            return grid

    def put(self, identity, grid, *, source='lms-file', fingerprint=None,
            artist=None, title=None):
        if grid.provisional:
            raise ValueError('A provisional grid cannot enter the full-file cache')
        TrackGrid.from_dict(grid.to_dict())
        fingerprint = fingerprint or grid.audio_fingerprint
        with self.connect() as db:
            db.execute('UPDATE grids SET superseded=1 WHERE content_hash=? '
                       'AND analyser_version<>?', (grid.file_sha256, grid.analyser_version))
            lru = db.execute('SELECT COALESCE(MAX(last_used),0)+1 FROM grids').fetchone()[0]
            db.execute('''INSERT INTO grids VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(content_hash,analyser_version) DO UPDATE SET
                grid_json=excluded.grid_json,last_used=excluded.last_used,superseded=0''',
                (grid.file_sha256, grid.analyser_version, GRID_SCHEMA_VERSION,
                 encode(grid.to_dict()),
                 grid.timing_basis, grid.confidence, source, grid.duration,
                 grid.source_sample_rate, grid.source_channels, time.time(), lru))
            db.execute('''INSERT INTO identities VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(identity_hash) DO UPDATE SET content_hash=excluded.content_hash,
                analyser_version=excluded.analyser_version,
                fingerprint_json=excluded.fingerprint_json,artist=excluded.artist,
                title=excluded.title,duration=excluded.duration''',
                (identity_hash(identity), grid.file_sha256, grid.analyser_version,
                 encode(fingerprint) if fingerprint else None,
                 artist.strip().casefold() if artist else None,
                 title.strip().casefold() if title else None, grid.duration))
            self._evict(db)

    def match_fingerprint(self, query):
        """Return a unique segment match; a caller must respect its offset."""
        from .fingerprint import Fingerprint, match
        with self.connect() as db:
            rows = db.execute("""SELECT DISTINCT i.content_hash,i.fingerprint_json
                FROM identities i JOIN grids g USING(content_hash,analyser_version)
                WHERE g.superseded=0 AND g.analyser_version=?
                AND i.fingerprint_json IS NOT NULL""", (VERSION,)).fetchall()
        matches = []
        for key, raw in rows:
            result = match(query, Fingerprint.from_dict(json.loads(raw)))
            if result is not None:
                matches.append((key, result))
        # Ambiguous recordings are rejected rather than attached by metadata.
        if len(matches) != 1:
            return None
        key, result = matches[0]
        return self.get_hash(key), result

    def learned_hint(self, artist, title, duration):
        """Unconfirmed early hint only; never creates a confirmed identity."""
        if not artist or not title or duration is None:
            return None
        with self.connect() as db:
            rows = db.execute("""SELECT DISTINCT g.content_hash FROM identities i
                JOIN grids g USING(content_hash,analyser_version)
                WHERE i.artist=? AND i.title=? AND abs(i.duration-?)<=1
                AND i.fingerprint_json IS NOT NULL AND g.superseded=0
                AND g.analyser_version=?""",
                (artist.strip().casefold(), title.strip().casefold(), duration, VERSION)).fetchall()
        if len(rows) != 1:
            return None
        grid = self.get_hash(rows[0][0])
        return replace(grid, provisional=True) if grid else None

    def _evict(self, db):
        # Historical analyser results are retained. Only current cache entries
        # participate in LRU eviction; provider metadata is independent of LRU.
        victims = db.execute('''SELECT content_hash,analyser_version FROM grids
            WHERE superseded=0 ORDER BY last_used DESC LIMIT -1 OFFSET ?''',
            (self.limit,)).fetchall()
        for content_hash, version in victims:
            db.execute('DELETE FROM identities WHERE content_hash=? AND analyser_version=?',
                       (content_hash, version))
            db.execute('DELETE FROM grids WHERE content_hash=? AND analyser_version=?',
                       (content_hash, version))
        # Alias count is bounded too: many containers of the same content
        # must not grow the identity index without bound.
        db.execute("""DELETE FROM identities WHERE rowid NOT IN (
            SELECT i.rowid FROM identities i JOIN grids g USING(content_hash,analyser_version)
            ORDER BY g.last_used DESC,i.rowid DESC LIMIT ?)""", (self.limit,))

    def maintain(self, *, now=None, interval=7*86400):
        """Run from a maintenance worker, never from a canonical PCM feed."""
        now = time.time() if now is None else now
        with self.connect() as db:
            row = db.execute("SELECT completed_at FROM maintenance WHERE name='vacuum'").fetchone()
            if row and now-row[0] < interval:
                return False
        # VACUUM requires its own transaction boundary and preserves old grids.
        with self.connect() as db:
            db.execute('VACUUM')
            db.execute("INSERT OR REPLACE INTO maintenance VALUES('vacuum',?)", (now,))
        return True

    def backup(self, destination, *, locked=False):
        """SQLite online backup includes committed WAL pages consistently."""
        destination = Path(destination)
        # Do not overwrite an existing backup.
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        try:
            with (self._connect() if locked else self.connect()) as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                finally:
                    target.close()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Grid database maintenance (no audio or network)')
    parser.add_argument('action', choices=('maintain', 'backup'))
    parser.add_argument('--database', default='/var/lib/lampastream/grids.db', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    database = GridDatabase(args.database)
    if args.action == 'backup':
        if args.destination is None:
            parser.error('backup requires --destination')
        database.backup(args.destination)
        print('Grid database backup complete')
    else:
        print('Grid database vacuum complete' if database.maintain() else
              'Grid database vacuum not due')


if __name__ == '__main__':
    main()
