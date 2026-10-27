"""Independent physical-signal tests for the BEAT-01 energy rule."""
import numpy as np
import pytest

from lampastream.beat_trigger import BassBeatTrigger, EnergyTrigger


def test_sustained_band_and_silence_do_not_retrigger():
    trigger = EnergyTrigger()
    hits = [trigger.process(.01, n*.01, 'bass') for n in range(1200)]
    assert sum(hit is not None for hit in hits) == 1
    assert all(trigger.process(0, 12+n*.01, 'bass', gate=False) is None
               for n in range(500))
    assert trigger.gain <= 10000


def test_refractory_and_strength_mapping():
    trigger = EnergyTrigger()
    first = trigger.process(.01, 0, 'bass')
    assert first.strength == 1
    trigger.process(0, .01, 'bass')
    assert trigger.process(.02, .05, 'bass') is None
    trigger.process(0, .09, 'bass')
    second = trigger.process(.04, .1, 'bass')
    assert second is not None
    assert second.strength == pytest.approx(min(1, (second.ratio-1.5)/6))


def test_high_frequency_is_texture_not_bass():
    trigger = BassBeatTrigger()
    mag = np.zeros(1025)
    mag[100] = 100
    beat, texture = trigger.process(mag, 0)
    assert beat is None
    assert texture is not None


@pytest.mark.parametrize('sensitivity', [-1, 101, float('nan')])
def test_invalid_sensitivity(sensitivity):
    with pytest.raises(ValueError):
        EnergyTrigger(sensitivity)
