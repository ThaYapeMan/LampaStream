"""File/grid contracts and real loopback acquisition; no live LMS traffic."""
import asyncio
import hashlib
import io
import os
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fake_lms_library import Session

from lampastream.grid import VERSION, Section, TrackGrid
from lampastream.grid.analyser import analyse, sections_for
from lampastream.grid.cache import GridCache
from lampastream.grid.prior import GridPrior
from lampastream.lms_grid import LmsGridAdapter, fetch_file, identity
from lampastream.track_position import LmsTrackPositionSource


def clicks(gap=False, period=.5):
    sr = 16000
    y = np.zeros(sr*16)
    tone = np.sin(np.arange(1600)*2*np.pi*80/sr)*np.exp(-np.arange(1600)/250)
    for t in np.arange(.5, 15.6, period):
        if gap and 7 <= t < 9:
            continue
        start = round(t*sr)
        y[start:start+len(tone)] += tone
    out = io.BytesIO()
    sf.write(out, y, sr, format='FLAC')
    return out.getvalue()


def grid():
    return TrackGrid(VERSION, 'a'*64, 20, 48000, 120, tuple(np.arange(.5, 20, .5)),
                     (True,)*39, (), .95, 'content-v1')


@pytest.mark.parametrize('gap', [False, True])
def test_file_clicks(gap):
    raw = clicks(gap)
    result = analyse(raw)
    assert result.file_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.timing_basis == 'content-v1'
    assert abs(result.tempo-120) < 2
    if gap:
        assert any(s.kind == 'break' and 6.9 < s.start < 7.2 and 8.8 < s.end < 9.2
                   for s in result.sections)
    assert TrackGrid.from_dict(result.to_dict()) == result


def test_sections_and_cache_lru(tmp_path):
    assert sections_for([0., .5, 1., 1.5], [True, False, False, True], 2.) == (
        Section('break', .5, 1.5), Section('drop', 1.5, 1.5))
    cache = GridCache(tmp_path, limit=2)
    for key in ('a', 'b'):
        cache.put(identity(key, 42), replace(grid(), file_sha256=key*64))
    assert cache.get(identity('a', 42))
    cache.put(identity('c', 42), replace(grid(), file_sha256='c'*64))
    assert cache.get(identity('b', 42)) is None
    assert cache.get(identity('a', 42)).file_sha256 == 'a'*64
    assert cache.get(identity('a', 43)) is None
    with cache.database.connect() as database:
        assert database.execute('SELECT count(*) FROM identities').fetchone()[0] == 2
    assert not list(tmp_path.glob('*.json'))


def test_contradiction_and_handover():
    prior = GridPrior()
    prior.set(('one', grid(), 0), .1)
    assert prior.ticks(.5, True) == [(.5, .8, 0)]
    assert prior.ticks(.5, True) == []
    prior.ticks(8.2, True)
    assert prior.grid is None and prior.blocked == 'one'
    prior.set(('one', grid(), 0), 9)
    assert prior.grid is None
    prior.set(('two', grid(), 0), 9.1)
    assert prior.ticks(9.5, True) == [(9.5, .8, 18)]
    prior.onsets.extend(np.arange(9.5, 18, .5))
    prior.ticks(17.5, True)
    assert prior.grid is not None


def test_silent_audio_does_not_contradict_and_breaks_emit_nothing():
    prior = GridPrior()
    g = replace(grid(), kick_flags=(False,)*39)
    prior.set(('one', g, 0), .1)
    assert prior.ticks(9., False) == []
    assert prior.grid is not None


@pytest.mark.serial
def test_fetch_success_mismatch_http_failure_and_timeout(tmp_path):
    path = tmp_path/'source'
    path.write_bytes(clicks())

    async def run():
        async with Session(path) as session:
            base = f'http://127.0.0.1:{session.web_port}'
            dest = tmp_path/'download'
            await fetch_file(base, '44436', path.stat().st_size, dest)
            assert dest.read_bytes() == path.read_bytes()
            with pytest.raises(ValueError):
                await fetch_file(base, '44436', path.stat().st_size+1, dest)
            with pytest.raises(ValueError):
                await fetch_file(base, '44436', path.stat().st_size-1, dest)
            with pytest.raises(Exception, match='404'):
                await fetch_file(base, 'unknown', path.stat().st_size, dest)
            with pytest.raises(TimeoutError):
                await fetch_file(base, '44436', path.stat().st_size, dest, timeout=.000001)
    asyncio.run(run())


@pytest.mark.serial
def test_fake_lms_current_next_and_restart_cache_hit(tmp_path):
    path = tmp_path/'source.flac'
    path.write_bytes(clicks())
    asyncio.run(integration(path, tmp_path/'cache'))


async def integration(path, cache_path):
    async with Session(path) as session:
        lifetimes = []
        for restart in range(2):
            started = time.monotonic()
            adapter = LmsGridAdapter('127.0.0.1', session.web_port, GridCache(cache_path))
            source = LmsTrackPositionSource('127.0.0.1', lambda: 'aa', session.cli_port,
                                            grid_adapter=adapter)
            source.open()
            try:
                async with asyncio.timeout(120):
                    while adapter.state != 'ready':
                        assert adapter.state != 'failed'
                        await asyncio.sleep(.02)
                from lampastream.canonicalizer import AnalysisPcmFrame
                from lampastream.models import Profile
                from lampastream.player_manager import _make_canonical_pipeline

                pipeline = _make_canonical_pipeline(object(), Profile(beat_accent_mode='tracker'))
                pipeline._beat_fusion.grid_provider = lambda frame, adapter=adapter: adapter.prior(
                    frame.content_position_s, frame.sample_pos)
                try:
                    records = pipeline.feed(AnalysisPcmFrame(
                        np.zeros((4096, 2), np.float32), 0, 'fixture', 'file', False,
                        content_position_s=0.))
                    assert records and all(r.features.beat_source == 'grid' for r in records)
                finally:
                    pipeline.stop()
                assert adapter.cache_state == ('hit' if restart else 'miss')
                assert len(session.requests) == (2 if path.stat().st_size > 16*1024**2 else 1)
                print(f'restart={restart} cache={adapter.cache_state} '
                      f'fetches={len(session.requests)} '
                      f'beat_source=grid tempo={adapter.grid.tempo:.3f}')
            finally:
                await source.close()
                lifetimes.append(time.monotonic()-started)
        assert len([c for c in session.commands if 'subscribe' in c]) == 2
        lookups = len([c for c in session.commands if 'subscribe' not in c])
        assert 2 <= lookups <= 2+sum(int(elapsed//30) for elapsed in lifetimes)
        assert all('tags:adglcKuf' in c or 'tags:uf' in c for c in session.commands)


@pytest.mark.serial
@pytest.mark.skipif(not os.environ.get('LAMPASTREAM_GRID_FIXTURE'), reason='private Mau P fixture')
def test_fake_lms_mau_p(tmp_path):
    asyncio.run(integration(Path(os.environ['LAMPASTREAM_GRID_FIXTURE']), tmp_path/'cache'))


def test_airplay_without_prior_is_identical():
    from lampastream.beat_fusion import BeatFusion
    from lampastream.spectrum_engine import SharedAnalysisFrame
    from lampastream.sync_engine import StereoMagStft

    plain, optional = BeatFusion(), BeatFusion()
    optional.grid_provider = lambda frame: None
    stft = StereoMagStft(48000)
    rng = np.random.default_rng(44)
    pcm = rng.normal(0, .05, (48000, 2)).astype(np.float32)
    count = 0
    for start in range(0, len(pcm), 480):
        samples = pcm[start:start+480]
        mags = stft.push(samples)
        frame = SharedAnalysisFrame(samples, mags, 'airplay', start, start+len(samples),
                                    [480*(count+i) for i in range(len(mags))])
        count += len(mags)
        assert plain.feed(frame) == optional.feed(frame)
        assert plain.clock.tempo_bpm == optional.clock.tempo_bpm


def test_prior_is_ignored_in_onset_and_off_modes():
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline

    for mode in ('onset', 'off'):
        pipeline = _make_canonical_pipeline(object(), Profile(beat_accent_mode=mode))
        assert pipeline._beat_fusion.accent_mode == mode
        from lampastream.canonicalizer import AnalysisPcmFrame
        pipeline._beat_fusion.grid_provider = lambda frame: ('track', grid(), 0.)
        records = pipeline.feed(AnalysisPcmFrame(np.zeros((4096, 2), np.float32),
                                                0, "test", "test", False))
        assert records and all(r.features.beat_source != "grid" for r in records)
        assert all(r.features.grid_tempo == 120 for r in records)
        pipeline.stop()


def test_content_coordinate_survives_resampling_and_audible_delay():
    from lampastream.canonicalizer import (
        AudioCanonicalizer,
        CanonicalData,
        DataResult,
        DecodedSourceFrame,
        EndOfStream,
    )

    canonicalizer = AudioCanonicalizer()
    frames = []
    for start in range(0, 44100, 441):
        # Audible time includes an arbitrary room delay; content time does not.
        frame = DecodedSourceFrame(np.zeros((441, 2), np.float32), 44100, 2, 'file',
                                   start, False, None, received_monotonic=10+start/44100,
                                   play_monotonic=15+start/44100,
                                   content_position_s=31+start/44100)
        frames.extend(r.frame for r in canonicalizer.push(DataResult(frame))
                      if isinstance(r, CanonicalData))
    frames.extend(r.frame for r in canonicalizer.push(EndOfStream())
                  if isinstance(r, CanonicalData))
    assert frames
    for frame in frames:
        assert frame.content_position_s == pytest.approx(31+frame.sample_pos/48000, abs=1e-9)
        assert frame.play_monotonic == pytest.approx(15+frame.sample_pos/48000, abs=1e-9)


def test_octave_check_keeps_slower_low_band_pulse():
    result = analyse(clicks(period=1.))
    assert result.tempo == pytest.approx(60., abs=1.)


@pytest.mark.parametrize('confirmations, rejected', [(7, True), (8, False)])
def test_contradiction_threshold_is_strictly_below_half(confirmations, rejected):
    prior = GridPrior()
    prior.set(('track', grid(), 0), .1)
    prior.onsets.extend(np.arange(.5, .5+confirmations*.5, .5))
    prior.ticks(8.2, True)
    assert (prior.grid is None) == rejected


def test_drop_strength_and_whole_track_section_horizon():
    prior = GridPrior()
    g = replace(grid(), sections=(Section('drop', 12., 12.),))
    prior.set(('track', g, 0), .1)
    assert prior.status(.1)['time_to_next_drop_s'] == pytest.approx(11.9)
    ticks = prior.ticks(12., False)
    assert ticks[-1][1] == 1.
    assert all(t[1] == .8 for t in ticks[:-1])


def test_predicted_grid_events_preserve_current_publication_and_audible_mapping():
    from lampastream.canonicalizer import AnalysisPcmFrame
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline

    pipeline = _make_canonical_pipeline(object(), Profile(beat_accent_mode='tracker'))
    pipeline._beat_fusion.grid_provider = lambda frame: ('track', grid(), 0.)
    events = []
    for start in range(0, 48000, 480):
        frame = AnalysisPcmFrame(np.zeros((480, 2), np.float32), start, 'test', 'file', False,
                                 received_monotonic=100+start/48000,
                                 play_monotonic=200+start/48000)
        records = pipeline.feed(frame)
        assert all(r.sample_end <= start+480 for r in records)
        for record in records:
            for event in record.features.onset_events:
                assert event.play_monotonic == pytest.approx(200+event.candidate_sample/48000)
                events.append(event)
    assert events and any(e.availability_sample < e.candidate_sample for e in events)
    pipeline.stop()


def test_track_change_clears_rejection_while_next_file_is_loading():
    prior = GridPrior()
    prior.set(('one', grid(), 0), .1)
    prior.ticks(8.2, True)
    assert prior.reason
    prior.set(('two', None, 0, {'grid_fetch_state': 'fetching'}), 9.)
    assert prior.reason is None and prior.blocked is None
    assert prior.status(9.)['grid_fetch_state'] == 'fetching'


@pytest.mark.serial
@pytest.mark.parametrize("same_content", [False, True])
def test_next_queued_track_is_preanalysed_by_same_worker(tmp_path, monkeypatch, same_content):
    current, following = tmp_path/'current.flac', tmp_path/'next.flac'
    current.write_bytes(clicks())
    following.write_bytes(current.read_bytes() if same_content else clicks(period=1.))
    spawn = asyncio.create_subprocess_exec
    starts = []

    async def record_spawn(*args, **kwargs):
        starts.append(args)
        return await spawn(*args, **kwargs)

    monkeypatch.setattr('lampastream.lms_grid.asyncio.create_subprocess_exec', record_spawn)

    async def run():
        async with Session(current, next_path=following) as session:
            cache = GridCache(tmp_path/'cache')
            adapter = LmsGridAdapter('127.0.0.1', session.web_port, cache)
            try:
                adapter.select('44436', current.stat().st_size)
                await adapter.playlist_next('127.0.0.1', session.cli_port, 'aa', 0)
                async with asyncio.timeout(180):
                    await adapter.queue.join()
                assert adapter.grid.tempo == pytest.approx(120, abs=2)
                assert cache.get(identity('44437', following.stat().st_size))
                full_starts = [args for args in starts if "--head" not in args]
                assert len(full_starts) == (1 if same_content else 2)
                assert len(starts)-len(full_starts) == 1
                assert len(session.requests) == 2
                adapter.select('44437', following.stat().st_size)
                async with asyncio.timeout(5):
                    await adapter.queue.join()
                assert adapter.cache_state == 'hit'
                assert adapter.grid.tempo == pytest.approx(120 if same_content else 60, abs=2)
                assert len(session.requests) == 2
            finally:
                await adapter.close()
    asyncio.run(run())


def test_epoch_reset_clears_observations_but_preserves_track_rejection():
    from lampastream.beat_fusion import BeatFusion

    fusion = BeatFusion()
    fusion.prior.set(('track', grid(), 0.), .1)
    fusion.prior.onsets.extend([.5, 1.])
    fusion.prior.ticks(8.2, True)
    assert fusion.prior.blocked == 'track'
    fusion.reset()
    assert not fusion.prior.onsets and not fusion.prior.loud
    fusion.prior.set(('track', grid(), 0.), 0.)
    assert fusion.prior.grid is None and fusion.prior.blocked == 'track'
