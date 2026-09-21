"""Real HPSS through both canonical spectrum engines, including live rendering."""

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest
from test_cavacore_pipeline import _SO_PATH, _make_canonical_frame

from lampastream.models import Profile
from lampastream.pcm_source import PcmHpss
from lampastream.player_manager import _make_canonical_pipeline
from lampastream.sync_engine import SyncEngine

BACKENDS = ["v2", pytest.param("cavacore", marks=pytest.mark.skipif(
    not _SO_PATH.exists(), reason="cavacore native library not built"))]


def pipeline(backend, enabled=True):
    return _make_canonical_pipeline(MagicMock(), Profile(
        bars_source="pcm_pipeline", spectrum_backend=backend,
        use_hpss_separation=enabled))


def feed(cap, mono, chunk=480, start=0, epoch="ep-1"):
    stereo = np.column_stack((mono, mono)).astype(np.float32)
    records = []
    for pos in range(0, len(mono), chunk):
        records.extend(cap.feed(_make_canonical_frame(
            stereo[pos:pos + chunk], sample_pos=start + pos, epoch_id=epoch)))
    return records


def contributions(records):
    return sorted((r.sample_pos, r.sample_end, r.features.percussive_energy,
                   r.features.harmonic_energy) for r in records
                  if "hpss_analyzer" in r.effective_processor_ids)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("chunk", [137, 480, 4096])
def test_hpss_differentiates_tone_and_transient_on_both_backends(backend, chunk):
    tone = (.5 * np.sin(2 * np.pi * 440 * np.arange(24000) / 48000)).astype(np.float32)
    transient = np.zeros(24000, np.float32)
    transient[12000] = 1
    measured = []
    for signal in (tone, transient):
        cap = pipeline(backend)
        try:
            records = feed(cap, signal, chunk)
            values = contributions(records)
            # Same unchanged algorithm as the legacy tap, with exact hop positions.
            expected = PcmHpss(48000).push(signal)
            assert [v[:2] for v in values] == [(i * 480, (i + 1) * 480)
                                               for i in range(len(expected))]
            np.testing.assert_allclose([v[2:] for v in values], expected, atol=1e-7)
            assert all(r.features.hpss_active for r in records
                       if "hpss_analyzer" in r.effective_processor_ids)
            measured.append(values)
        finally:
            cap.stop()
    harmonic = np.mean([v[3] for v in measured[0][25:]])
    percussive_frame = max(measured[1], key=lambda v: v[2])
    assert harmonic > .8
    assert percussive_frame[2] > .8
    assert percussive_frame[3] < .2
    print(f"HPSS {backend} chunk={chunk}: tone harmonic={harmonic:.6f}, "
          f"transient percussive={percussive_frame[2]:.6f}, "
          f"transient harmonic={percussive_frame[3]:.6f}")


@pytest.mark.parametrize("backend", BACKENDS)
def test_hpss_disable_enable_epoch_and_eos(backend):
    cap = pipeline(backend, enabled=False)
    tone = (.5 * np.sin(2 * np.pi * 440 * np.arange(24000) / 48000)).astype(np.float32)
    try:
        assert not contributions(feed(cap, tone))
        assert cap.latest_hpss() == (False, 0, 0)
        cap.set_hpss_enabled(True)
        assert not contributions(feed(cap, tone[:137], start=24000))
        assert not cap.latest_hpss()[0]
        active = feed(cap, tone[137:], start=24137)
        assert contributions(active)[0][0] == 24000
        terminal = cap.latest_hpss()
        assert terminal[0] and terminal[2] > .8
        cap.end_of_stream()
        assert cap.latest_hpss() == terminal
        feed(cap, tone[:137], start=0, epoch="new")
        assert cap.latest_hpss() == (False, 0, 0)
        cap.set_hpss_enabled(False)
        records = feed(cap, tone[137:], start=137, epoch="new")
        assert not contributions(records)
        assert all(not r.features.hpss_active for r in records)
        assert cap.latest_hpss() == (False, 0, 0)
    finally:
        cap.stop()


@pytest.mark.parametrize("backend", BACKENDS)
def test_hpss_live_effects_and_profile_toggle(backend, monkeypatch):
    cap = pipeline(backend)
    tone = (.5 * np.sin(2 * np.pi * 440 * np.arange(24000) / 48000)).astype(np.float32)
    feed(cap, tone)
    record = cap._latest_pub
    original_active = record.features.hpss_active
    engine = SyncEngine(None, Profile(use_hpss_separation=True), analyser=cap)
    render = MagicMock(wraps=engine._effect.render)
    engine._effect.render = render

    async def stop_after_tick(_):
        raise asyncio.CancelledError

    monkeypatch.setattr("lampastream.sync_engine.asyncio.sleep", stop_after_tick)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.run(MagicMock()))
        features = render.call_args.args[0]
        assert features.hpss_active and features.harmonic_energy > .8
        assert record.features.hpss_active == original_active
        engine.update_onset_pipeline(Profile(use_hpss_separation=False))
        assert cap.latest_hpss() == (False, 0, 0)
    finally:
        engine.stop()
