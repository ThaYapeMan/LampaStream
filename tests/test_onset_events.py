"""Timestamped event identity and bounded transport contracts."""
from dataclasses import replace

import pytest

from lampastream.models import Profile
from lampastream.player_manager import _make_canonical_pipeline
from lampastream.types import AudioFeatures, OnsetEvent


def event(sample=480):
    return OnsetEvent(("epoch", "all", sample), "epoch", sample, sample+480,
                      1, 1.0, 10.0, 1.0, frozenset({"all"}), "all")


def test_queue_survives_latest_and_drains_once():
    pipeline = _make_canonical_pipeline(None, Profile())
    try:
        features = AudioFeatures([], 0, 0, 0, 0, onset=True, onset_events=(event(),))
        for i in range(3):
            pipeline._publish(epoch_id="epoch", sample_start=i*480, sample_end=(i+1)*480,
                              features=features if i == 0 else replace(features, onset=False,
                                                                        onset_events=()),
                              effective_spectrum_backend="v2", effective_processor_ids=())
        assert not pipeline.latest().onset
        assert pipeline.drain_events() == [event()]
        assert pipeline.drain_events() == []
        assert pipeline.events_dropped_count == 0
    finally:
        pipeline.stop()


def test_undeclared_output_uses_conservative_capabilities():
    from lampastream.types import OutputCapabilities, output_capabilities
    assert output_capabilities(object()) == OutputCapabilities()


def test_envelope_event_time_hold_and_policies():
    import math

    from lampastream.onset_envelope import TriggerEnvelope
    from lampastream.trace_output import load_capabilities
    for room in ("two-channel.json", "two-channel-fast.json"):
        from pathlib import Path
        cap = load_capabilities(Path(__file__).parent / "fixtures/rooms" / room)
        envelope = TriggerEnvelope(cap.min_visible_hold_s, .25)
        envelope.trigger(1, 2)
        assert envelope.value(1.99) == 0
        assert envelope.value(2 + cap.min_visible_hold_s - 1e-9) == 1
        assert envelope.value(2 + cap.min_visible_hold_s + .25) == pytest.approx(math.exp(-1))
        assert not envelope.trigger(.5, 2.01, "ignore_during_hold")
        envelope.trigger(.9, 2.02, "add_with_clamp")
        assert envelope.value(2.02) == 1


def engine_view(events, *, sample_end=48000, source_time=None):
    import asyncio
    from types import SimpleNamespace

    from lampastream.sync_engine import SyncEngine
    from lampastream.types import Colour, UniformScene
    pipeline = _make_canonical_pipeline(None, Profile())
    if source_time is not None:
        pipeline._arrival_spans.append(("epoch", 0, sample_end, source_time))
    features = AudioFeatures([], 0, 0, 0, 0, onset_events=tuple(events))
    pipeline._publish(epoch_id="epoch", sample_start=sample_end-480, sample_end=sample_end,
                      features=features, effective_spectrum_backend="v2",
                      effective_processor_ids=())
    engine = SyncEngine(None, Profile(), analyser=pipeline)
    views = []
    engine._effect = SimpleNamespace(mix=0, render=lambda f, t:
        (views.append(f), UniformScene(Colour.BLACK))[1])

    async def stop(_):
        raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.run(SimpleNamespace(send=lambda *args: None),
                                   clock=lambda: 1.0, sleep=stop))
        return engine, views
    finally:
        pipeline.stop()


def test_burst_max_merges_peak_without_losing_count():
    first = replace(event(47520), strength=.7)
    second = event(48000)
    engine, views = engine_view([first, second])
    assert views[0].onset_count_since_render == 2
    assert views[0].onset_envelope == 1
    assert views[0].onset
    assert engine.event_counters["all"] == dict(
        received=2, merged=1, triggered=1, expired=0, lost=0)


def test_expired_event_does_not_trigger():
    engine, views = engine_view([event(0)])
    assert views[0].onset_count_since_render == 0
    assert views[0].onset_envelope == 0
    assert engine.event_counters["all"] == dict(
        received=1, merged=0, triggered=0, expired=1, lost=0)


def test_output_agnostic_onset_modules():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/lampastream"
    matches = []
    for name in ("sync_engine.py", "onset_envelope.py", "accent.py", "audible_preview.py"):
        for line, text in enumerate((root / name).read_text().splitlines(), 1):
            if re.search(r"\b(?:25|255)\b|hue", text, re.IGNORECASE):
                matches.append((name, line, text))
    assert matches == []
    print("output-agnostic grep: 0 matches (25, 255, hue)")


def test_gate_freezes_statistics_and_resumption_does_not_emit():
    from lampastream.sync_engine import OnsetDetector
    picker = OnsetDetector()
    for _ in range(100):
        picker.process_odf_event(.2, -20)
    reference = picker._flux_ema, picker._flux_var
    for _ in range(500):
        picker.process_odf_event(0, -90)
    assert (picker._flux_ema, picker._flux_var) == reference
    for _ in range(20):
        assert picker.process_odf_event(.2, -20) is None


def test_band_merge_window_is_anchored_to_earliest_candidate():
    from lampastream.spectrum_engine import ProcessorUpdate
    from lampastream.sync_engine import BeatDetector
    beat = BeatDetector("multiband", .1, .9, 3, 2, 250, 2000)

    def update(sample, band):
        item = replace(event(sample), id=("epoch", band, sample), bands=frozenset({band}),
                       dominant_band=band, confidence=1/3)
        return ProcessorUpdate("beat_detector", sample, sample+480, onset=True,
                               onset_events=(item,))

    state = beat._state
    assert beat._merge_band_updates(state, [update(0, "bass")], 480) == []
    assert beat._merge_band_updates(state, [update(480, "mid")], 960) == []
    result = beat._merge_band_updates(state, [update(1920, "treble")], 1920)
    assert len(result) == 1
    assert result[0].onset_events[0].candidate_sample == 0
    assert result[0].onset_events[0].bands == frozenset({"bass", "mid"})
    assert result[0].onset_events[0].confidence == pytest.approx(2/3)
    assert beat.flush()[0].onset_events[0].bands == frozenset({"treble"})


@pytest.mark.parametrize("lookahead", range(4))
def test_explicit_lookahead_is_the_only_picker_confirmation_delay(lookahead):
    from lampastream.sync_engine import OnsetDetector
    picker = OnsetDetector(lookahead_frames=lookahead)
    hits = []
    for frame in range(80):
        result = picker.process_odf_event(10.0 if frame == 50 else .1)
        if result:
            hits.append(result)
    assert len(hits) == 1
    assert hits[0].candidate_frame == 50
    assert hits[0].availability_frame == 50 + lookahead
    assert hits[0].candidate_strength == 10


def test_add_with_clamp_stays_bounded_through_repeated_bursts():
    from lampastream.onset_envelope import TriggerEnvelope
    envelope = TriggerEnvelope(.1, .2)
    for i in range(100):
        envelope.trigger(.9, i/100, "add_with_clamp")
        assert 0 <= envelope.value(i/100) <= 1


def test_source_event_anchor_is_independent_of_drain_clock():
    item = event(47520)
    engine, views = engine_view([item], source_time=.95)
    assert views[0].onset_age_s == pytest.approx(.05)
    assert engine.event_records[item.id]["event_time"] == .95
    assert engine.event_records[item.id]["event"].received_monotonic == 1.0


def test_clock_maps_containing_and_extrapolated_canonical_samples():
    from types import SimpleNamespace

    from lampastream.audible_clock import LmsAudibleClock
    clock = LmsAudibleClock(timing=SimpleNamespace(tap_source='LMS head start'))
    first = AudioFeatures([], 0, 0, 0, 0, play_monotonic=10.)
    second = replace(first, play_monotonic=10.03)
    assert clock.at(480, 480, first, 9.).audible == 10.
    assert clock.at(2400, 1920, second, 9.).audible == 10.04


def test_precision_guard_preserves_unlit_channels_and_holds_subcode_decay():
    from lampastream.output_boundary import QuantisationGuard
    from lampastream.types import Colour, OutputCapabilities
    guard = QuantisationGuard(OutputCapabilities(colour_depth_bits=12))
    baseline = Colour(.1, 0, .2)
    assert guard.colour("lamp", baseline, False) is baseline
    lifted = guard.colour("lamp", Colour(.101, 0, .2), True)
    assert lifted.r >= .1 + (1 << 3) * guard.lsb
    assert lifted.g == 0
    assert lifted.b == .2
    peak = guard.colour("lamp", Colour(.5, 0, .2), True)
    assert guard.colour("lamp", Colour(.5-guard.lsb/2, 0, .2), True) == peak


def test_capability_hold_default_tracks_declared_output_rate():
    from lampastream.types import OutputCapabilities
    assert OutputCapabilities(update_hz=60).min_visible_hold_s == 2/60
    with pytest.raises(ValueError):
        OutputCapabilities(update_hz=float("nan"))
