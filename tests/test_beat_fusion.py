"""Production STFT fixtures, without starting a source or output worker."""
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from lampastream.beat_fusion import BeatFusion
from lampastream.models import Analyser, Effect
from lampastream.spectrum_engine import SharedAnalysisFrame
from lampastream.sync_engine import StereoMagStft

FIXTURES = Path(__file__).parent/'fixtures/replay/beats'


def analyse(name, chunk=480):
    with wave.open(str(FIXTURES/f'{name}.wav')) as stream:
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), '<i2').astype(float)/32768
    fusion, stft = BeatFusion(), StereoMagStft(48000)
    count, events, history = 0, [], []
    for start in range(0, len(pcm), chunk):
        stereo = np.repeat(pcm[start:start+chunk, None], 2, axis=1)
        mags = stft.push(stereo)
        updates = fusion.feed(SharedAnalysisFrame(stereo, mags, 'epoch', start,
            start+len(stereo), [480*(count+i) for i in range(len(mags))]))
        count += len(mags)
        events.extend(e for update in updates for e in update.onset_events)
        history.append((start/48000, fusion.clock.tempo_bpm, fusion.clock.locked,
                        fusion.clock.confidence))
    return events, history


@pytest.mark.parametrize('name', ['house', 'techno', 'breakbeat', 'disco', 'deep-house'])
def test_all_ground_truth_kicks_detected(name):
    events, _ = analyse(name)
    beats = [e for e in events if e.kind == 'beat' and not e.predicted]
    truth = json.loads((FIXTURES/f'{name}.json').read_text())['instruments']['kick']
    assert len(truth) > 0
    assert sum(any(abs(e.candidate_sample-t) <= 480 for e in beats) for t in truth) == len(truth)
    assert all(e.availability_sample >= e.candidate_sample for e in events)
    assert len({e.id for e in events}) == len(events)


def test_pad_has_zero_beat_or_texture_lift():
    assert analyse('pad-texture')[0] == []


def test_batching_does_not_change_event_identity_or_strength():
    assert analyse('house', 480)[0] == analyse('house', 4096)[0]


def test_new_configuration_defaults_roundtrip():
    analyser = Analyser.from_dict({'id': 'old'})
    effect = Effect.from_dict({'id': 'old'})
    assert (analyser.beat_sensitivity, analyser.beat_band, 
            analyser.beat_latency_ms) == (50, 'bass', 0)
    assert (effect.beat_intensity, effect.beat_mode, effect.beat_divisor,
            effect.beat_fall_ms, effect.beat_predicted) == ('Moderate', 'Phase', 1, 250, True)
    assert Analyser.from_dict(analyser.to_dict()) == analyser
    assert Effect.from_dict(effect.to_dict()) == effect
