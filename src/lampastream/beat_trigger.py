"""Causal band-energy triggers; no FFT, transport or output dependencies.

Ratio/post-hit adaptation follows Music Assistant aiosendspin's approach;
AGC times follow ETC/WLED. See the two BEAT-01 research documents for sources.
This is an original implementation, not a port of GPL audio-reactive code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BeatTriggerEvent:
    time: float
    band: str
    strength: float
    confidence: float
    ratio: float


class EnergyTrigger:
    """AGC, relative energy rise, adaptive floor and refractory interval.

    All statistics exclude the current sample from the decision reference.
    The slow reference has an absolute floor: silence cannot amplify noise.
    """

    def __init__(self, sensitivity=50., dead_time=.1):
        if not math.isfinite(sensitivity) or not 0 <= sensitivity <= 100:
            raise ValueError("Sensitivity must be between 0 and 100")
        self.threshold = 2.5 - sensitivity * .02
        self.floor = .08 * 2 ** ((50-sensitivity)/25)
        self.dead_time = dead_time
        self.fast = self.slow = self.mean = self.previous = 0.
        self.previous_energy = 0.
        self.last_time = None
        self.last_fire = -math.inf
        self.gain = 1.
        self.ratio = 0.

    def process(self, energy, t, band, *, gate=True, dead_time=None):
        dt = .01 if self.last_time is None else max(0., t-self.last_time)
        self.last_time = t
        energy = max(0., float(energy))
        # Preserve a sharp kick's causal attack instead of waiting for the
        # follower: an eightfold raw rise must still pass the same ratio/floor.
        abrupt = energy >= 8*max(self.fast, 1e-9)
        self.fast += -math.expm1(-dt/(.05 if energy > self.fast else .1)) * (energy-self.fast)
        self.slow += -math.expm1(-dt/5.) * (self.fast-self.slow)
        self.gain = 1/max(self.slow, 1e-4)
        value = math.log10(1 + self.fast*self.gain)
        self.ratio = value/max(self.mean, 1e-6)
        raw_value = math.log10(1+energy*self.gain)
        raw_ratio = raw_value/max(self.mean, 1e-6)
        if abrupt and raw_ratio >= self.threshold:
            self.ratio = raw_ratio
            value = raw_value
        refractory = self.dead_time if dead_time is None else dead_time
        fire = (gate and energy >= 1e-6 and value >= self.floor
                and self.ratio >= self.threshold and value > self.previous
                and energy > self.previous_energy
                and t-self.last_fire >= refractory-1e-9)
        self.previous_energy = energy
        self.previous = value
        self.mean += (-math.expm1(-dt/.3)) * (value-self.mean)
        if not fire:
            return None
        self.last_fire = t
        self.mean = .6*self.mean + .4*value
        margin = max(0., self.ratio-self.threshold)
        return BeatTriggerEvent(t, band, min(1., margin/6),
                                margin/(1+margin), self.ratio)


class BassBeatTrigger:
    """50–100 / 100–200 Hz energy from the shared long-window STFT.

    Broadband fallback starts only after four seconds without bass activity
    while the level gate is open. Mid/treble texture has its own ratio rule.
    """

    def __init__(self, sensitivity=50., band="bass", sample_rate=48000, fft_size=2048):
        if band not in {"bass", "low", "energy"}:
            raise ValueError("Beat band must be bass, low or energy")
        self.band = band
        frequencies = np.fft.rfftfreq(fft_size, 1/sample_rate)
        self.mask = ((frequencies >= (100 if band == "low" else 50))
                     & (frequencies <= (200 if band == "low" else 100)))
        # IEC A-weighting magnitude response; energy is weighted by its square.
        f2 = frequencies**2
        ra = (12194.**2*f2**2 / np.maximum(
            (f2+20.6**2)*np.sqrt((f2+107.7**2)*(f2+737.9**2))
            *(f2+12194.**2), 1e-30))
        self.weights = (ra*10**(2/20))**2
        self.texture_mask = (frequencies >= 200) & (frequencies < 2000)
        self.treble_mask = frequencies >= 2000
        self.scale = fft_size**2
        self.primary = EnergyTrigger(sensitivity)
        self.energy = EnergyTrigger(sensitivity)
        self.texture = EnergyTrigger(25, .06)
        self.treble = EnergyTrigger(25, .06)
        self.last_bass = None
        self.open_since = None
        self.first_time = None

    def process(self, magnitudes, t, *, locked=False, period=None, gate=True):
        if self.first_time is None:
            self.first_time = t
        ready = t-self.first_time >= .35
        power = np.asarray(magnitudes, dtype=float)**2/self.scale
        low = float(np.sum(power[self.mask]))
        broad = float(np.sum(power*self.weights))
        texture = float(np.sum(power[self.texture_mask]))
        treble = float(np.sum(power[self.treble_mask]))
        if not gate:
            self.open_since = None
        elif self.open_since is None:
            self.open_since = t
        dead = .6*period if locked and period is not None else .1
        bass = self.primary.process(low, t, self.band, gate=gate and ready, dead_time=dead)
        energy = self.energy.process(broad, t, "energy", gate=gate and ready, dead_time=dead)
        ticks = (self.texture.process(texture, t, "mid", gate=gate),
                 self.treble.process(treble, t, "treble", gate=gate))
        if bass is not None:
            self.last_bass = t
        reference = self.last_bass if self.last_bass is not None else self.open_since
        fallback = reference is not None and t-reference >= 4
        beat = energy if self.band == "energy" or fallback else bass
        return beat, tuple(tick for tick in ticks if tick is not None)
