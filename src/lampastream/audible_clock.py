"""Player-layer mappings from canonical sample coordinates to room time.

Only this boundary interprets player timing diagnostics and latency probes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClockPoint:
    audible: float
    lookahead_s: float = 0.


class AudibleClock:
    """Causal PCM clock with a measured offset to the listening room."""

    def __init__(self, probe=None, timing=None, lookahead=None):
        self.probe, self.timing = probe, timing
        self._lookahead = lookahead

    @property
    def generation(self):
        return getattr(self.timing, 'tap_generation', 0)

    @property
    def lookahead_s(self):
        return 0.

    def at(self, sample, reference, features, now):
        delay = self.probe.current_delay_ms()/1000 if self.probe is not None else 0.
        anchor = features.received_monotonic
        offset = (sample-reference)/48000
        if anchor is None:
            anchor = now
            offset = min(0., offset)
        return ClockPoint(anchor+offset+max(0., delay))

    def scene_ready(self, received, ready, audible):
        recorder = getattr(self.timing, 'scene_ready', None)
        if recorder is not None:
            recorder(received, ready, audible)

    def sent(self, received, ready, stamp):
        if self.timing is not None and received is not None:
            self.timing.processing(received, ready, stamp)


class LmsAudibleClock(AudibleClock):
    """yeney-core play clock plus the synced room's stored/measured offset.

    LmsTimedSource supplies calibrated provenance when head start is available;
    the latency probe supplies the measured room offset for causal PCM.
    """

    @property
    def lookahead_s(self):
        if self._lookahead is not None:
            return self._lookahead
        return .5 if getattr(self.timing, 'tap_source', '') == 'LMS head start' else 0.

    def at(self, sample, reference, features, now):
        if self.lookahead_s and features.play_monotonic is not None:
            config = getattr(self.probe, 'config', None)
            trim = config.trim_ms/1000 if config is not None else 0.
            return ClockPoint(features.play_monotonic+(sample-reference)/48000+trim,
                              self.lookahead_s)
        return super().at(sample, reference, features, now)


class AirPlayAudibleClock(AudibleClock):
    """Early-tap room clock, with causal pipe fallback behind the same mapping."""

    @property
    def lookahead_s(self):
        if self._lookahead is not None:
            return self._lookahead
        return 1.5 if getattr(self.timing, 'tap_source', '') == 'early tap' else 0.

    def at(self, sample, reference, features, now):
        if self.lookahead_s and features.play_monotonic is not None:
            config = getattr(self.probe, 'config', None)
            trim = config.trim_ms/1000 if config is not None else 0.
            return ClockPoint(features.play_monotonic+(sample-reference)/48000+trim,
                              self.lookahead_s)
        return super().at(sample, reference, features, now)
