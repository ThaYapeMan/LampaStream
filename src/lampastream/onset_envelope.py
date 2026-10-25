"""Event-time trigger envelopes, independent of render and output rates."""
from __future__ import annotations

import math
from bisect import insort


class TriggerEnvelope:
    """Hold then exponential release, evaluated on the scene's clock.

    History permits timestamped scenes to be evaluated before future triggers.
    Restart replaces the peak; ignore_during_hold preserves the held trigger;
    add_with_clamp adds the current value and clamps the new peak to unity.
    """

    def __init__(self, hold_s: float, release_s: float):
        self.hold_s = hold_s
        self.release_s = release_s
        self._triggers: list[tuple[float, float]] = []

    def trigger(self, strength: float, t_event: float, policy: str = "restart") -> bool:
        strength = min(1.0, max(0.0, strength))
        preceding = [item for item in self._triggers if item[0] <= t_event]
        if policy == "ignore_during_hold" and preceding:
            if t_event - preceding[-1][0] < self.hold_s:
                return False
        elif policy == "add_with_clamp":
            strength = min(1.0, strength + self.value(t_event))
        elif policy not in {"restart", "ignore_during_hold"}:
            raise ValueError(f"Unknown onset retrigger policy: {policy}")
        insort(self._triggers, (t_event, strength))
        # Bound history without removing any recent event-time scene.
        if len(self._triggers) > 1000:
            self._triggers.pop(0)
        return True

    def value(self, t: float) -> float:
        for stamp, peak in reversed(self._triggers):
            if stamp <= t:
                age = t-stamp
                if age < self.hold_s:
                    return peak
                return peak * math.exp(-(age-self.hold_s) / max(self.release_s, 1e-6))
        return 0.0
