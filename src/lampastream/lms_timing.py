"""Bracketed SHM write-clock estimation and LMS audible-time ingress.

This observes the existing reader only; it never changes the PCM producer or DSP.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import replace
from urllib.parse import unquote

import numpy as np

from .airplay_timing import TimingDiagnostics, percentile
from .canonicalizer import (
    DataResult,
    InvalidationCause,
    StreamInvalidated,
    TemporarilyNoData,
)
from .lms_follower import _cli_exchange

log = logging.getLogger(__name__)


def configure_head_start(player, exchange=_cli_exchange):
    """Set and verify only this virtual player's preference, using bounded CLI I/O."""
    if player.follow_mode != 'sync_group':
        return False
    if not player.player_mac or any(c.isspace() for c in player.player_mac):
        raise ValueError('A virtual player MAC is required for head start')
    prefix = f'{player.player_mac} playerpref '
    exchange(player.lms_host, 9090, prefix + f'playDelay {player.head_start_ms}\n')
    actual = unquote(exchange(player.lms_host, 9090, prefix + 'playDelay ?\n')).split()[-1]
    if int(actual) != player.head_start_ms:
        raise ValueError('LMS did not verify the virtual player head start')
    start = unquote(exchange(player.lms_host, 9090, prefix + 'startDelay ?\n')).split()[-1]
    if float(start) != 0:
        log.warning('Virtual player startDelay is %s ms; leave it unchanged, but set it to 0 '
                    'in LMS for a steady head start', start)
    log.info('LMS virtual player head start verified: playDelay=%d ms', player.head_start_ms)
    return True


class WriteClock:
    """Fit a 30-second interval-constrained clock, rejecting reads over 15 ms late.

    Each advancing position constrains its write to [previous read, current read].
    The fitted slope uses long-baseline pairs; the intercept uses robust interval
    bounds, rather than treating the read time as the write time.
    """
    def __init__(self):
        self.samples = deque()
        self.previous = None
        self.key = None
        self.generation = 0
        self.rate = 44100.0
        self.offset = None
        self.stopped = False
        self.batch_frames = 0

    def reset(self):
        self.samples.clear()
        self.offset = None
        self.generation += 1

    def observe(self, position, before, after, rate, generation, gap, running):
        key = (rate, generation, gap, running)
        changed = self.key is not None and key != self.key
        self.key = key
        previous = self.previous
        self.previous = (position, after)
        if changed:
            self.reset()
        if not running or rate <= 0:
            return changed
        if previous is None or changed:
            self.rate = float(rate)
            return changed
        old_position, old_time = previous
        if position == old_position:
            if (
                self.offset is not None
                and after - self.at(position) > max(.020, self.batch_frames / self.rate + .005)
                and not self.stopped
            ):
                self.reset()
                self.stopped = True
                return True
            return False
        if self.stopped:
            self.stopped = False
            self.reset()
            changed = True
        if position > old_position:
            self.batch_frames = position - old_position
        width = after - old_time
        if position < old_position:
            self.reset()
            changed = True
        # A delayed read gives no evidence of a producer jump. Do not use it in the fit.
        if width > .015 or width <= 0:
            return changed
        if self.offset is not None:
            prediction = self.at(position)
            if prediction < old_time - .005 or prediction > after + .005:
                self.reset()
                changed = True
        self.samples.append((position, old_time, after))
        while self.samples and self.samples[0][2] < after - 30:
            self.samples.popleft()
        points = list(self.samples)
        # Long-baseline midpoint slopes reduce quantisation and poll-jitter errors.
        slopes = []
        if points and after - points[0][2] >= 5:
            first = points[0]
            for last in points[-32:]:
                elapsed = (last[1] + last[2] - first[1] - first[2]) / 2
                if elapsed >= 5:
                    slopes.append((last[0] - first[0]) / elapsed)
        fitted = float(np.median(slopes)) if slopes else float(rate)
        self.rate = float(np.clip(fitted, rate * .998, rate * 1.002))
        lower = [lo - pos / self.rate for pos, lo, hi in points]
        upper = [hi - pos / self.rate for pos, lo, hi in points]
        lo, hi = np.percentile(lower, 95), np.percentile(upper, 5)
        self.offset = float((lo + hi) / 2)
        return changed

    def at(self, position):
        return None if self.offset is None else self.offset + position / self.rate


class LmsTimedSource:
    def __init__(self, source, player, transport=lambda: None, clock=time.monotonic):
        self.source = source
        self.player = player
        self.transport = transport
        self.clock = clock
        self.fit = WriteClock()
        self.timing = TimingDiagnostics(clock=clock)
        self.timing.tap_source = 'LMS head start'
        self.bad_since = None
        self.track = None
        self.transport_position = None
        self.reason = None

    def open(self, *args, **kwargs):
        return self.source.open(*args, **kwargs)

    def close(self):
        return self.source.close()

    @property
    def running(self):
        return self.source.running

    def reset(self):
        self.fit.reset()
        self.timing.tap_reset()

    def read(self):
        before = self.clock()
        ext = self.source._read_ext_coherent() if self.source._mm is not None else None
        after = self.clock()
        track = self.transport()
        key = (track.title, track.artist, track.playing) if track else None
        changed = self.track is not None and key != self.track
        self.track = key
        position = getattr(track, "position_s", None)
        if position is not None and self.transport_position is not None:
            changed = changed or position < self.transport_position - .05
        self.transport_position = position
        if changed:
            self.reset()
        if ext is not None:
            _, _, running, rate, _ = self.source._read_header()
            jumped = self.fit.observe(ext.abs_write_pos, before, after, rate,
                                      ext.generation, ext.gap_seq, running)
            if jumped:
                self.timing.tap_reset()
            changed = changed or jumped
        result = self.source.read()
        if isinstance(result, StreamInvalidated):
            if not changed:
                self.reset()
            return result
        if changed:
            return StreamInvalidated(InvalidationCause.SEEK, None)
        if not isinstance(result, DataResult):
            return result
        if track and not track.playing:
            return TemporarilyNoData()
        frame = result.frame
        stamp = (self.fit.at(frame.source_sample_pos)
                 if frame.source_sample_pos is not None else None)
        if stamp is None:
            return result
        audible = stamp + (self.player.head_start_ms + self.player.speaker_output_delay_ms) / 1000
        received = self.clock()
        self.timing.tap_arrival(audible - received, 0)
        self.timing.arrival(len(frame.samples), received)
        data = self.timing.snapshot()
        processing = percentile([s['processing_ms'] for s in data['samples']], .95)
        insufficient = (processing is not None and data['lead_p5_ms'] is not None
                        and data['lead_p5_ms'] < processing + 40)
        if insufficient:
            if self.bad_since is None:
                self.bad_since = received
            if received - self.bad_since >= 5:
                self.timing.tap_source = 'delay fallback'
                self.reason = 'Not enough head start, using delay instead'
        else:
            self.bad_since = None
            if self.timing.tap_source != 'LMS head start':
                self.timing.tap_reset()
            self.timing.tap_source = 'LMS head start'
            self.reason = None
        return DataResult(replace(frame, received_monotonic=received, play_monotonic=audible,
                                  timing_generation=self.timing.tap_generation))
