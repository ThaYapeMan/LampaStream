"""Provider settings and explicit operator writes; never mutate the audio pipeline."""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .context import current_identity, owner_fields, refresh, snapshot
from .store import ProviderStore

router = APIRouter()


class ProviderBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool | None = None
    consent: bool | None = None


class CorrectionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identity: str = Field(min_length=4, max_length=100)
    action: Literal['half', 'double', 'tap', 'nudge']
    tempo: float | None = Field(default=None, ge=20, le=400, allow_inf_nan=False)
    nudge_ms: float = Field(default=0., ge=-1000, le=1000, allow_inf_nan=False)


def get_store(request):
    candidate = getattr(request.app.state, 'tempo_provider_store', None)
    return candidate if isinstance(candidate, ProviderStore) else ProviderStore()


@router.get('/tempo-metadata')
async def tempo_metadata(request: Request):
    from ..api import _manager
    try:
        return await asyncio.to_thread(refresh, _manager(request), get_store(request))
    except (OSError, ValueError, sqlite3.Error):
        raise HTTPException(503, 'Grid database unavailable; run the standard installer') from None


@router.patch('/metadata-providers/{name}')
async def configure_provider(name: str, request: Request, body: ProviderBody):
    try:
        return await asyncio.to_thread(get_store(request).configure, name,
                                       **body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(404, 'Unknown metadata provider') from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, 'Grid database unavailable; run the standard installer') from None


@router.post('/tempo/correction')
async def correct_tempo(request: Request, body: CorrectionBody):
    from ..api import _manager
    manager = _manager(request)
    identity, _ = await asyncio.to_thread(current_identity, manager)
    if identity is None or not identity.key.startswith('fp:'):
        raise HTTPException(409, 'Wait for an audio-fingerprint identity '
                            'before saving a correction')
    if identity.key != body.identity:
        raise HTTPException(409, 'Track changed; choose the correction again')
    store = get_store(request)
    def save():
        current, _ = current_identity(manager)
        if current is None or current.key != identity.key:
            raise ValueError('Track changed; choose the correction again')
        state = snapshot(manager, store)
        previous = owner_fields(store, identity)
        tempo = state['tempo']
        if body.action == 'tap':
            tempo = body.tempo
        elif body.action in ('half', 'double') and tempo:
            tempo *= .5 if body.action == 'half' else 2.
        if tempo is None:
            raise ValueError('Wait for a tempo or tap one')
        phase = previous.get('phase_offset_s', 0.)
        if body.action == 'nudge':
            phase += body.nudge_ms/1000
        fields = dict(tempo=tempo, phase_offset_s=phase)
        store.lookup('owner', replace(identity, correction=fields), force=True)
        return snapshot(manager, store)
    try:
        return await asyncio.to_thread(save)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, 'Grid database unavailable; run the standard installer') from None
