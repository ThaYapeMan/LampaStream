"""Bracketed SHM write-clock estimation and LMS audible-time ingress.

This observes the existing reader only; it never changes the PCM producer or DSP.
"""
from __future__ import annotations

import asyncio
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


async def cli_exchange(host, command):
    """A cancellable, bounded CLI exchange: Stop never waits for a worker thread."""
    writer = None
    try:
        async with asyncio.timeout(3):
            reader, writer = await asyncio.open_connection(host, 9090)
            writer.write(command.encode())
            await writer.drain()
            return (await reader.readline()).decode().strip()
    finally:
        if writer is not None:
            writer.close()


class LmsHeadStart:
    """Session-owned readiness/retry task; peers come only from the group observer."""
    BACKOFF = (1, 2, 5, 10, 30)

    def __init__(self, player, source, exchange=cli_exchange, clock=time.monotonic):
        if not player.player_mac or any(c.isspace() for c in player.player_mac):
            raise ValueError('A virtual player MAC is required for head start')
        self.player, self.source, self.exchange, self.clock = player, source, exchange, clock
        self.peers = ()
        self.verified = False
        self.connected = False
        self.dirty = True
        self.attempt = 0
        self.next_attempt = 0
        self.started = clock()
        self.wake = asyncio.Event()
        self.warned_start = False
        self.revision = 0
        self.group_pending = False

    def group_refresh(self, peers, reconnected=False, pending=False):
        peers = tuple(sorted(peers))
        was_pending = self.group_pending
        self.group_pending = pending
        if peers != self.peers or reconnected or pending or was_pending:
            self.revision += 1
            self.dirty = True
            self.verified = False
            self.next_attempt = float('inf') if pending else 0
            self.attempt = 0
            self._gate(False, 'waiting', 'Waiting for the virtual player in LMS')
        self.peers = peers
        if self.connected and not peers and not pending:
            self._gate(False, 'unsynced', 'Not synced with a speaker yet: sync it in LMS')
        self.wake.set()

    def _gate(self, ready, state, reason):
        if self.source is not None:
            self.source.set_readiness(ready, state, reason)

    async def query(self, command):
        raw = await self.exchange(self.player.lms_host,
                                  f'{self.player.player_mac} {command}\n')
        parts = unquote(raw).split()
        expected = [self.player.player_mac, *command.split()[:-1]]
        if len(parts) != len(expected) + 1 or parts[:-1] != expected:
            raise ValueError('LMS returned no verified player preference')
        return parts[-1]

    async def refresh(self):
        revision = self.revision
        self.connected = await self.query('connected ?') == '1'
        if not self.connected:
            self.verified = False
            self.dirty = True
            self._gate(False, 'waiting', 'Waiting for the virtual player in LMS')
            return False
        if self.dirty or not self.verified:
            await self.exchange(self.player.lms_host,
                                f'{self.player.player_mac} playerpref playDelay '
                                f'{self.player.head_start_ms}\n')
        actual = int(await self.query('playerpref playDelay ?'))
        if actual != self.player.head_start_ms:
            raise ValueError('LMS did not verify the virtual player head start')
        if self.dirty or not self.verified:
            start = float(await self.query('playerpref startDelay ?'))
            if start and not self.warned_start:
                log.warning('Virtual player startDelay is %s ms; leave it unchanged, '
                            'but set it to 0 in LMS for a steady head start', start)
                self.warned_start = True
            log.info('LMS virtual player head start verified: playDelay=%d ms', actual)
        if revision != self.revision or self.group_pending:
            return None  # A refresh superseded this in-flight verification.
        self.verified = True
        self.dirty = False
        self._gate(bool(self.peers), 'scheduled' if self.peers else 'unsynced',
                   None if self.peers else 'Not synced with a speaker yet: sync it in LMS')
        return True

    async def wait(self, seconds=None):
        if seconds is None:
            await self.wake.wait()
        else:
            try:
                await asyncio.wait_for(self.wake.wait(), seconds)
            except TimeoutError:
                pass

    async def run(self):
        while True:
            self.wake.clear()
            if self.group_pending:
                await self.wait()
                continue
            delay = self.next_attempt - self.clock()
            if delay > 0:
                await self.wait(delay)
                continue
            try:
                success = await self.refresh()
            except (OSError, ValueError, IndexError) as exc:
                success = False
                self.verified = False
                self.dirty = True
                self._gate(False, 'fallback' if self.connected else 'waiting',
                           'Head start could not be verified; using delay instead'
                           if self.connected else 'Waiting for the virtual player in LMS')
                log.warning('LMS head start verification failed; retrying: %s', exc)
            if success is None:
                self.next_attempt = float('inf') if self.group_pending else 0
                continue
            if success:
                self.attempt = 0
                self.next_attempt = float('inf')
                # Healthy re-verification is driven by the existing observer's refresh.
                await self.wait()
                self.next_attempt = 0
            else:
                delay = self.BACKOFF[min(self.attempt, len(self.BACKOFF) - 1)]
                self.attempt += 1
                if not self.connected:
                    remaining = 30 - (self.clock() - self.started)
                    delay = min(delay, remaining) if remaining > 0 else 30
                self.next_attempt = self.clock() + delay


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


class LmsTimingDiagnostics(TimingDiagnostics):
    def scene_ready(self, received, ready, play):
        if received is not None:
            with self.lock:
                self._record('scene-ready', ready, received_monotonic=received,
                             ready_monotonic=ready, play_monotonic=play,
                             timing_generation=self.tap_generation)

    def processing(self, received, ready, sent):
        # The scheduler already checks the timing generation. Unlike AirPlay's
        # cadence monitor, a write-clock epoch has no metadata playback boundary
        # against which to reject an otherwise valid publication's first receipt.
        now = self.clock()
        held = max(0, sent - ready) * 1000
        processing = max(0, (now - received) * 1000 - held)
        with self.lock:
            accepted = self.processing_window.accept(processing, time.time())
            if accepted:
                self.processing_sequence += 1
            self._record('processing', now, received_monotonic=received,
                         ready_monotonic=ready, sent_monotonic=sent,
                         processing_ms=processing, delay_hold_ms=held, accepted=accepted,
                         timing_generation=self.tap_generation)


class LmsTimedSource:
    def __init__(self, source, player, transport=lambda: None, clock=time.monotonic, ready=True):
        self.source = source
        self.player = player
        self.transport = transport
        self.clock = clock
        self.fit = WriteClock()
        self.timing = LmsTimingDiagnostics(clock=clock)
        self.timing.tap_source = 'LMS head start'
        self.bad_since = None
        self.track = None
        self.transport_position = None
        self.reason = None if ready else 'Waiting for the virtual player in LMS'
        self.ready = ready
        self.readiness_state = 'scheduled' if ready else 'waiting'
        self.fit_snapshot = dict(precision_ms=None, sample_count=0, samples=[],
                                 last_sample_time=None)
        self.reset_requested = False
        self.fit_sample_key = None
        if not ready:
            self.timing.tap_source = 'delay fallback'

    def set_readiness(self, ready, state, reason):
        if ready != self.ready:
            self.timing.tap_reset()
            self.reset_requested = True
        self.ready = ready
        self.readiness_state = state
        if not ready or self.timing.tap_source != 'delay fallback' or self.reason is None:
            self.reason = reason
        if not ready or self.reset_requested:
            self.timing.tap_source = 'LMS head start' if ready else 'delay fallback'

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
        changed = self.reset_requested or (self.track is not None and key != self.track)
        self.reset_requested = False
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
            sample_key = (self.fit.generation,
                          self.fit.samples[-1][0] if self.fit.samples else None)
            if sample_key != self.fit_sample_key:
                self.fit_sample_key = sample_key
                points = list(self.fit.samples)
                residuals = [max(lo - self.fit.at(pos), self.fit.at(pos) - hi, 0) * 1000
                             for pos, lo, hi in points] if self.fit.offset is not None else []
                wall_offset = time.time() - after
                self.fit_snapshot = dict(
                    precision_ms=percentile(residuals, .95), sample_count=len(points),
                    last_sample_time=points[-1][2] + wall_offset if points else None,
                    median_residual_ms=percentile(residuals, .5),
                    samples=[dict(residual_ms=r, timestamp=point[2] + wall_offset)
                             for point, r in zip(points[-7:], residuals[-7:], strict=False)])
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
        received = before
        self.timing.arrival(len(frame.samples), received)
        if not self.ready:
            return DataResult(replace(frame, received_monotonic=received))
        stamp = (self.fit.at(frame.source_sample_pos)
                 if frame.source_sample_pos is not None else None)
        if stamp is None:
            return result
        audible = stamp + (self.player.head_start_ms + self.player.speaker_output_delay_ms) / 1000
        self.timing.tap_arrival(audible - received, 0)
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
