"""Single-owner timestamped AirPlay ingress and bounded scene scheduling.

Wire v1 is little-endian, 52-byte header and at most 1000 S16 stereo frames.
The receiver writes records atomically below PIPE_BUF. No second FIFO consumer.
"""

from __future__ import annotations

import heapq
import logging
import os
import stat
import struct
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .canonicalizer import (
    DataResult,
    DecodedSourceFrame,
    InvalidationCause,
    StreamInvalidated,
    TemporarilyNoData,
)
from .pcm_source import AirPlayPipeStereoSource

log = logging.getLogger(__name__)
HEADER = struct.Struct("<4sHHIIIQQQQ")
FLUSH, PAUSE, RESUME, DISCONTINUITY, OUT_OF_ORDER = 1, 2, 4, 8, 16


@dataclass(frozen=True)
class TapRecord:
    flags: int
    rtp: int
    frames: int
    generation: int
    play_ns: int
    raw_ns: int
    mono_ns: int
    drops: int
    pcm: bytes

    @property
    def play_time(self):
        return (self.mono_ns + self.play_ns - self.raw_ns) / 1e9

    def encode(self):
        return (
            HEADER.pack(
                b"LSET",
                1,
                self.flags,
                self.rtp,
                self.frames,
                self.generation,
                self.play_ns,
                self.raw_ns,
                self.mono_ns,
                self.drops,
            )
            + self.pcm
        )


class TapFramer:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, raw):
        self.buffer.extend(raw)
        records = []
        while len(self.buffer) >= HEADER.size:
            magic, version, flags, rtp, frames, generation, play, raw_clock, mono, drops = (
                HEADER.unpack_from(self.buffer)
            )
            if magic != b"LSET" or version != 1 or frames > 1000 or flags & ~31:
                self.buffer.clear()
                raise ValueError("Malformed early-tap record")
            size = HEADER.size + frames * 4
            if len(self.buffer) < size:
                break
            if frames and (
                not play or not raw_clock or not mono or abs(play - raw_clock) > 30_000_000_000
            ):
                self.buffer.clear()
                raise ValueError("Invalid early-tap clock pair")
            records.append(
                TapRecord(
                    flags,
                    rtp,
                    frames,
                    generation,
                    play,
                    raw_clock,
                    mono,
                    drops,
                    bytes(self.buffer[HEADER.size : size]),
                )
            )
            del self.buffer[:size]
        return records


class EarlyAirPlaySource:
    """Read both FIFOs once: drain regular PCM while only analysing the healthy tap.

    Regular PCM is discarded while tap is healthy so its writer cannot block.
    Source transitions invalidate DSP and scheduled scenes; no receiver restart.
    """

    def __init__(
        self, *, timing, path="/run/lampastream/airplay-early.pcm", pipe=None, clock=time.monotonic
    ):
        self.timing, self.path, self.clock = timing, path, clock
        self.pipe = pipe or AirPlayPipeStereoSource(timing=timing)
        self.fd = None
        self.opened = False
        self.framer = TapFramer()
        self.records = deque()
        self.last_record = None
        self.open_attempt = -float("inf")
        self.mode = "pipe fallback"
        self.reported_fallback = False
        self.wire_generation = None
        self.expected = None
        self.paused = False
        self.pending = None
        self.observed_generation = timing.tap_generation

    def open(self):
        self.pipe.open()
        self._open_tap()
        self.opened = True

    def _open_tap(self):
        self.open_attempt = self.clock()
        try:
            if not stat.S_ISFIFO(os.stat(self.path).st_mode):
                return
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            self.fd = None

    def close(self):
        self.opened = False
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.pipe.close()

    @property
    def running(self):
        return self.opened and (self.pipe.running or self.mode == "early tap")

    def discard_pending(self):
        self.pipe.discard_pending()
        if self.fd is not None:
            for _ in range(16):
                try:
                    if not os.read(self.fd, 65536):
                        break
                except BlockingIOError:
                    break
        self.framer.buffer.clear()
        self.records.clear()
        self.pending = None
        self.expected = None
        self.observed_generation = self.timing.tap_generation

    def _invalidate(self):
        self.timing.tap_reset()
        self.observed_generation = self.timing.tap_generation
        self.expected = None
        return StreamInvalidated(cause=InvalidationCause.UNKNOWN, known_lost_samples=None)

    def _mode(self, mode, reason):
        if mode == self.mode:
            if mode == "pipe fallback" and not self.reported_fallback:
                log.info("AirPlay audio source: %s (%s)", mode, reason)
                self.reported_fallback = True
            return None
        self.mode = mode
        self.reported_fallback = mode == "pipe fallback"
        with self.timing.lock:
            self.timing.tap_source = mode
            self.timing.tap_leads.clear()
        log.info("AirPlay audio source: %s (%s)", mode, reason)
        return self._invalidate()

    def read(self):
        now = self.clock()
        if self.observed_generation != self.timing.tap_generation:
            # The sole metadata reader can cancel output even if a tap marker was dropped.
            self.discard_pending()
            self.pending = None
            self.expected = None
            self.observed_generation = self.timing.tap_generation
            return StreamInvalidated(cause=InvalidationCause.UNKNOWN, known_lost_samples=None)
        if self.pending is not None:
            result, self.pending = self.pending, None
            return result
        if now - self.open_attempt >= 1:
            self.open_attempt = now
            if self.fd is not None:
                try:
                    current, opened = os.stat(self.path), os.fstat(self.fd)
                    changed = (current.st_dev, current.st_ino) != (
                        opened.st_dev,
                        opened.st_ino,
                    ) or not stat.S_ISFIFO(current.st_mode)
                except OSError:
                    changed = True
                if changed:
                    os.close(self.fd)
                    self.fd = None
                    self.records.clear()
                    self.framer.buffer.clear()
            if self.fd is None:
                self._open_tap()
        malformed = False
        if self.fd is not None and not self.records:
            try:
                raw = os.read(self.fd, 65536)
                self.records.extend(self.framer.feed(raw))
            except BlockingIOError:
                pass
            except (OSError, ValueError):
                malformed = True
                self.records.clear()
                self.framer.buffer.clear()
        if malformed:
            invalidation = self._mode("pipe fallback", "malformed tap record")
            if invalidation:
                return invalidation
        if self.records:
            record = self.records.popleft()
            if self.wire_generation is not None:
                delta = ((record.generation - self.wire_generation + 2**31) % 2**32) - 2**31
                if delta < 0:
                    return TemporarilyNoData()  # a delayed record cannot undo a flush
            with self.timing.lock:
                self.timing.tap_drops = record.drops
            if record.flags & OUT_OF_ORDER:
                return TemporarilyNoData()  # retransmits cannot rewind the analysis timeline
            invalid = self.wire_generation != record.generation or record.flags & (
                FLUSH | PAUSE | RESUME | DISCONTINUITY
            )
            self.wire_generation = record.generation
            if record.flags & PAUSE:
                self.paused = True
            if record.flags & RESUME:
                self.paused = False
                self.timing.tap_paused = False
            if invalid:
                self.records.appendleft(
                    TapRecord(
                        0,
                        record.rtp,
                        record.frames,
                        record.generation,
                        record.play_ns,
                        record.raw_ns,
                        record.mono_ns,
                        record.drops,
                        record.pcm,
                    )
                ) if record.frames else None
                return self._invalidate()
            if not record.frames or self.paused or self.timing.tap_paused:
                return TemporarilyNoData()
            distance = (
                (record.rtp - (self.expected if self.expected is not None else record.rtp) + 2**31)
                % 2**32
            ) - 2**31
            if self.expected is not None and distance < 0:
                return TemporarilyNoData()
            if self.expected is not None and distance > 0:
                self.records.appendleft(record)
                return self._invalidate()
            if record.mono_ns / 1e9 - now > 0.1:
                transition = self._mode("pipe fallback", "malformed tap clock pair")
                return transition or self.pipe.read()
            if now - record.mono_ns / 1e9 > 1:
                self.records.clear()
                transition = self._mode("pipe fallback", "tap records are over 1 s old")
                return transition or self.pipe.read()
            play = record.play_time
            # Receipt includes any FIFO residence: slow consumers cannot overclaim lead.
            self.last_record = now
            transition = self._mode("early tap", "timestamped PCM available")
            self.expected = (record.rtp + record.frames) % 2**32
            self.timing.arrival(record.frames, now)
            self.timing.tap_arrival(play - now, record.drops)
            # Drain through the same regular reader; never run two analysis paths.
            self.pipe.discard_pending()
            samples = (
                np.frombuffer(record.pcm, dtype="<i2").reshape(-1, 2).astype(np.float32) / 32768
            )
            result = DataResult(
                DecodedSourceFrame(
                    samples,
                    44100,
                    2,
                    "airplay:early",
                    None,
                    bool(np.any(np.abs(samples) >= 1)),
                    time.time_ns(),
                    now,
                    play,
                    self.timing.tap_generation,
                )
            )
            if transition:
                self.pending = result
                return transition
            return result
        if (
            self.mode == "early tap"
            and self.last_record is not None
            and now - self.last_record <= 1
        ):
            self.pipe.discard_pending()
            return TemporarilyNoData()
        transition = self._mode("pipe fallback", "tap missing or stale for more than 1 s")
        if transition:
            return transition
        return self.pipe.read()


class SceneSchedule:
    """Bounded target-time queue; each output tick sends only the newest due scene."""

    def __init__(self, capacity=1000):
        self.queue = []
        self.sequence = 0
        self.capacity = capacity
        self.generation = None

    def reset(self, generation):
        if generation != self.generation:
            self.queue.clear()
            self.generation = generation

    def add(self, scene, play, ready, generation, trim_ms=0, provenance=None):
        self.reset(generation)
        self.sequence += 1
        heapq.heappush(
            self.queue, (max(ready, play + trim_ms / 1000), self.sequence, scene, provenance)
        )
        if len(self.queue) > self.capacity:
            heapq.heappop(self.queue)

    def due(self, now, generation):
        self.reset(generation)
        result = None
        while self.queue and self.queue[0][0] <= now:
            _, _, scene, provenance = heapq.heappop(self.queue)
            result = scene, provenance
        return result
