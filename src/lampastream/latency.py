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
import threading
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
        "current_play": None, "applied_delay_play": None, "session_anchor_set": False,
        "strategy": strategy or config.strategy,
        "applied_delay_ms": delay if delay is not None else (
            config.fixed_delay_ms if config.strategy == "fixed" else
            (config.measured_delay_ms or 0) + config.trim_ms
            if config.strategy == "auto" else 0),
        "median_residual_ms": None, "player_delay_ms": None,
        "trim_ms": config.trim_ms, "sample_count": 0, "precision_ms": None,
        "last_sample_time": None, "samples": [], "state": state, "reason": reason,
    }


# Larger position differences describe misaligned tracks, not room latency.
MAX_AUTO_DELAY_MS = 5000


class AutoLatencyProbe:
    """Bounded, asynchronous LMS position sampling; the output getter never waits.

    All socket work is owned through cancellation. No status/URL/mode queries or
    seeks are made here; startup alignment belongs to the own-player follower.
    """

    def __init__(self, config, follower, persist, preference_cache=None, *,
                 clock=time.monotonic, position_clock=None, origin_known=None, warning=None):
        self.config = config
        self.follower = follower
        self.persist = persist
        self.clock = clock
        self.position_clock = position_clock
        self.origin_known = origin_known
        self.warning = warning
        self._exception_logged = False
        self._last_waiting_log = -math.inf
        self.applied_delay_play = None
        self.room_samples = deque(maxlen=9)
        self.startup_at = clock()
        self.startup_step_used = False
        self.mapping_generation = 0
        self.session_offset_ms = 0.
        self._anchored_room_ms = None
        self.session_anchor_at = None
        self.guard_residual_ms = None
        self._previous_guard_sample = None
        self._last_pair_at = None
        self._step_samples = []
        self._last_guard_log = -math.inf
        self.cache = preference_cache if preference_cache is not None else {}
        self.raw_samples = deque(maxlen=9)
        self.rejected_samples = 0
        self.samples = deque(maxlen=7)
        self.sample_times = deque(maxlen=7)
        measured = config.measured_delay_ms or 0
        if position_clock is not None and config.measurement_basis != 'lms-content-v2':
            measured = 0  # old saved values include the previous seek landing
        # Discard persisted estimates poisoned by the old same-URL reuse path.
        if not abs(measured) < MAX_AUTO_DELAY_MS:
            measured = 0
        self.delay = float(measured + config.trim_ms)
        self.target_delay = self.delay
        self.applied_at = clock()
        self._mapping_lock = threading.Lock()
        self.player_delay = None
        self.last_sample = None
        self.next_sample = 0.0
        self.burst_end = 0.0
        self.context = None
        self.first = True
        self.order = False
        self.task = None
        self.stopping = False
        self.state = "idle"
        self.reason = None

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

    smooth_corrections = True
    MAX_CORRECTION_MS_PER_SECOND = 5.

    def _advance(self, now):
        # Advance the old target before installing a new one. Repeated getters
        # or samples cannot buy extra correction, and idle time is not credit.
        elapsed = max(0., now - self.applied_at)
        bound = elapsed * self.MAX_CORRECTION_MS_PER_SECOND
        self.delay += max(-bound, min(bound, self.target_delay - self.delay))
        self.applied_at = max(self.applied_at, now)

    def current_delay_ms(self):
        with self._mapping_lock:
            self._advance(self.clock())
            return self.delay

    def status(self):
        applied = self.current_delay_ms()
        if (self.position_clock is not None and self.state == 'measuring'
                and self.session_anchor_at is not None
                and abs(self.target_delay - applied) < 15):
            self.state = 'stable'
        status = latency_status(self.config, state=self.state, delay=applied, reason=self.reason)
        status.update(
            median_residual_ms=(round(statistics.median(self.samples) * 1000)
                                if self.samples else None),
            player_delay_ms=self.player_delay, sample_count=len(self.samples),
            precision_ms=self.precision_ms(), last_sample_time=self.last_sample,
            samples=[{"residual_ms": round(value * 1000), "timestamp": stamp}
                     for value, stamp in zip(self.samples, self.sample_times, strict=True)],
        )
        if self.position_clock is not None:
            status.update(current_play=self.current_play,
                          applied_delay_play=self.applied_delay_play,
                          session_anchor_set=self.session_anchor_at is not None,
                          measurement_basis='lms-content-v2',
                          room_delay_ms=(self._anchored_room_ms - (self.player_delay or 0)
                                         if self.session_anchor_at is not None else None),
                          session_offset_ms=round(self.session_offset_ms, 3),
                          session_anchor_at=self.session_anchor_at,
                          guard_residual_ms=self.guard_residual_ms,
                          startup_step_used=self.startup_step_used)
        return status

    @property
    def current_play(self):
        return self.context.transition if self.context else None

    def precision_ms(self):
        if not self.samples:
            return None
        median = statistics.median(self.samples)
        return round(1482.6 * statistics.median(abs(x - median) for x in self.samples))

    def eligible(self, context, now):
        if self.context is None or context.transition != self.context.transition:
            initial = self.context is None
            new_track = initial or context.track != self.context.track
            self.context = context
            self._exception_logged = False
            self._last_waiting_log = context.changed_at
            self.reason = None
            if self.warning:
                self.warning(None)
            self.samples.clear()
            self.sample_times.clear()
            self.raw_samples.clear()
            self.room_samples.clear()
            self.rejected_samples = 0
            if self.position_clock is not None:
                self.session_anchor_at = None
                self.guard_residual_ms = None
                self._previous_guard_sample = None
                self._last_pair_at = None
                self._step_samples.clear()
            if new_track or self.position_clock is not None:
                self.first = True
                if not initial:
                    self.startup_at = context.changed_at
                self.startup_step_used = False
            self.next_sample = context.changed_at + (1 if self.position_clock else 5)
            self.burst_end = self.next_sample + 30
        ready = (context.connected and context.playing and context.same_track
                 and now >= context.changed_at + (1 if self.position_clock else 5))
        if not ready:
            self.state = "idle"
        elif self.first or len(self.samples) < 4:
            self.state = "measuring"
        return ready and now >= self.next_sample

    def _guard(self, sample, room_delay_ms, sample_interval):
        residual, _, now = sample
        self.guard_residual_ms = round(residual * 1000 - self.session_offset_ms, 3)
        previous = self._previous_guard_sample
        if self._step_samples:
            values = [entry[0][0] for entry in self._step_samples]
            if (now - self._step_samples[-1][0][2] > sample_interval
                    or max(*values, residual) - min(*values, residual) > .060 + 1e-12):
                self._step_samples.clear()
        if (self._step_samples or (previous is not None
                and 0 < now - previous[2] <= sample_interval
                and abs(residual - previous[0]) > .060 + 1e-12)):
            self._step_samples.append((sample, room_delay_ms))
            if len(self._step_samples) < 4:
                return False
            candidates, rooms = zip(*self._step_samples, strict=True)
            self._step_samples.clear()
            room_center = statistics.median(rooms)
            if (abs(statistics.median(item[0] for item in candidates) * 1000
                    - self.session_offset_ms) > 60 + 1e-9
                    and all(abs(room - room_center) <= 20 for room in rooms)):
                self.raw_samples.clear()
                self.raw_samples.extend(candidates[:-1])
                self.room_samples.clear()
                self.room_samples.extend(rooms[:-1])
                return True
        return None

    def _log_guard_slide(self, inliers, now):
        if now - self._last_guard_log < 60:
            return
        rates = [(b - a) * 1000 / (tb - ta)
                 for i, (a, _, ta) in enumerate(inliers)
                 for b, _, tb in inliers[i + 1:] if tb - ta >= 15]
        if rates and (rate := round(statistics.median(rates), 2)):
            logging.getLogger(__name__).info(
                "latency guard: residual slide %.2f ms/s against anchored session offset; "
                "not applied (not a rate reference)", rate)
            self._last_guard_log = now

    def accept(self, residual, now, room_delay_ms=None, *, sample_interval=15):
        finite = math.isfinite(residual)
        plausible = finite and abs(residual * 1000) < MAX_AUTO_DELAY_MS
        stamp = time.time()
        sample = residual, stamp, now
        native = self.position_clock is not None
        step = None
        if native:
            if room_delay_ms is None or not math.isfinite(room_delay_ms):
                logging.getLogger(__name__).info("latency sample: rejected: invalid room delay")
                self.state = "not measurable"
                self._step_samples.clear()
                return False
            if not plausible or abs(room_delay_ms) >= MAX_AUTO_DELAY_MS:
                logging.getLogger(__name__).info(
                    "latency sample: rejected: outside room-latency range")
                self._step_samples.clear()
                return False
            if self.session_anchor_at is not None:
                step = self._guard(sample, room_delay_ms, sample_interval)
                if step is False:
                    logging.getLogger(__name__).info("latency sample: held as a step candidate")
                    return True
        if plausible:
            self.raw_samples.append(sample)
        median = (statistics.median(value for value, _, _ in self.raw_samples)
                  if self.raw_samples else None)
        inliers = [(value, timestamp, sampled_at)
                   for value, timestamp, sampled_at in self.raw_samples
                   if abs(value - median) <= .060 + 1e-12]
        accepted = plausible and abs(residual - median) <= .060 + 1e-12
        reason = ("within 60 ms of window median" if accepted else
                  "non-finite residual" if not finite else
                  "position mismatch exceeds room-latency range" if not plausible else
                  "outside 60 ms of window median")
        logging.getLogger(__name__).info(
            "latency sample: residual_ms=%s %s: %s; window_median_ms=%s inliers=%d",
            round(residual * 1000, 3) if finite else residual,
            "accepted" if accepted else "rejected", reason,
            round(median * 1000, 3) if median is not None else None, len(inliers))
        if not accepted:
            self.rejected_samples += 1
            if self.rejected_samples == 3:
                self.raw_samples.clear()
                self.room_samples.clear()
                self.samples.clear()
                self.sample_times.clear()
                self.rejected_samples = 0
                self.state = "measuring"
                self.next_sample = now + 3
                self.burst_end = now + 30
            return False
        if native:
            self.room_samples.append(room_delay_ms)
            self._previous_guard_sample = sample
        self.rejected_samples = 0
        self.samples.clear()
        self.sample_times.clear()
        self.samples.extend(value for value, _, _ in inliers)
        self.sample_times.extend(timestamp for _, timestamp, _ in inliers)
        self.last_sample = stamp
        if native and self.session_anchor_at is not None and not step:
            self._log_guard_slide(inliers, now)
            with self._mapping_lock:
                self._advance(now)
                self.target_delay = self._anchored_room_ms + self.session_offset_ms + (
                    self.config.trim_ms)
                self.state = "stable" if abs(self.target_delay - self.delay) < 15 else "measuring"
            self.reason = None
            return True
        # A single candidate never sets or persists the delay. Four mutually
        # consistent values establish consensus, including after a window reset.
        ordered = sorted(value for value, _, _ in inliers)
        agreed = any(ordered[i + 3] - ordered[i] <= .060 + 1e-12
                     for i in range(len(ordered) - 3))
        if not agreed:
            return True
        if self.position_clock is not None:
            center = statistics.median(self.room_samples)
            room_inliers = [v for v in self.room_samples if abs(v-center) <= 20]
            if len(room_inliers) < 4:
                return True
        else:
            room_inliers = []
        if native:
            relative = statistics.median(value for value, _, _ in inliers) * 1000
            measured = round(statistics.median(room_inliers))
        else:
            # Legacy position mapping projects the consensus to this sample.
            slopes = [(b - a) / (tb - ta)
                      for i, (a, _, ta) in enumerate(inliers)
                      for b, _, tb in inliers[i + 1:] if tb - ta >= 15]
            rate = max(-.001, min(.001, statistics.median(slopes))) if slopes else 0
            measured = round(statistics.median(value + rate * (now - sampled_at)
                                               for value, _, sampled_at in inliers) * 1000)
        measured += self.player_delay or 0
        if not abs(measured) < MAX_AUTO_DELAY_MS:
            return False
        if native:
            self._anchored_room_ms = measured
            self.session_offset_ms = relative
            self.session_anchor_at = stamp
            self.applied_delay_play = self.current_play
            if self.warning:
                self.warning(None)
            self._last_guard_log = max(self._last_guard_log, now)
            self.guard_residual_ms = round(residual * 1000 - relative, 3)
        with self._mapping_lock:
            self._advance(now)
            self.target_delay = measured + self.session_offset_ms + self.config.trim_ms
            # Only the first anchor in a transport session may step directly.
            # Never reopen this allowance on a late remeasurement/window reset.
            startup = self.startup_at if self.startup_at is not None else self.applied_at
            if (native and self.first and not self.startup_step_used
                    and 0 <= now - startup <= 15):
                if abs(self.delay - self.target_delay) > 1e-9:
                    self.mapping_generation += 1
                self.delay = self.target_delay
                self.startup_step_used = True
        logging.getLogger(__name__).info(
            "latency mapping: track=%s applied_ms=%.3f target_ms=%.3f room_ms=%s "
            "session_ms=%.3f startup_step=%s limit_ms_per_s=5",
            self.context.track if self.context else None, self.delay, self.target_delay,
            measured, self.session_offset_ms, self.startup_step_used)
        self.first = False
        self.reason = None
        self.state = ("stable" if self.position_clock is None
                      or abs(self.target_delay - self.delay) < 15 else "measuring")
        self.config.measurement_basis = ('lms-content-v2'
                                         if self.position_clock is not None else None)
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
        residual = a - b - (ta - tb)
        if self.position_clock is None:
            return residual
        if self.origin_known is not None and self.origin_known() is False:
            raise ValueError("Stream origin unknown for this file")
        anchor = self.position_clock()
        if anchor is None or abs(self.clock() - anchor[1]) > .5:
            raise ValueError("No fresh absolute PCM content clock")
        position, played_at, content_start = anchor
        alignment = self.follower.position_alignment
        if alignment is None or alignment[0] != context.track:
            raise ValueError("No matching track-start alignment")
        # LMS labels the requested seek; FLAC actually starts at a frame boundary.
        # Keep that landing error in the session term, never in saved calibration.
        landing = alignment[1] - content_start
        if abs(landing) > .5:
            raise ValueError("Seek landing >500 ms: ambiguous absolute content origin")
        native_bias = (ta - played_at) + position - a
        room_delay = (native_bias + landing) * 1000
        logging.getLogger(__name__).info(
            "latency basis: track=%s own_follow_ms=%.3f requested_s=%.6f "
            "content_start_s=%.6f landing_ms=%.3f native_bias_ms=%.3f room_ms=%.3f",
            context.track, residual*1000, alignment[1], content_start,
            landing*1000, native_bias*1000, room_delay)
        return residual - landing, room_delay

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
        # Use the prior poll's scheduled deadline, including CLI exchange time.
        # The run loop checks readiness every quarter second.
        previous = self._last_pair_at
        sample_interval = self.next_sample + .25 - previous if previous is not None else 15
        try:
            residual = await self._owned_call(self._pair)
        except asyncio.CancelledError:
            if self.position_clock is not None:
                logging.getLogger(__name__).info("latency sample: rejected: probe stopped")
            raise
        except (OSError, ValueError):
            self._step_samples.clear()
            self._previous_guard_sample = None
            raise
        finally:
            self.order = not self.order
            interval = (1 if self.position_clock else 3) if now < self.burst_end else 15
            self.next_sample = self.clock() + interval
        if self.stopping or context != self.follower.latency_context():
            if self.position_clock is not None:
                logging.getLogger(__name__).info(
                    "latency sample: rejected: playback changed during position pair")
            return
        if self.position_clock is None:
            self.accept(residual, now)
        else:
            self._last_pair_at = now
            self.accept(residual[0], now, residual[1], sample_interval=sample_interval)

    def report_waiting(self):
        context = self.context
        if (self.position_clock is None or context is None or not context.playing
                or self.session_anchor_at is not None):
            return
        now = self.clock()
        since = max(0., now - context.changed_at)
        reason = self.reason or "Waiting for position consensus"
        if since >= 15 and self.warning:
            self.warning(reason)
        if now - self._last_waiting_log >= 10:
            alignment = self.follower.position_alignment
            logging.getLogger(__name__).info(
                "latency probe waiting: reason=%s track=%s seek_s=%s since_s=%.3f",
                reason, context.track, alignment[1] if alignment else None, since)
            self._last_waiting_log = now

    async def _run(self):
        while not self.stopping:
            try:
                await self.tick()
            except (OSError, ValueError) as error:
                self.state = ("measuring" if self.clock() - self.startup_at <= 15
                              else "not measurable")
                self.reason = str(error)
                if not self._exception_logged:
                    logging.getLogger(__name__).warning("latency probe: %s", error)
                    self._exception_logged = True
            self.report_waiting()
            await asyncio.sleep(.25)
