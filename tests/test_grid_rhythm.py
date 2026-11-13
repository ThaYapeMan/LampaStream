"""Section-level carrying-band and conservative 3/4/4/4 bar estimation."""
import numpy as np
import pytest

from lampastream.attacks import attack_envelope
from lampastream.grid import Section
from lampastream.grid.rhythm import describe, estimate_bar


@pytest.mark.parametrize('length', [3, 4])
def test_bar_period_and_phase_from_accented_energy(length):
    energy = np.tile([1.]+[.25]*(length-1), 16)
    found, phase, confidence = estimate_bar(np.roll(energy, 1))
    assert found == length and phase == 1 and confidence > .9
    _, _, confidence = estimate_bar(np.ones(64))
    assert confidence == 0


def test_riff_reduced_band_then_full_kick_and_dark_pad():
    rate, duration = 48000, 48
    beats = np.arange(.5, duration, .5)
    pcm = np.zeros((rate*duration, 2), np.float32)
    time = np.arange(4800)/rate
    for beat in beats:
        if beat >= 32:
            continue
        frequency = 1000 if beat < 16 else 80
        tone = (.5*np.sin(2*np.pi*frequency*time)*np.exp(-time*55)).astype(np.float32)
        start = round(beat*rate)
        pcm[start:start+len(tone), 0] += tone
    bands = {name: attack_envelope(pcm, band=band)[0] for name, band in
             [('low', (40, 150)), ('mid', (150, 2000)), ('high', (2000, 10000))]}
    flags = (beats >= 16) & (beats < 32)
    tempo, rhythm, _ = describe(beats, flags, (Section('tempo', .5, duration, 120),),
                               bands, .005, duration)
    assert len(tempo) == 1
    def carrier(t):
        return next(section.beat_band for section in rhythm if section.start <= t < section.end)
    assert carrier(8) == 'mid'
    assert carrier(24) == 'low'
    assert carrier(40) == 'none'
    assert all(section.end-section.start >= 1.5 for section in rhythm)


def test_offbeat_hats_do_not_claim_a_beat_carrier():
    beats = np.arange(.5, 32, .5)
    values = np.zeros(6400)
    values[np.rint(np.r_[beats, beats+.25]/.005).astype(int)] = 1
    bands = dict(low=np.zeros_like(values), mid=np.zeros_like(values), high=values)
    _, sections, _ = describe(beats, np.zeros(len(beats), bool),
                              (Section('tempo', .5, 32, 120),), bands, .005, 32)
    assert all(section.beat_band == 'none' for section in sections)
