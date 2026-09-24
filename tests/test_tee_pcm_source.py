"""Phase 0 fanout isolation and canonical worker regressions, without hardware."""

import asyncio
import dataclasses
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from lampastream.canonicalizer import (
    DataResult,
    DecodedSourceFrame,
    EndOfStream,
    InvalidationCause,
    StreamInvalidated,
    TemporarilyNoData,
)
from lampastream.models import Profile
from lampastream.pcm_source import TeePcmSource
from lampastream.player_manager import ActiveSession, PlayerManager, _make_canonical_pipeline
from lampastream.storage import Storage


class Source:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0
        self.running = False
        self.closed = 0

    def open(self, *args, **kwargs):
        self.open_args = (args, kwargs)
        self.running = True

    def close(self):
        self.closed += 1
        self.running = False

    def read(self):
        self.calls += 1
        return next(self.results)


def events():
    rng = np.random.default_rng(7)
    for rate in (44100, 48000):
        for pos in range(0, 12000, 1000):
            yield DataResult(DecodedSourceFrame(
                samples=rng.uniform(-.5, .5, (1000, 2)).astype(np.float32),
                sample_rate=rate, channels=2, source_id='test',
                source_sample_pos=pos, over_range=False, wall_ns=None,
            ))
            yield TemporarilyNoData()
        if rate == 44100:
            yield StreamInvalidated(InvalidationCause.RATE_CHANGE)
    yield EndOfStream()


def test_delegation_and_secondary_lifecycle():
    results = list(events())
    source = Source(results)
    tee = TeePcmSource(source)
    assert not tee.running
    tee.open('mac', _path='test')
    assert source.open_args == (('mac',), {'_path': 'test'})
    assert tee.running
    assert tee.read() is results[0]
    assert tee.drain_secondary(10) == []
    tee.attach_secondary()
    tee.attach_secondary()  # idempotent, preserves pending items
    primary = [tee.read() for _ in results[1:]]
    secondary = tee.drain_secondary(3) + tee.drain_secondary(100)
    assert len(primary) == len(secondary)
    assert all(a is b for a, b in zip(primary, secondary, strict=True))
    assert source.calls == len(results)
    assert not results[0].frame.samples.flags.writeable
    tee.close()
    assert source.closed == 1
    assert not tee.running

    source = Source(results)
    tee = TeePcmSource(source)
    tee.attach_secondary()
    tee.read()
    tee.detach_secondary()
    tee.read()
    tee.attach_secondary()
    assert tee.drain_secondary(10) == []
    assert tee.read() is results[2]
    assert tee.drain_secondary(0) == []
    assert tee.drain_secondary(10)[0] is results[2]
    with pytest.raises(ValueError):
        tee.drain_secondary(-1)
    with pytest.raises(ValueError):
        TeePcmSource(source, capacity=0)


def test_undrained_secondary_is_bounded_and_primary_completes():
    # A full blocking queue would hang this worker. A generous deadline catches
    # per-read waiting without pretending to prove target realtime performance.
    results = [TemporarilyNoData() for _ in range(100000)]
    source = Source(results)
    tee = TeePcmSource(source, capacity=7)
    tee.attach_secondary()
    observed = []
    errors = []

    def consume():
        try:
            observed.extend(tee.read() for _ in results)
        except Exception as exc:
            errors.append(exc)

    start = time.monotonic()
    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    worker.join(3)
    assert not worker.is_alive(), 'secondary backpressure blocked primary reads'
    assert time.monotonic() - start < 3
    assert errors == []
    assert source.calls == len(results)
    assert all(a is b for a, b in zip(observed, results, strict=True))
    pending = tee.drain_secondary(len(results))
    assert len(pending) == 7
    assert all(a is b for a, b in zip(pending, results[-7:], strict=True))


def test_canonical_worker_input_and_output_byte_parity(monkeypatch):
    results = list(events())
    # Epoch IDs are intentionally random; use identical IDs for byte comparison.
    monkeypatch.setattr('lampastream.canonicalizer.uuid.uuid4', lambda: 'epoch')

    def run(wrapped):
        source = Source(results)
        tee = TeePcmSource(source)
        cap = _make_canonical_pipeline(tee if wrapped else source, Profile(spectrum_backend='v2'))
        seen = []
        original_push = cap._canonicalizer.push

        def observe(result):
            seen.append(result)
            if len(seen) == len(results):
                cap._stop.set()
            return original_push(result)

        cap._canonicalizer.push = observe
        cap._run()  # Actual worker loop; deterministic stop after final EOS.
        assert source.calls == len(results)
        assert all(a is b for a, b in zip(seen, results, strict=True))
        assert tee.drain_secondary(100) == []
        records = cap.drain_publications()
        assert records
        return json.dumps([dataclasses.asdict(r) for r in records], sort_keys=True).encode()

    assert run(False) == run(True)


@pytest.mark.parametrize('ingress', ['lms', 'airplay'])
def test_manager_activation_swap_and_teardown_reuse_tee(tmp_path, monkeypatch, ingress):
    import lampastream.player_manager as pm

    source = Source([TemporarilyNoData()])
    source_factory = MagicMock(return_value=source)
    monkeypatch.setattr(pm, 'SqueezeliteShmStereoSource', source_factory)
    monkeypatch.setattr(pm, 'AirPlayPipeStereoSource', source_factory)
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(pm, '_make_canonical_pipeline', factory)
    engine = MagicMock(retirement_pending=False)
    engine.run = AsyncMock()
    monkeypatch.setattr(pm, 'SyncEngine', MagicMock(return_value=engine))
    driver = MagicMock(start=AsyncMock(), stop=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(pm, 'HueDriver', MagicMock(return_value=driver))
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    monkeypatch.setattr(manager, '_wait_for_shm', MagicMock())
    monkeypatch.setattr(manager, '_poll_sync_master', AsyncMock())
    monkeypatch.setattr(manager, '_configure_shairport_name', lambda _: False)
    manager._airplay_tracks = MagicMock()
    profile = Profile(player_mac='', spectrum_backend='v2')
    session = ActiveSession(profile)
    manager._active = session

    async def exercise():
        activate = manager._activate_lms_pcm if ingress == 'lms' else manager._activate_airplay
        await activate(session, profile, None, MagicMock(), [])
        tee = session.shm_source
        assert isinstance(tee, TeePcmSource)
        assert tee.running
        factory.assert_called_once_with(tee, profile)
        assert source.open_args == ((('',) if ingress == 'lms' else ()), {})
        tee.attach_secondary()
        result = tee.read()
        new_profile = dataclasses.replace(profile, bars=20)
        manager.replace_pcm_analyser(new_profile)
        factory.assert_called_with(tee, new_profile)
        # The rollback closure also uses the same tee, without closing/reopening.
        engine.replace_analyser.call_args.kwargs['rebuild_old']()
        factory.assert_called_with(tee, profile)
        assert session.shm_source is tee
        assert tee.drain_secondary(1)[0] is result
        assert source.closed == 0
        await manager._teardown_session(session)
        assert source.closed == 1
        assert not tee.running
        assert session.shm_source is None

    asyncio.run(exercise())
