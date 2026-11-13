"""Provider persistence/resolution; acquisition runs outside canonical analysis."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict
from functools import lru_cache

from ..grid.database import GridDatabase, encode, identity_hash
from .registry import PROVIDERS


class ProviderStore:
    def __init__(self, database=None, *, specs=None, options=None, allow_test=False,
                 clock=time.time):
        self.database = database or GridDatabase()
        self.specs = PROVIDERS if specs is None else specs
        self.options = options or {}
        self.allow_test = allow_test
        self.clock = clock

    def _sync(self, db):
        for name, spec in self.specs.items():
            status = 'obsolete' if spec.status == 'obsolete' else (
                'active' if spec.enabled else 'disabled')
            db.execute('INSERT OR IGNORE INTO metadata_providers VALUES(?,?,?,?,0)',
                       (name, status, int(spec.enabled), spec.priority))
            row = db.execute('SELECT enabled FROM metadata_providers WHERE name=?',
                             (name,)).fetchone()
            status = 'obsolete' if spec.status == 'obsolete' else (
                'active' if row[0] else 'disabled')
            db.execute('UPDATE metadata_providers SET status=?,priority=?,'
                       "enabled=CASE WHEN ?='obsolete' THEN 0 ELSE enabled END "
                       "WHERE name=? AND (status<>? OR priority<>? "
                       "OR (?='obsolete' AND enabled<>0))",
                       (status, spec.priority, status, name, status, spec.priority, status))
        db.execute('INSERT OR IGNORE INTO metadata_providers '
                   "SELECT DISTINCT provider,'obsolete',0,0,0 FROM track_metadata")
        known = tuple(self.specs)
        if known:
            slots = ','.join('?' for _ in known)
            db.execute(f'UPDATE metadata_providers SET status=\'obsolete\',enabled=0 '
                       f'WHERE name NOT IN ({slots})', known)

    def list(self):
        states = {}
        lookups = {}
        if self.database.path.exists():
            with self.database.connect() as db:
                self._sync(db)
                states = {row[0]: row[1:] for row in db.execute(
                    'SELECT name,enabled,status,consent FROM metadata_providers')}
                lookups = {row[0]: dict(status=row[1], requested_at=row[2])
                           for row in db.execute('SELECT provider,status,requested_at FROM lookups '
                                                 'ORDER BY requested_at')}
        result = []
        for name, spec in self.specs.items():
            enabled, status, consent = states.get(name, (
                spec.enabled, spec.status if spec.status == 'obsolete' else
                'active' if spec.enabled else 'disabled', False))
            result.append(dict({k: v for k, v in asdict(spec).items() if k != 'module'},
                               enabled=bool(enabled and status != 'obsolete'), status=status,
                               consent=bool(consent), lookup=lookups.get(name),
                               toggleable=(not spec.always_enabled and status != 'obsolete'
                                           and (not spec.test_only or self.allow_test))))
        return result

    def configure(self, name, *, enabled=None, consent=None):
        spec = self.specs[name]
        if enabled is not None and (spec.always_enabled or spec.status == 'obsolete'
                                    or spec.test_only and not self.allow_test):
            raise ValueError('This provider cannot be toggled')
        if consent is not None and not spec.redistributable:
            raise ValueError('This provider does not permit redistribution')
        with self.database.connect() as db:
            self._sync(db)
            if enabled is not None:
                db.execute('UPDATE metadata_providers SET enabled=?,status=? WHERE name=?',
                           (int(enabled), 'active' if enabled else 'disabled', name))
            if consent is not None:
                db.execute('UPDATE metadata_providers SET consent=? WHERE name=?',
                           (int(consent), name))
                db.execute('UPDATE track_metadata SET redistributable=? WHERE provider=?',
                           (int(consent and spec.redistributable), name))
        return next(row for row in self.list() if row['name'] == name)

    def lookup(self, name, identity, *, force=False):
        spec = self.specs[name]
        available = {'fingerprint': bool(identity.fingerprint),
                     'external_id': bool(identity.external_id), 'ISRC': bool(identity.isrc),
                     'artist+title': bool(identity.artist and identity.title)}
        if not any(available.get(key, False) for key in spec.lookup_keys):
            return False
        now, key = self.clock(), identity_hash(identity.key)
        query = {k: getattr(identity, k) for k in ('artist', 'title', 'duration', 'isrc',
                                                 'external_id')}
        query['tags'] = {k: v for k, v in (identity.tags or {}).items()
                         if k.casefold() in ('tempo', 'tbpm', 'bpm')}
        if spec.leaves_lan:
            query = {'artist': identity.artist, 'title': identity.title}
        query_json = encode(query)
        with self.database.connect() as db:
            self._sync(db)
            enabled, status, consent = db.execute(
                'SELECT enabled,status,consent FROM metadata_providers WHERE name=?',
                (name,)).fetchone()
            if not enabled or status != 'active' or spec.test_only and not self.allow_test:
                return False
            previous = db.execute('SELECT fetched_at,ttl FROM track_metadata '
                                  'WHERE identity_hash=? AND provider=?', (key, name)).fetchone()
            attempt = db.execute('SELECT retry_after,status,requested_at,query_json FROM lookups '
                                 'WHERE identity_hash=? AND provider=?', (key, name)).fetchone()
            same_query = attempt is not None and attempt[3] == query_json
            if not force and same_query:
                if previous and (previous[1] == 0 or now < sum(previous)):
                    return False
                if attempt[1] not in ('pending', 'failed') and now < attempt[2]+spec.ttl:
                    return False
            last = db.execute('SELECT MAX(requested_at) FROM lookups WHERE provider=?',
                              (name,)).fetchone()[0]
            if last is not None and now < last+spec.rate_limit:
                return False
            if spec.requires_credentials and not self.options.get(name, {}).get('credentials'):
                return False
            if attempt and now < attempt[0]:
                return False
            db.execute('INSERT INTO lookups VALUES(?,?,?,?,?,?,0) ON CONFLICT '
                       '(identity_hash,provider) DO UPDATE SET query_json=excluded.query_json,'
                       'status=excluded.status,requested_at=excluded.requested_at,'
                       'retry_after=excluded.retry_after',
                       (key, name, query_json, 'pending', now, now+spec.rate_limit))
        try:
            result = spec.make(**self.options.get(name, {})).lookup(identity)
            fields = dict(result.fields)
            if set(fields)-set(spec.capabilities):
                raise ValueError('Provider returned unsupported normalized fields')
            for field, value in fields.items():
                if field not in ('tempo', 'phase_offset_s'):
                    continue
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise ValueError('Provider values must be finite numbers')
                if field == 'tempo' and not 20 <= value <= 400:
                    raise ValueError('Tempo must be between 20 and 400 BPM')
                if field == 'phase_offset_s' and abs(value) > 2:
                    raise ValueError('Phase nudge must be within two seconds')
            if not 0 <= result.confidence <= 1:
                raise ValueError('Invalid provider confidence')
            raw = encode(result.raw_payload)
            if max(len(raw), len(encode(fields))) > 262144:
                raise ValueError('Provider payload too large')
            with self.database.connect() as db:
                self._sync(db)
                current = db.execute('SELECT enabled,status,consent FROM metadata_providers '
                                     'WHERE name=?', (name,)).fetchone()
                # A disable/retirement while lookup was running must freeze existing rows.
                if not current[0] or current[1] != 'active':
                    return False
                if fields:
                    db.execute('INSERT INTO track_metadata VALUES(?,?,?,?,?,?,?,?) '
                               'ON CONFLICT(identity_hash,provider) DO UPDATE SET '
                               'fetched_at=excluded.fetched_at,ttl=excluded.ttl,'
                               'fields_json=excluded.fields_json,'
                               'raw_payload_json=excluded.raw_payload_json,'
                               'confidence=excluded.confidence,'
                               'redistributable=excluded.redistributable',
                               (key, name, now, spec.ttl, encode(fields), raw,
                                result.confidence, int(spec.redistributable and current[2])))
                outcome = 'ready' if fields else (
                    result.status if result.status != 'ready' else 'empty')
                db.execute('UPDATE lookups SET status=?,failures=0 WHERE identity_hash=? '
                           'AND provider=?', (outcome, key, name))
            return bool(fields)
        except Exception:
            with self.database.connect() as db:
                db.execute('UPDATE lookups SET status=\'failed\',failures=failures+1,'
                           'retry_after=? WHERE identity_hash=? AND provider=?',
                           (now+(0. if spec.manual else max(60., spec.rate_limit)), key, name))
            raise

    def acquire(self, identity):
        import logging
        for name, spec in self.specs.items():
            if spec.manual:
                continue
            try:
                self.lookup(name, identity)
            except Exception:
                logging.getLogger(__name__).warning(
                    'Metadata provider %s unavailable; retaining stored rows', name, exc_info=True)

    def display_rows(self, identity):
        if not self.database.path.exists():
            return []
        with self.database.connect() as db:
            self._sync(db)
            rows = db.execute('SELECT m.provider,m.fields_json,m.fetched_at,l.status '
                              'FROM track_metadata m LEFT JOIN lookups l '
                              'ON m.identity_hash=l.identity_hash AND m.provider=l.provider '
                              'JOIN metadata_providers p ON p.name=m.provider '
                              "WHERE m.identity_hash=? AND p.enabled=1 AND p.status='active' "
                              'ORDER BY p.priority DESC', (identity_hash(identity.key),)).fetchall()
        return [dict(provider=name, label=self.specs[name].display_label,
                     fields=json.loads(fields), fetched_at=fetched_at, status=status)
                for name, fields, fetched_at, status in rows
                if name in self.specs and self.specs[name].display_label]

    def resolve(self, identity):
        if not self.database.path.exists():
            return None
        with self.database.connect() as db:
            self._sync(db)
            row = db.execute('SELECT provider,fields_json,confidence,redistributable '
                             'FROM resolved_tempo WHERE identity_hash=?',
                             (identity_hash(identity.key),)).fetchone()
        return (dict(provider=row[0], fields=json.loads(row[1]), confidence=row[2],
                     redistributable=bool(row[3])) if row else None)


def fingerprint_key(value):
    if not value:
        return None
    raw = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':'))
    return _verified_key(raw)


@lru_cache(maxsize=64)
def _verified_key(raw):
    from ..grid.fingerprint import Fingerprint, match
    fingerprint = Fingerprint.from_dict(json.loads(raw))
    if match(fingerprint, fingerprint) is None:
        return None
    canonical = json.dumps(fingerprint.to_dict(), allow_nan=False, sort_keys=True,
                           separators=(',', ':'))
    return 'fp:'+hashlib.sha256(canonical.encode()).hexdigest()
