"""Select the blend input without changing analysis or LayerMixer ballistics."""
from __future__ import annotations

import math

import numpy as np

from .models import Profile
from .types import AudioFeatures


class EnergyInput:
    """Sustained energy, LUFS windows, or a peak envelope with optional bar reshape.

    Adaptive mode starts at [-30, -8] LUFS, expands with a 1 s time constant
    and contracts with the configured time constant. A six-LU minimum span
    prevents collapse. Constant programmes approach the centre, so fixed mode
    remains the appropriate choice for a persistent absolute-level reading.
    Silence/warmup produce zero and do not train the adaptive window.
    """

    def __init__(self, profile: Profile) -> None:
        self.mode = profile.energy_source
        self.floor = profile.lufs_floor
        self.ceiling = profile.lufs_ceiling
        self.tau = profile.adaptation_tau_s
        self.peak_attack_s = 0.05 if profile.peak_envelope_auto else profile.peak_attack_s
        self.peak_release_s = 2.0 if profile.peak_envelope_auto else profile.peak_release_s
        self.peak_reshape_enabled = profile.peak_reshape_enabled
        self.peak_reshape_power = profile.peak_reshape_power
        self._peak_envelope: float | None = None
        self.adaptive_floor = -30.0
        self.adaptive_ceiling = -8.0
        self._last_t: float | None = None

    def select(self, features: AudioFeatures, t: float) -> float:
        if self.mode == "sustained":
            # Exact existing default, including canonical's full fallback.
            return (features.sustained_energy if features.sustained_energy is not None
                    else features.full)
        dt = max(0.0, t - self._last_t) if self._last_t is not None else 0.0
        self._last_t = t
        if self.mode == "peak_envelope":
            level = features.level
            if self.peak_reshape_enabled:
                if any(not math.isfinite(b) for b in features.bars):
                    return 0.0
                level = (float(np.mean([max(0.0, b) ** self.peak_reshape_power
                                        for b in features.bars]))
                         if len(features.bars) else 0.0)
            if level is None or not math.isfinite(level):
                return 0.0
            if self._peak_envelope is None:
                self._peak_envelope = level
            else:
                k = (self.peak_attack_s if level > self._peak_envelope
                     else self.peak_release_s)
                self._peak_envelope += (1 - math.exp(-dt / max(k, 1e-6))) * (
                    level - self._peak_envelope)
            return max(0.0, min(1.0, level / max(self._peak_envelope, 1e-6)))
        value = features.loudness_momentary_lufs
        if value is None or not math.isfinite(value):
            return 0.0
        low, high = self.floor, self.ceiling
        if self.mode == "loudness_adaptive":
            low, high = self.adaptive_floor, self.adaptive_ceiling
            low += (1 - math.exp(-dt / (1.0 if value < low else self.tau))) * (value - low)
            high += (1 - math.exp(-dt / (1.0 if value > high else self.tau))) * (value - high)
            if high - low < 6.0:
                centre = (low + high) / 2
                low, high = centre - 3.0, centre + 3.0
            self.adaptive_floor, self.adaptive_ceiling = low, high
        return max(0.0, min(1.0, (value - low) / (high - low)))
