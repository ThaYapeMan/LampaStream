"""LatencyProbe implementations for the LampaStream output delay subsystem.

NoLatencyProbe    — always returns 0; for local LMS player players.
FixedLatencyProbe — returns a configured constant; for AirPlay and any other
                    player where the delay is negotiated and stable.

AutoLatencyProbe measures standard LMS positions for manually followed players.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import unquote


class NoLatencyProbe:
    """Zero-delay probe for local players or when no latency is configured."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def current_delay_ms(self) -> int:
        return 0


class FixedLatencyProbe:
    """Constant-delay probe for players with a negotiated, stable latency.

    Appropriate for AirPlay 1 (~2000 ms), AirPlay 2 (~500 ms), and any other
    player type where the offset is known and does not drift — the latency is
    a protocol guarantee maintained by clock synchronisation.
    """

    def __init__(self, delay_ms: int) -> None:
        self._delay_ms = delay_ms

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def current_delay_ms(self) -> int:
        return self._delay_ms


# Auto uses position queries only; track/transport eligibility comes from listen 1.


@dataclass(frozen=True)
class FollowPositionContext:
    connected: bool = False
    playing: bool = False
    same_track: bool = False
    track: int = 0
    transition: int = 0
    changed_at: float = 0.0


def latency_status(config, *, state="idle", strategy=None, delay=None, reason=None):
    return {
        "strategy": strategy or config.strategy,
        "applied_delay_ms": delay if delay is not None else (
            config.fixed_delay_ms if config.strategy == "fixed" else
            max(0, (config.measured_delay_ms or 0) + config.trim_ms)
            if config.strategy == "auto" else 0),
        "median_residual_ms": None, "player_delay_ms": None,
        "trim_ms": config.trim_ms, "sample_count": 0, "precision_ms": None,
        "last_sample_time": None, "samples": [], "state": state, "reason": reason,
    }


class AutoLatencyProbe:
    """Bounded, asynchronous LMS position sampling; the output getter never waits.

    All socket work is owned through cancellation. No status/URL/mode queries are
    made here, and the only possible seek is delegated to the own-player follower.
    """

    def __init__(self, config, follower, persist, preference_cache=None, *, clock=time.monotonic):
        self.config = config
        self.follower = follower
        self.persist = persist
        self.clock = clock
        self.cache = preference_cache if preference_cache is not None else {}
        self.raw_samples = deque(maxlen=9)
        self.rejected_samples = 0
        self.samples = deque(maxlen=7)
        self.sample_times = deque(maxlen=7)
        self.delay = max(0, (config.measured_delay_ms or 0) + config.trim_ms)
        self.player_delay = None
        self.last_sample = None
        self.next_sample = 0.0
        self.burst_end = 0.0
        self.context = None
        self.first = True
        self.realign_track = None
        self.order = False
        self.task = None
        self.stopping = False
        self.state = "idle"

    async def start(self):
        self.stopping = False
        self.task = asyncio.create_task(self._run(), name="lms-auto-latency")

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.state = "idle"

    def current_delay_ms(self):
        return self.delay

    def status(self):
        status = latency_status(self.config, state=self.state, delay=self.delay)
        status.update(
            median_residual_ms=(round(statistics.median(self.samples) * 1000)
                                if self.samples else None),
            player_delay_ms=self.player_delay, sample_count=len(self.samples),
            precision_ms=self.precision_ms(), last_sample_time=self.last_sample,
            samples=[{"residual_ms": round(value * 1000), "timestamp": stamp}
                     for value, stamp in zip(self.samples, self.sample_times, strict=True)],
        )
        return status

    def precision_ms(self):
        if not self.samples:
            return None
        median = statistics.median(self.samples)
        return round(1482.6 * statistics.median(abs(x - median) for x in self.samples))

    def eligible(self, context, now):
        if self.context is None or context.transition != self.context.transition:
            new_track = self.context is None or context.track != self.context.track
            self.context = context
            self.samples.clear()
            self.sample_times.clear()
            self.raw_samples.clear()
            self.rejected_samples = 0
            if new_track:
                self.first = True
            self.next_sample = context.changed_at + 5
            self.burst_end = self.next_sample + 30
        ready = (context.connected and context.playing and context.same_track
                 and now >= context.changed_at + 5)
        if not ready:
            self.state = "idle"
        elif self.first or len(self.samples) < 4:
            self.state = "measuring"
        return ready and now >= self.next_sample

    def accept(self, residual, now):
        finite = math.isfinite(residual)
        stamp = time.time()
        if finite:
            self.raw_samples.append((residual, stamp, now))
        median = (statistics.median(value for value, _, _ in self.raw_samples)
                  if self.raw_samples else None)
        inliers = [(value, timestamp, sampled_at)
                   for value, timestamp, sampled_at in self.raw_samples
                   if abs(value - median) <= .060 + 1e-12]
        accepted = finite and abs(residual - median) <= .060 + 1e-12
        reason = ("within 60 ms of window median" if accepted else
                  "non-finite residual" if not finite else "outside 60 ms of window median")
        logging.getLogger(__name__).info(
            "latency sample: residual_ms=%s %s: %s; window_median_ms=%s inliers=%d",
            round(residual * 1000, 3) if finite else residual,
            "accepted" if accepted else "rejected", reason,
            round(median * 1000, 3) if median is not None else None, len(inliers))
        if not accepted:
            self.rejected_samples += 1
            if self.rejected_samples == 3:
                self.raw_samples.clear()
                self.samples.clear()
                self.sample_times.clear()
                self.rejected_samples = 0
                self.state = "measuring"
                self.next_sample = now + 3
                self.burst_end = now + 30
            return False
        self.rejected_samples = 0
        self.samples.clear()
        self.sample_times.clear()
        self.samples.extend(value for value, _, _ in inliers)
        self.sample_times.extend(timestamp for _, timestamp, _ in inliers)
        self.last_sample = stamp
        # A single candidate never sets or persists the delay. Four mutually
        # consistent values establish consensus, including after a window reset.
        ordered = sorted(value for value, _, _ in inliers)
        agreed = any(ordered[i + 3] - ordered[i] <= .060 + 1e-12
                     for i in range(len(ordered) - 3))
        if not agreed:
            return True
        # The median of a 9-sample, 15-second window otherwise trails a
        # 0.7 ms/s drift by 42 ms. Project the consensus to this sample's time
        # with a robust, bounded drift rate; never extrapolate a lone sample.
        slopes = [(b - a) / (tb - ta)
                  for i, (a, _, ta) in enumerate(inliers)
                  for b, _, tb in inliers[i + 1:] if tb - ta >= 15]
        rate = max(-.001, min(.001, statistics.median(slopes))) if slopes else 0
        estimate = statistics.median(value + rate * (now - sampled_at)
                                     for value, _, sampled_at in inliers)
        measured = round(estimate * 1000) + (self.player_delay or 0)
        target = max(0, measured + self.config.trim_ms)
        self.delay = target if self.first else self.delay + max(-50, min(50, target - self.delay))
        self.first = False
        self.state = "stable"
        self.persist(measured, self.last_sample)
        return True

    def _value(self, mac, command):
        from .lms_follower import _cli_exchange
        before = self.clock()
        raw = _cli_exchange(self.follower._host, self.follower._port, f"{mac} {command}\n")
        after = self.clock()
        parts = unquote(raw).split()
        if not parts:
            raise ValueError("Empty LMS reply")
        expected = [mac.lower(), *command.split()[:-1]]
        if [x.lower() for x in parts[:-1]] != [x.lower() for x in expected]:
            raise ValueError("Unexpected LMS position/preference reply")
        value = float(parts[-1])
        if not math.isfinite(value):
            raise ValueError("Non-finite LMS position/preference")
        return value, (before + after) / 2

    def _pair(self):
        own = self.follower._lampastream_mac
        followed = self.follower.target_mac
        macs = (followed, own) if self.order else (own, followed)
        context = self.follower.latency_context()
        values = {}
        for mac in macs:
            if (not context.playing or not context.connected or not context.same_track
                    or context != self.follower.latency_context() or self.stopping):
                raise ValueError("Playback changed during position pair")
            values[mac] = self._value(mac, "time ?")
        a, ta = values[own]
        b, tb = values[followed]
        if a < 0 or b < 0:
            raise ValueError("Negative LMS position")
        return a - b - (ta - tb)

    async def _owned_call(self, function, *args):
        worker = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                await worker
            except (OSError, ValueError):
                pass
            raise

    async def tick(self):
        now = self.clock()
        context = self.follower.latency_context()
        if not self.eligible(context, now):
            return
        mac = self.follower.target_mac
        if mac not in self.cache:
            try:
                value, _ = await self._owned_call(self._value, mac, "playerpref playDelay ?")
                self.cache[mac] = round(value)
            except (OSError, ValueError):
                self.cache[mac] = 0  # unsupported preference is harmless
        self.player_delay = self.cache[mac]
        # A notification may have arrived during the preference exchange.
        if context != self.follower.latency_context() or self.stopping:
            return
        try:
            residual = await self._owned_call(self._pair)
        finally:
            self.order = not self.order
            self.next_sample = self.clock() + (3 if now < self.burst_end else 15)
        if self.stopping or context != self.follower.latency_context():
            return
        self.accept(residual, now)
        if (now >= self.burst_end and len(self.samples) >= 4
                and statistics.median(self.samples) < -.3
                and self.realign_track != context.track):
            self.realign_track = context.track
            await self._owned_call(self.follower.realign_own_player, context.track)
            self.samples.clear()
            self.sample_times.clear()
            self.raw_samples.clear()
            self.rejected_samples = 0
            self.first = True
            self.state = "measuring"
            self.next_sample = self.clock() + 5
            self.burst_end = self.next_sample + 30

    async def _run(self):
        while not self.stopping:
            try:
                await self.tick()
            except (OSError, ValueError):
                self.state = "measuring"
            await asyncio.sleep(.25)
