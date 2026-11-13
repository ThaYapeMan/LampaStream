"""Read-only metadata context bridge, outside canonical analysis and rendering."""
from __future__ import annotations

import hashlib
import json

from ..grid import TrackGrid
from ..grid.database import encode
from .registry import Identity
from .store import ProviderStore, fingerprint_key


def current_identity(manager):
    track = manager.track_position
    session = getattr(manager, '_active', None)
    engine = getattr(session, 'sync_engine', None)
    analyser = getattr(engine, '_analyser', None)
    fusion = getattr(analyser, '_beat_fusion', None)
    prior = getattr(fusion, 'prior', None)
    source_identity = getattr(getattr(session, 'track_source', None), 'grid_adapter', None)
    grid = (getattr(source_identity, 'grid', None) if source_identity is not None else
            getattr(prior, 'available', None) or getattr(prior, 'grid', None))
    grid = grid if isinstance(grid, TrackGrid) else None
    fingerprint = grid.audio_fingerprint if grid and not grid.provisional else None
    key = fingerprint_key(fingerprint)
    if key is None:
        if (track is None or not track.artist or not track.title or not track.duration_s):
            return None, None
        # An early lookup hint is explicitly unconfirmed and cannot store an
        # owner correction or attach a learned grid. It never enters identities.
        hint = (track.artist.strip().casefold(), track.title.strip().casefold(), track.duration_s)
        key = 'hint:'+hashlib.sha256(encode(hint).encode()).hexdigest()
    tags = {'tempo': track.tempo_bpm} if track and track.tempo_bpm is not None else {}
    return Identity(key, artist=track.artist or '' if track else '',
                    title=track.title or '' if track else '',
                    duration=grid.duration if grid else track.duration_s,
                    fingerprint=fingerprint, tags=tags), grid


def snapshot(manager, store=None):
    store = store or ProviderStore()
    identity, grid = current_identity(manager)
    if identity is None:
        return dict(identity=None, confirmed=False, resolved_tempo=None,
                    tempo=None, phase_offset_s=0., reason='Waiting for track identity')
    resolved = store.resolve(identity)
    fields = resolved['fields'] if resolved else {}
    return dict(identity=identity.key, confirmed=identity.key.startswith('fp:'),
                resolved_tempo=resolved, tempo=fields.get('tempo', grid.tempo if grid else None),
                phase_offset_s=fields.get('phase_offset_s', 0.),
                reason=None if identity.key.startswith('fp:') else 'Waiting for audio fingerprint')


def refresh(manager, store=None):
    store = store or ProviderStore()
    identity, _ = current_identity(manager)
    if identity is not None and store.database.path.exists():
        store.acquire(identity)
    return snapshot(manager, store)


def owner_fields(store, identity):
    from ..grid.database import identity_hash
    with store.database.connect() as db:
        row = db.execute('SELECT fields_json FROM track_metadata '
                         'WHERE identity_hash=? AND provider=?',
                         (identity_hash(identity.key), 'owner')).fetchone()
    return json.loads(row[0]) if row else {}
