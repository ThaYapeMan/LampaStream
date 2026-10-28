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


@pytest.mark.parametrize('name,bpm,lock', [
    ('house', 120, 3.02), ('techno', 128, 3.34), ('breakbeat', 174, 3.97),
    ('disco', 100, 3.52), ('deep-house', 122, 3.47)])
def test_measured_tempo_lock_and_on_beat_ratio(name, bpm, lock):
    events, history = analyse(name)
    first_lock = next(row for row in history if row[2])
    assert first_lock[0] == pytest.approx(lock, abs=1e-9)
    assert first_lock[0]-.5 <= 4
    assert history[-1][1] == pytest.approx(bpm, abs=.25)
    beats = [e for e in events if e.kind == 'beat' and not e.predicted]
    assert all(e.on_beat for e in beats)


def test_breakdown_grid_has_no_false_bass_and_keeps_phase():
    events, _ = analyse('breakdown')
    missing = [e for e in events if 3.98 <= e.candidate_sample/48000 < 7.98 and e.kind == 'beat']
    assert len(missing) == 8
    assert all(e.predicted for e in missing)
    assert all(abs(e.candidate_sample/48000-round(e.candidate_sample/24000)*.5) <= .02
               for e in missing)
    assert missing[-1].strength < missing[0].strength


def test_pink_noise_and_sweep_exact_false_trigger_counts():
    from replay_chain import Replay, decode, parser

    for name, count in [('pink-noise', 2), ('sweep', 6)]:
        args = parser().parse_args(['--input', str(FIXTURES.parent/f'{name}.wav'),
            '--config', str(FIXTURES.parent/'default-config.json'), '--out', '/tmp/unused-beat'])
        replay = Replay(args)
        try:
            pcm, rate, _ = decode(args.input)
            replay.analyse(pcm, rate)
            beats = [e for record in replay.records for e in record.features.onset_events
                     if e.kind == 'beat' and not e.predicted]
            assert len(beats) == count
            assert len(beats)/(replay.sample_count/48000) <= .5
        finally:
            replay.pipeline.stop()


def test_tempo_change_relocks_and_missing_breakbeat_grid_is_accurate():
    events, history = analyse('tempo-change')
    relock = next(t for t, bpm, locked, _ in history if t >= 6 and locked and abs(bpm-128) < 1)
    assert relock == pytest.approx(9.77, abs=1e-9)
    events, _ = analyse('breakbeat')
    grid = json.loads((FIXTURES/'breakbeat.json').read_text())['instruments']['beats']
    errors = [min(abs(e.candidate_sample-p) for p in grid) for e in events if e.predicted]
    assert max(errors) == 286
    assert max(errors)/48 <= 20


@pytest.mark.parametrize('intensity,fall', [('Subtle', 300), ('Moderate', 250),
                                          ('High', 200), ('Intense', 150)])
def test_preset_default_fall(intensity, fall):
    assert Effect(beat_intensity=intensity).beat_fall_ms == fall
    assert Effect(beat_intensity=intensity, beat_fall_ms=175).beat_fall_ms == 175
