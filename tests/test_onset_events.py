"""Timestamped event identity and bounded transport contracts."""
from dataclasses import replace

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
        assert envelope.value(2 + cap.min_visible_hold_s + .25) == __import__("pytest").approx(math.exp(-1))
        assert not envelope.trigger(.5, 2.01, "ignore_during_hold")
        envelope.trigger(.9, 2.02, "add_with_clamp")
        assert envelope.value(2.02) == 1
