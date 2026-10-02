"""Read-only AirPlay timing tap and bounded local-processing estimator.

The only FIFO readers remain the PCM source and metadata source. The diagnostic
API copies numbers/events, never PCM, and never attaches a second FIFO reader.
"""

from __future__ import annotations

import math
import re
import statistics
import threading
import time
from collections import deque

from .latency import latency_status

SAMPLE_RATE = 44100
PACING_TOLERANCE_MS = 20
MAX_GAP_MS = 100
RATE_TOLERANCE = 0.05
WARMUP_WINDOWS = 3


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


class CadenceCheck:
    """Single-owner monitor; TimingDiagnostics provides the cross-thread lock.

    Startup lead-in, flush and resume reset the window. Three complete seconds
    must pass before steady pacing can be claimed; faults invalidate it at once.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.arrivals = deque(maxlen=1024)
        self.jitter = deque(maxlen=512)
        self.windows = deque(maxlen=7)
        self.start = None
        self.previous = None
        self.previous_frames = 0
        self.window_frames = 0
        self.window_start = None
        self.largest_gap = 0.0
        self.largest_burst = 0

    def observe(self, frames, now):
        if frames <= 0 or not math.isfinite(now):
            return
        if self.start is None:
            self.start = self.window_start = now
        if self.previous is not None:
            gap = now - self.previous
            self.largest_gap = max(self.largest_gap, gap)
            self.jitter.append(abs(gap - self.previous_frames / SAMPLE_RATE) * 1000)
        self.previous, self.previous_frames = now, frames
        self.largest_burst = max(self.largest_burst, frames)
        while now - self.window_start >= 1:
            self.windows.append(
                {"start_monotonic": self.window_start, "frames_per_second": self.window_frames}
            )
            self.window_start += 1
            self.window_frames = 0
        self.window_frames += frames
        self.arrivals.append((now, frames))

    def status(self, now):
        recent = [(t, n) for t, n in self.arrivals if now - t <= 3]
        gaps = [b[0] - a[0] for a, b in zip(recent, recent[1:], strict=False)]
        gap = max([now - self.previous if self.previous is not None else 0, *gaps])
        bursts = 0
        cluster_start, cluster_frames = None, 0
        for stamp, frames in recent:
            if cluster_start is None or stamp - cluster_start > 0.001:
                cluster_start, cluster_frames = stamp, 0
            cluster_frames += frames
            bursts = max(bursts, cluster_frames)
        self.largest_burst = max(self.largest_burst, bursts)
        jitter = [
            abs((b[0] - a[0]) - a[1] / SAMPLE_RATE) * 1000
            for a, b in zip(recent, recent[1:], strict=False)
        ]
        recent_windows = list(self.windows)[-WARMUP_WINDOWS:]
        enough = len(recent_windows) >= WARMUP_WINDOWS
        reason = None
        if gap * 1000 > MAX_GAP_MS:
            reason = "Audio delivery stalled"
        elif bursts / SAMPLE_RATE * 1000 > MAX_GAP_MS:
            reason = "Audio arrived in a burst"
        elif enough and any(
            abs(w["frames_per_second"] / SAMPLE_RATE - 1) > RATE_TOLERANCE for w in recent_windows
        ):
            reason = "Audio is not arriving at a steady real-time rate"
        elif enough and (percentile(jitter, 0.95) or 0) > PACING_TOLERANCE_MS:
            reason = "Audio arrival timing is too uneven"
        return {
            "state": "unpaced" if reason else "steady" if enough else "measuring",
            "reason": reason,
            "windows": list(self.windows),
            "jitter_ms": {
                "p50": percentile(jitter, 0.5),
                "p95": percentile(jitter, 0.95),
                "max": max(jitter, default=0),
            },
            "largest_gap_ms": max(self.largest_gap, gap) * 1000,
            "largest_burst_frames": self.largest_burst,
            "tolerance_ms": PACING_TOLERANCE_MS,
        }


class ProcessingWindow:
    def __init__(self):
        self.samples = deque(maxlen=7)
        self.outlier_streak = 0

    def accept(self, milliseconds, stamp):
        if not math.isfinite(milliseconds) or milliseconds < 0:
            return False
        if self.samples and abs(milliseconds - self.median()) > 400:
            self.outlier_streak += 1
            if self.outlier_streak < 3:
                return False
            # A sustained change is a new regime, not a permanently rejected outlier.
            self.samples.clear()
        self.outlier_streak = 0
        self.samples.append((milliseconds, stamp))
        return True

    def median(self):
        return statistics.median(n for n, _ in self.samples) if self.samples else None

    def precision(self):
        median = self.median()
        return (
            round(1.4826 * statistics.median(abs(n - median) for n, _ in self.samples))
            if median is not None
            else None
        )


class TimingDiagnostics:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.events = deque(maxlen=4096)
        self.sequence = 0
        self.generation = 0
        self.active = False
        self.playback_since = None
        self.playback_paused = False
        self.last_arrival = None
        self.cadence = CadenceCheck()
        self.processing_window = ProcessingWindow()
        self.processing_sequence = 0

    def _record(self, kind, now, **values):
        self.sequence += 1
        self.events.append(
            dict(
                sequence=self.sequence,
                kind=kind,
                monotonic=now,
                generation=self.generation,
                **values,
            )
        )

    def reset(self, reason="session"):
        with self.lock:
            self.generation += 1
            self.active = False
            self.playback_since = None
            self.playback_paused = False
            self.last_arrival = None
            self.cadence.reset()
            self.processing_window = ProcessingWindow()
            self._record("reset", self.clock(), reason=reason)

    def arrival(self, frames, now):
        with self.lock:
            self.active = True
            self.last_arrival = now
            self.cadence.observe(frames, now)
            self._record("arrival", now, frames=frames)

    def metadata(self, code, payload):
        if code not in {
            "prgr",
            "pffr",
            "phb0",
            "phbt",
            "pbeg",
            "pres",
            "prsm",
            "paus",
            "pfls",
            "pend",
            "aend",
            "mdst",
            "mden",
        }:
            return
        now = self.clock()
        with self.lock:
            last = self.cadence.previous
            if code in {"pbeg", "pres", "prsm"}:
                self.playback_since = now
                self.playback_paused = False
            elif (code in {"phb0", "phbt"} and not self.playback_paused
                  and self.playback_since is None and re.fullmatch(r"\d+/\d+", payload)):
                self.playback_since = now
            elif code in {"paus", "pfls", "pend", "aend"}:
                self.playback_since = None
                self.playback_paused = True
            if code in {"pbeg", "phb0", "pres", "paus", "pfls", "pend", "aend"}:
                self.generation += 1
                self.cadence.reset()
                self.processing_window = ProcessingWindow()
                self.active = code in {"pbeg", "phb0", "pres"}
            self._record(
                "metadata",
                now,
                code=code,
                payload=payload[:256],
                local_raw_ns=time.clock_gettime_ns(
                    getattr(time, "CLOCK_MONOTONIC_RAW", time.CLOCK_MONOTONIC)
                ),
                since_arrival_ms=(now - last) * 1000 if last is not None else None,
            )

    def ended(self):
        with self.lock:
            if self.active:
                self.active = False
                self._record("end", self.clock())

    def processing(self, received, ready, sent):
        """Exclude the intentional output-delay hold, preventing feedback.

        Start is the pipe read, end is HueDriver.send returning. Queue residence
        from scene-ready to send-start is subtracted, not counted as processing.
        """
        now = self.clock()
        held_ms = max(0, sent - ready) * 1000
        p = max(0, (now - received) * 1000 - held_ms)
        with self.lock:
            if not self.active or received < (self.cadence.start or 0):
                return
            accepted = self.processing_window.accept(p, time.time())
            if accepted:
                self.processing_sequence += 1
            self._record(
                "processing",
                now,
                processing_ms=p,
                delay_hold_ms=held_ms,
                received_monotonic=received,
                accepted=accepted,
            )

    def snapshot(self, after=0):
        with self.lock:
            events = [dict(e) for e in self.events if e["sequence"] > after]
            samples = list(self.processing_window.samples)
            return {
                "sequence": self.sequence,
                "generation": self.generation,
                "active": self.active,
                "playback_since": self.playback_since,
                "last_arrival": self.last_arrival,
                "stalled_for_s": (
                    max(
                        0,
                        self.clock()
                        - max(self.playback_since, self.last_arrival or self.playback_since),
                    )
                    if self.playback_since is not None
                    else 0
                ),
                "pacing": self.cadence.status(self.clock()),
                "median_processing_ms": (
                    round(self.processing_window.median(), 3) if samples else None
                ),
                "precision_ms": self.processing_window.precision(),
                "sample_count": len(samples),
                "processing_sequence": self.processing_sequence,
                "samples": [{"processing_ms": round(n, 3), "timestamp": t} for n, t in samples],
                "events": events,
                "dropped": bool(self.events and after and after < self.events[0]["sequence"] - 1),
            }


class AirPlayAutoLatencyProbe:
    def __init__(self, config, diagnostics, margin, persist, *, clock=time.monotonic):
        self.config, self.diagnostics, self.margin = config, diagnostics, margin
        self.persist, self.clock = persist, clock
        self.delay = (
            max(0, config.measured_delay_ms + config.trim_ms)
            if config.measured_delay_ms is not None
            else config.fixed_delay_ms
        )
        if margin == 0:
            self.delay = max(0, config.trim_ms)
        self.first = True
        self.last_sequence = -1
        self.persisted_at = None
        self.state = "measuring"
        self.reason = None
        self.last_good = 0 if margin == 0 else config.measured_delay_ms

    async def start(self):
        pass

    async def stop(self):
        if self.last_good is not None:
            self.persist(self.last_good, time.time())

    def current_delay_ms(self):
        data = self.diagnostics.snapshot(after=self.diagnostics.sequence)
        self.reason = None
        if not data["active"]:
            self.state = "idle"
        elif self.margin is None:
            self.state, self.reason = "not measurable", "Early audio delivery is not verified"
        elif data["pacing"]["state"] == "unpaced":
            self.state, self.reason = "not measurable", data["pacing"]["reason"]
        elif data["pacing"]["state"] != "steady" or data["sample_count"] < 3:
            self.state = "measuring"
        elif self.margin != 0 and data["median_processing_ms"] > self.margin:
            self.state, self.reason = (
                "not measurable",
                "Processing takes longer than early delivery",
            )
        else:
            self.state = "lagging" if self.margin == 0 else "stable"
            if data["processing_sequence"] != self.last_sequence:
                self.last_sequence = data["processing_sequence"]
                measured = max(0, round(self.margin - data["median_processing_ms"]))
                target = max(0, measured + self.config.trim_ms)
                self.delay = (
                    target if self.first else self.delay + max(-50, min(50, target - self.delay))
                )
                self.first = False
                self.last_good = measured
                if self.persisted_at is None or self.clock() - self.persisted_at >= 15:
                    self.persist(measured, time.time())
                    self.persisted_at = self.clock()
        if self.reason:
            self.delay = self.config.fixed_delay_ms
        return self.delay

    def status(self):
        self.current_delay_ms()
        data = self.diagnostics.snapshot(after=self.diagnostics.sequence)
        result = latency_status(
            self.config,
            state=self.state,
            delay=self.delay,
            strategy="fixed" if self.reason else "auto",
            reason=self.reason,
        )
        result.update(
            source="airplay",
            lag_ms=(
                round(data["median_processing_ms"] + self.delay)
                if self.margin == 0 and data["median_processing_ms"] is not None
                else None
            ),
            early_delivery_ms=self.margin,
            median_processing_ms=data["median_processing_ms"],
            sample_count=data["sample_count"],
            precision_ms=data["precision_ms"],
            samples=data["samples"],
            last_sample_time=data["samples"][-1]["timestamp"] if data["samples"] else None,
            pacing=data["pacing"],
        )
        return result
