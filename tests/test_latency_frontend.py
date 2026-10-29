"""Independent onset resolution preserves continuous spectrum and hop clocks."""
import numpy as np
import pytest

from lampastream.pcm_source import PcmStft
from lampastream.sync_engine import StereoMagStft


@pytest.mark.parametrize('window', [256, 512, 1024])
def test_short_window_chunk_invariant(window):
    pcm = np.random.default_rng(71).normal(size=(4800, 2)).astype(np.float32)
    whole = StereoMagStft(48000, window, right_aligned=True).push(pcm)
    stream = StereoMagStft(48000, window, right_aligned=True)
    split = [mag for start in range(0, len(pcm), 100)
             for mag in stream.push(pcm[start:start+100])]
    assert len(whole) == len(split) == 10
    for a, b in zip(whole, split, strict=True):
        np.testing.assert_array_equal(a, b)
    stream.reset()
    for a, b in zip(whole, stream.push(pcm), strict=True):
        np.testing.assert_array_equal(a, b)


def test_long_stft_unchanged():
    pcm = np.random.default_rng(9).normal(size=4800).astype(np.float32)
    frames = PcmStft(48000).push(pcm)
    expected = [np.abs(np.fft.rfft(pcm[i:i+2048] * np.hamming(2048).astype(np.float32)))
                .astype(np.float32) for i in range(0, len(pcm)-2048+1, 480)]
    np.testing.assert_array_equal(frames, expected)


def test_schedule_next_deadline_and_generation():
    from lampastream.scheduler import RenderRequest, Scheduler
    from lampastream.types import OutputCapabilities

    schedule = Scheduler(OutputCapabilities(transport_latency_s=0))
    schedule.reset(1)
    schedule.add(RenderRequest('a', 0, 1.012), 0)
    schedule.add(RenderRequest('b', 0, 1.017), 0)
    assert schedule.next_due() == 1.012
    assert schedule.due(1.011) is None
    assert schedule.due(1.012).features == 'a'
    assert schedule.next_due() == 1.017
    schedule.reset(2)
    assert schedule.next_due() is None


def test_slow_render_cannot_send_two_extras_in_one_drain(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from lampastream import scheduler as scheduling
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline
    from lampastream.scheduler import RenderRequest
    from lampastream.sync_engine import SyncEngine
    from lampastream.types import (
        AudioFeatures,
        Colour,
        OnsetEvent,
        OutputCapabilities,
        UniformScene,
    )

    clock = [0.0]
    pipeline = _make_canonical_pipeline(None, Profile())
    pipeline._publish(epoch_id='epoch', sample_start=0, sample_end=480,
                      features=AudioFeatures([.3]*30, .3, .3, .3, .3),
                      effective_spectrum_backend='v2', effective_processor_ids=('v2',))
    scene = UniformScene(Colour.BLACK)

    class Schedule(scheduling.Scheduler):
        def __init__(self, capabilities, **kwargs):
            super().__init__(capabilities, **kwargs)
            self.add(RenderRequest(pipeline.latest(), 0, .025), 0)

    monkeypatch.setattr(scheduling, 'Scheduler', Schedule)
    engine = SyncEngine(None, Profile(), analyser=pipeline)

    def render(features, t):
        clock[0] += .02  # deliberately exceeds the declared minimum send spacing
        return scene

    engine._effect = SimpleNamespace(render=render, mix=0)
    output = SimpleNamespace(send=lambda *args: None,
                             capabilities=OutputCapabilities(update_hz=100))
    sleeps = 0

    async def sleep(dt):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError
        clock[0] += dt
        event = OnsetEvent(('epoch', 'all', 0), 'epoch', 0, 480, 1, 1, 1, 1,
                           frozenset({'all'}), 'all', received_monotonic=clock[0],
                           kind='beat', on_beat=True)
        pipeline._event_queue.append(event)

    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.run(output, clock=lambda: clock[0], sleep=sleep))
        assert engine.extra_send_stats['sends'] == 1
        assert engine.extra_send_stats['max_per_drain'] == 1
    finally:
        pipeline.stop()
