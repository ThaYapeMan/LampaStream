"""Provider persistence/resolution; acquisition runs outside canonical analysis."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import asdict
from functools import lru_cache

from ..grid.database import GridDatabase, encode, identity_hash
from .registry import PROVIDERS

_FILE_IDENTITY = 'local-file-identity'
_EXTERNAL_CACHE_STATES = {'ready', 'not_found', 'ambiguous', 'octave_ambiguous'}
_FAILURE_COOLDOWN_S = 60.
_PENDING_LEASE_S = 30.
# A reserved key outside the hashed track-identity namespace.
_PROVIDER_REQUEST = 'provider-request'
_PAUSE_STATES = {'blocked', 'rate_limited', 'authentication_failed'}
_PAUSE_S = 24 * 3600
_PAUSE_LOG_S = 3600
log = logging.getLogger(__name__)


def _credential_digest(credentials):
    return hashlib.sha256(credentials.encode()).hexdigest() if credentials else None


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
                   "SELECT DISTINCT provider,'obsolete',0,0,0 FROM track_metadata "
                   "WHERE provider<>?", (_FILE_IDENTITY,))
        known = tuple(self.specs)
        if known:
            slots = ','.join('?' for _ in known)
            db.execute(f'UPDATE metadata_providers SET status=\'obsolete\',enabled=0 '
                       f'WHERE name NOT IN ({slots})', known)

    def list(self):
        states = {}
        lookups = {}
        requests = {}
        now = self.clock()
        if self.database.path.exists():
            with self.database.connect() as db:
                self._sync(db)
                states = {row[0]: row[1:] for row in db.execute(
                    'SELECT name,enabled,status,consent FROM metadata_providers')}
                lookups = {row[0]: dict(status=row[1], requested_at=row[2])
                           for row in db.execute('SELECT provider,status,requested_at FROM lookups '
                                                 'WHERE identity_hash<>? ORDER BY requested_at',
                                                 (_PROVIDER_REQUEST,))}
                requests = {name: (requested, outcome, json.loads(state))
                            for name, requested, outcome, state in db.execute(
                    'SELECT provider,requested_at,status,query_json FROM lookups '
                    'WHERE identity_hash=?', (_PROVIDER_REQUEST,))}
        result = []
        for name, spec in self.specs.items():
            enabled, status, consent = states.get(name, (
                spec.enabled, spec.status if spec.status == 'obsolete' else
                'active' if spec.enabled else 'disabled', False))
            lookup = lookups.get(name)
            credentials = (spec.credentials(self.options.get(name, {}))
                           if spec.requires_credentials else '')
            http_status = paused_until = None
            if name in requests:
                requested, outcome, state = requests[name]
                until, code = state['paused_until'], state['http_status']
                if state['credential_digest'] == _credential_digest(credentials):
                    if lookup and lookup['requested_at'] == requested:
                        http_status = code
                    if enabled and until is not None and now < until:
                        paused_until, http_status = until, code
                        lookup = dict(status=outcome, requested_at=requested)
            if spec.requires_credentials and not credentials:
                lookup = dict(status='credentials_not_configured', requested_at=None)
            result.append(dict({k: v for k, v in asdict(spec).items()
                                if k not in ('module', 'credential_env')},
                               enabled=bool(enabled and status != 'obsolete'), status=status,
                               consent=bool(consent), lookup=lookup,
                               paused_until=paused_until, http_status=http_status,
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
                was_enabled, = db.execute('SELECT enabled FROM metadata_providers WHERE name=?',
                                          (name,)).fetchone()
                if spec.leaves_lan and enabled != was_enabled:
                    db.execute("UPDATE lookups SET query_json=json_set(query_json, "
                               "'$.paused_until',NULL) WHERE identity_hash=? AND provider=?",
                               (_PROVIDER_REQUEST, name))
                    db.execute("DELETE FROM lookups WHERE provider=? AND status='pending'",
                               (name,))
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
        options = self.options.get(name, {})
        credentials = spec.credentials(options) if spec.requires_credentials else ''
        digest = _credential_digest(credentials)
        if spec.requires_credentials:
            if not credentials:
                return False
            options = {**options, 'credentials': credentials}
        available = {'fingerprint': bool(identity.fingerprint),
                     'external_id': bool(identity.external_id), 'ISRC': bool(identity.isrc),
                     'artist+title': bool(identity.title and (identity.artist or spec.leaves_lan))}
        if not any(available.get(key, False) for key in spec.lookup_keys):
            return False
        now, key = self.clock(), identity_hash(identity.key)
        query = {k: getattr(identity, k) for k in ('artist', 'title', 'duration', 'isrc',
                                                 'external_id')}
        query['tags'] = {k: v for k, v in (identity.tags or {}).items()
                         if k.casefold() in ('tempo', 'tbpm', 'bpm')}
        if spec.leaves_lan:
            query = {'artist': identity.artist, 'title': identity.title,
                     'album_artist': identity.album_artist,
                     'isrc': identity.isrc, 'duration': identity.duration,
                     'adapter_version': spec.adapter_version}
        query_json = encode(query)
        with self.database.connect() as db:
            self._sync(db)
            enabled, status, consent = db.execute(
                'SELECT enabled,status,consent FROM metadata_providers WHERE name=?',
                (name,)).fetchone()
            if not enabled or status != 'active' or spec.test_only and not self.allow_test:
                return False
            request = self._request_state(db, name) if spec.leaves_lan else None
            retry_paused = bool(request and request[2]['paused_until'] is not None)
            if retry_paused:
                _, outcome, state = request
                until = state['paused_until']
                if state['credential_digest'] == digest and now < until:
                    last_log = state['last_pause_log']
                    if last_log is None or now >= last_log + _PAUSE_LOG_S:
                        db.execute("UPDATE lookups SET query_json=json_set(query_json, "
                                   "'$.last_pause_log',?) WHERE identity_hash=? AND provider=?",
                                   (now, _PROVIDER_REQUEST, name))
                        log.info('provider=%s http=%s status=%s paused_until=%.0f',
                                 name, state['http_status'], outcome, until)
                    return False
                if db.execute("SELECT 1 FROM lookups WHERE provider=? AND status='pending' "
                              "AND retry_after>? LIMIT 1", (name, now)).fetchone():
                    return False
            previous = db.execute('SELECT fetched_at,ttl FROM track_metadata '
                                  'WHERE identity_hash=? AND provider=?', (key, name)).fetchone()
            attempt = db.execute('SELECT retry_after,status,requested_at,query_json FROM lookups '
                                 'WHERE identity_hash=? AND provider=?', (key, name)).fetchone()
            same_query = attempt is not None and attempt[3] == query_json
            old_query = json.loads(attempt[3]) if spec.leaves_lan and attempt else {}
            outdated = (spec.leaves_lan and attempt and attempt[1] != 'ready'
                        and old_query.get('adapter_version', 1) < spec.adapter_version)
            if spec.leaves_lan and previous and not (force or retry_paused) and now < sum(previous):
                # Keep fresh accepted rows across adapter upgrades. Newly available
                # ISRC or album artist can improve the match for the same recording.
                improved = any(query[field] and old_query.get(field) != query[field]
                               for field in ('isrc', 'album_artist'))
                if not improved:
                    return False
            if not (force or retry_paused) and same_query:
                if previous and (previous[1] == 0 or now < sum(previous)):
                    return False
                cacheable = (attempt[1] in _EXTERNAL_CACHE_STATES if spec.leaves_lan
                             else attempt[1] not in ('pending', 'failed'))
                if cacheable and now < attempt[2] + spec.ttl:
                    return False
            last = db.execute('SELECT MAX(requested_at) FROM lookups WHERE provider=? '
                              'AND identity_hash<>?',
                              (name, _PROVIDER_REQUEST)).fetchone()[0]
            if last is not None and now < last+spec.rate_limit:
                return False
            if attempt and attempt[1] == 'pending' and now < attempt[0]:
                return False
            if attempt and not (outdated or retry_paused) and now < attempt[0]:
                return False
            db.execute('INSERT INTO lookups VALUES(?,?,?,?,?,?,0) ON CONFLICT '
                       '(identity_hash,provider) DO UPDATE SET query_json=excluded.query_json,'
                       'status=excluded.status,requested_at=excluded.requested_at,'
                       'retry_after=excluded.retry_after',
                       (key, name, query_json, 'pending', now,
                        now + (_PENDING_LEASE_S if spec.leaves_lan else spec.rate_limit)))
        try:
            result = spec.make(**options).lookup(identity)
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
                claim = db.execute('SELECT requested_at FROM lookups WHERE identity_hash=? '
                                   'AND provider=?', (key, name)).fetchone()
                if claim != (now,) or (spec.requires_credentials
                                        and spec.credentials(self.options.get(name, {}))
                                        != credentials):
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
                retry_after = now + spec.rate_limit
                if spec.leaves_lan:
                    if outcome in _PAUSE_STATES:
                        finished = self.clock()
                        self._record_request(db, name, now, outcome, result.http_status,
                                             digest, paused_until=finished + _PAUSE_S,
                                             last_pause_log=finished)
                    else:
                        self._record_request(db, name, now, outcome, result.http_status, digest)
                        if outcome not in _EXTERNAL_CACHE_STATES | {'timeout'}:
                            retry_after = self.clock() + max(_FAILURE_COOLDOWN_S, spec.rate_limit)
                db.execute('UPDATE lookups SET status=?,failures=0,retry_after=? '
                           'WHERE identity_hash=? AND provider=?',
                           (outcome, retry_after, key, name))
            return bool(fields)
        except Exception:
            with self.database.connect() as db:
                db.execute('UPDATE lookups SET status=\'failed\',failures=failures+1,'
                           'retry_after=? WHERE identity_hash=? AND provider=? AND requested_at=?',
                           (self.clock() + (0. if spec.manual else
                                            max(_FAILURE_COOLDOWN_S, spec.rate_limit)),
                            key, name, now))
            raise

    def _request_state(self, db, name):
        row = db.execute('SELECT requested_at,status,query_json FROM lookups '
                         'WHERE identity_hash=? AND provider=?',
                         (_PROVIDER_REQUEST, name)).fetchone()
        return (row[0], row[1], json.loads(row[2])) if row else None

    def _record_request(self, db, name, now, outcome, http_status, digest,
                        *, paused_until=None, last_pause_log=None):
        previous = self._request_state(db, name)
        if previous and previous[2]['credential_digest'] == digest:
            until = previous[2]['paused_until']
            if until is not None and self.clock() < until:
                return
            if paused_until is None and now < previous[0]:
                return
        state = encode(dict(http_status=http_status, credential_digest=digest,
                            paused_until=paused_until, last_pause_log=last_pause_log))
        db.execute('INSERT INTO lookups VALUES(?,?,?,?,?,?,0) ON CONFLICT '
                   '(identity_hash,provider) DO UPDATE SET query_json=excluded.query_json,'
                   'status=excluded.status,requested_at=excluded.requested_at',
                   (_PROVIDER_REQUEST, name, state, outcome, now, 0.))

    def save_file_identity(self, identity, *, album_artist, isrc):
        if not (album_artist or isrc):
            return
        raw = encode(dict(album_artist=album_artist, isrc=isrc))
        with self.database.connect() as db:
            db.execute("INSERT INTO track_metadata VALUES(?,?,?,0,'{}',?,1,0) "
                       "ON CONFLICT(identity_hash,provider) DO UPDATE SET "
                       "fetched_at=excluded.fetched_at,raw_payload_json=excluded.raw_payload_json",
                       (identity_hash(identity), _FILE_IDENTITY, self.clock(), raw))

    def file_identity(self, identity):
        with self.database.connect() as db:
            row = db.execute('SELECT raw_payload_json FROM track_metadata '
                             'WHERE identity_hash=? AND provider=?',
                             (identity_hash(identity), _FILE_IDENTITY)).fetchone()
        return json.loads(row[0]) if row else {}

    def acquire(self, identity):
        for name, spec in self.specs.items():
            if spec.manual:
                continue
            try:
                self.lookup(name, identity)
            except Exception:
                log.warning(
                    'Metadata provider %s unavailable; retaining stored rows', name)

    def display_rows(self, identity):
        if not self.database.path.exists():
            return []
        with self.database.connect() as db:
            self._sync(db)
            rows = db.execute('SELECT m.provider,m.fields_json,m.fetched_at,m.ttl,l.status '
                              'FROM track_metadata m LEFT JOIN lookups l '
                              'ON m.identity_hash=l.identity_hash AND m.provider=l.provider '
                              'JOIN metadata_providers p ON p.name=m.provider '
                              "WHERE m.identity_hash=? AND p.enabled=1 AND p.status='active' "
                              'ORDER BY p.priority DESC', (identity_hash(identity.key),)).fetchall()
        now = self.clock()
        return [dict(provider=name, label=self.specs[name].display_label,
                     fields=json.loads(fields), fetched_at=fetched_at, status=status,
                     age_s=max(0., now - fetched_at), stale=bool(ttl and now >= fetched_at + ttl))
                for name, fields, fetched_at, ttl, status in rows
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
