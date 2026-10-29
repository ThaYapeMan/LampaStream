"""Player-layer mappings from canonical sample coordinates to room time.

Only this boundary interprets player timing diagnostics and latency probes.
"""
from __future__ import annotations

from contextlib import nullcontext
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
        self._calibration = None
        self._revision = 0

    @property
    def generation(self):
        return getattr(self.timing, 'tap_generation', 0), self._revision

    @property
    def lookahead_s(self):
        return 0.

    def valid(self, features):
        generation = features.timing_generation
        return (self.timing is None or generation is None
                or generation == getattr(self.timing, 'tap_generation', 0))

    def at(self, sample, reference, features, now):
        if not self.valid(features):
            return None
        delay = self.probe.current_delay_ms()/1000 if self.probe is not None else 0.
        self._set_calibration(("delay", delay))
        anchor = features.received_monotonic
        offset = (sample-reference)/48000
        if anchor is None:
            anchor = now
            offset = min(0., offset)
        return ClockPoint(anchor+offset+max(0., delay))

    def _set_calibration(self, value):
        if self._calibration is not None and value != self._calibration:
            self._revision += 1
        self._calibration = value

    def _lead_estimate(self, fallback):
        if self._lookahead is not None:
            return self._lookahead
        with getattr(self.timing, 'lock', nullcontext()):
            leads = getattr(self.timing, 'tap_leads', None)
            return max(0., leads[-1]/1000) if leads else fallback

    def scene_ready(self, received, ready, audible):
        recorder = getattr(self.timing, 'scene_ready', None)
        if recorder is not None:
            recorder(received, ready, audible)
        if self.probe is not None:
            self.probe.current_delay_ms()

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
        # The measured room offset/head start is already in audible time.
        return self._lookahead if self._lookahead is not None else 0.

    def at(self, sample, reference, features, now):
        if not self.valid(features):
            return None
        if (getattr(self.timing, 'tap_source', '') == 'LMS head start'
                and features.play_monotonic is not None):
            config = getattr(self.probe, 'config', None)
            trim = config.trim_ms/1000 if config is not None else 0.
            self._set_calibration(("trim", trim))
            return ClockPoint(features.play_monotonic+(sample-reference)/48000+trim,
                              self.lookahead_s)
        if features.play_monotonic is not None and self.timing is None:
            delay = self.probe.current_delay_ms()/1000 if self.probe is not None else 0.
            self._set_calibration(("delay", delay))
            return ClockPoint(features.play_monotonic+(sample-reference)/48000+max(0., delay),
                              self.lookahead_s)
        return super().at(sample, reference, features, now)


class AirPlayAudibleClock(AudibleClock):
    """Early-tap room clock, with causal pipe fallback behind the same mapping."""

    @property
    def lookahead_s(self):
        if self._lookahead is not None:
            return self._lookahead
        return (self._lead_estimate(1.5)
                if getattr(self.timing, 'tap_source', '') == 'early tap' else 0.)

    def at(self, sample, reference, features, now):
        if not self.valid(features):
            return None
        if self.lookahead_s and features.play_monotonic is not None:
            config = getattr(self.probe, 'config', None)
            trim = config.trim_ms/1000 if config is not None else 0.
            self._set_calibration(("trim", trim))
            return ClockPoint(features.play_monotonic+(sample-reference)/48000+trim,
                              self.lookahead_s)
        return super().at(sample, reference, features, now)


class SqueezeboxAudibleClock(LmsAudibleClock):
    """Hardware LMS room: player play position plus that player's measured offset."""
    kind = 'squeezebox'


class YeneyRoomAudibleClock(LmsAudibleClock):
    """YeneY/Sonos room: virtual play position plus the room's measured offset.

    AutoLatencyProbe.current_delay_ms already includes its player_delay term
    (the reported pipeline/playDelay), so it must never be added a second time.
    Stored per-player fixed offsets remain authoritative when Auto is disabled.
    """
    kind = 'yeney-sonos'

    @property
    def reported_pipeline_delay_ms(self):
        return getattr(self.probe, 'player_delay', None)


def lms_clock_for_model(model, probe=None, timing=None):
    """Select in PlayerManager; no model identity escapes this per-source object."""
    model = model.lower() if isinstance(model, str) else ''
    if any(token in model for token in ('yeney', 'sonos')):
        result = YeneyRoomAudibleClock(probe, timing)
    elif ('squeezebox' in model or set(model.split('/')) &
          {'squeezebox2', 'squeezebox3', 'baby', 'fab4', 'transporter', 'slimp3'}):
        result = SqueezeboxAudibleClock(probe, timing)
    else:
        result = LmsAudibleClock(probe, timing)
    result.model = model or 'unknown LMS model'
    return result
