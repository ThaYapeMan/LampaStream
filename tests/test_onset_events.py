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
