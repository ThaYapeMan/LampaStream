"""Hue Entertainment output driver.

This is the only module in LampaStream that imports from hue_entertainment.
Everything Hue-specific lives here: LightColorCommand construction, the
EntertainmentSession lifecycle, and channel position fetching.

The OutputDriver pattern means effects never know about channel IDs or
transport details — they produce a Scene (colour as a function of position)
and HueDriver samples it at each registered light's location.

Single-stream constraint: the Hue bridge only supports one Entertainment
stream at a time per bridge.  PlayerManager enforces this at the session
level by calling deactivate() before each activate().  HueDriver itself
has no cross-instance guard; callers are responsible for the ordering.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from hue_entertainment import EntertainmentSession, HueEntertainmentAPI, LightColorCommand

from .hue_release import HueReleaseRest
from .models import BridgeConfig
from .types import Colour, Position, Scene

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration and channel info
# ---------------------------------------------------------------------------


@dataclass
class HueOutputConfig:
    """Groups the Hue-specific output fields that live on a Profile.

    The internal runtime Profile carries these as flat fields; PlayerManager
    assembles a HueOutputConfig at activation
    time rather than touching the Profile's serialisation.
    """

    bridge: BridgeConfig
    area_id: str
    area_name: str
    release_after_idle_s: int = 30
    on_release: str = "restore"


@dataclass
class ChannelInfo:
    """A single light channel with its spatial position.

    channel_id  — the Hue Entertainment channel_id used in LightColorCommand
    position    — normalised (x, y, z) from LightChannel.position; used by
                  spatial effects (waves, fireworks) to compute per-light
                  colour from a Scene.
    """

    channel_id: int
    position: Position


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp *v* to [lo, hi]."""
    return max(lo, min(hi, v))


async def get_channel_infos(bridge: BridgeConfig, area_id: str) -> list[ChannelInfo]:
    """Fetch channel IDs and normalised positions for one Entertainment Area.

    Replaces the old get_area_channel_ids() which only returned IDs.
    LightChannel.position is a tuple[float, float, float] (x, y, z) set
    when the area was configured in the Hue app; defaults to (0, 0, 0) for
    lights whose position was never set.

    The Hue Entertainment API specifies positions in the range -1.0…+1.0 per
    axis.  Each component is clamped to that range here so that effect code
    can rely on normalised coordinates without additional guards.
    """
    api = HueEntertainmentAPI(bridge.host, app_key=bridge.app_key)
    try:
        areas = await api.get_entertainment_areas()
    finally:
        await api.close()
    area = next((a for a in areas if a.id == area_id), None)
    if area is None:
        raise ValueError(f"Entertainment area {area_id!r} not found on bridge {bridge.host!r}")
    return [
        ChannelInfo(
            channel_id=ch.channel_id,
            position=Position(
                x=_clamp(ch.position[0]),
                y=_clamp(ch.position[1]),
                z=_clamp(ch.position[2]),
            ),
        )
        for ch in area.channels
    ]


# ---------------------------------------------------------------------------
# HueDriver — implements the Output protocol
# ---------------------------------------------------------------------------


class HueDriver:
    """Sends rendered Scenes to a Hue Entertainment Area over DTLS/UDP.

    Lifecycle:
        driver = HueDriver(config, channels)
        await driver.start()          # opens the DTLS stream
        driver.send(scene, t)         # called at 30 Hz by SyncEngine
        await driver.stop()           # releases lights using the coupling policy
        await driver.aclose()         # releases the connection object

    last_colours is updated on every send() call and exposed for the web UI
    preview (app.py WebSocket).  It contains one Colour per channel in the
    same order as the channels list passed to __init__.
    """

    def __init__(self, config: HueOutputConfig, channels: list[ChannelInfo]) -> None:
        self._config = config
        self._channels = channels
        self._session: EntertainmentSession | None = None
        self.last_colours: list[Colour] = []
        self._last_commands: list[LightColorCommand] = []
        self._active = False
        self._clock = time.monotonic
        self._local_failure_at = float("-inf")
        self._last_audio = self._clock()
        self._audio_token = None
        self._paused_since = None
        self._release_kind = None
        self._release_audio_token = None
        self._release_track = None
        self._release_playing = False
        self.transport = lambda: None
        self._rest = HueReleaseRest(config.bridge, config.area_id)
        self._lifecycle_lock = asyncio.Lock()
        self.output_generation = 0
        self._sleep = asyncio.sleep
        self._state = "failed"
        self._reason: str | None = "Light output is not active"
        self._owner: str | None = None
        self._health_task: asyncio.Task | None = None
        self._remote_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None

    @property
    def accepting_frames(self):
        return self._state == "streaming"

    @property
    def channels(self) -> list[ChannelInfo]:
        return self._channels

    @property
    def output_status(self) -> dict:
        if self._active and self._state == "streaming" and not self._session.is_streaming:
            return {"state": "reconnecting", "reason": "Light connection dropped"}
        return {"state": self._state, "reason": self._reason, **(
            {"release_kind": self._release_kind} if self._state == "released" else {})}

    async def start(self) -> None:
        """Own the stream for the entire coupling, including silence and pause."""
        b = self._config.bridge
        self._session = EntertainmentSession(b.host, b.app_key, b.client_key, idle_timeout=0)
        try:
            await self._connect(stop_others=True, capture=True)
        except BaseException:
            await self._session.aclose()
            self._session = None
            raise
        self._active = True
        if self._state == "reconnecting":
            self._request_recovery(self._reason)
        self._health_task = asyncio.create_task(self._monitor_local(), name="hue-output-health")
        self._remote_task = asyncio.create_task(self._monitor_remote(), name="hue-output-remote")

    async def _session_operation(self, operation, *args, **kwargs):
        # The library's handshake/disconnect executor must finish before teardown.
        task = asyncio.create_task(operation(*args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def _connect(self, *, stop_others=False, capture=False, check_remote=True) -> None:
        if capture and self._config.on_release != "leave":
            await self._rest.capture()
        await self._session_operation(self._session.start, self._config.area_id,
                                      stop_others=stop_others)
        # The library can resend only after it has received a first frame.
        commands = self._last_commands or [LightColorCommand(channel_id=c.channel_id)
                                          for c in self._channels]
        self._session.send(commands)
        self.output_generation += 1
        self._last_commands = []
        self._owner = None
        self._state, self._reason = "streaming", None
        self._release_kind = None
        # Capture the auth RID immediately after our own activation, not the app key.
        if check_remote:
            await self._check_remote()

    def observe_audio(self, token, present=True):
        if present and token != self._audio_token:
            self._audio_token = token
            self._last_audio = self._clock()

    async def _local_tick(self):
        now = self._clock()
        track = self.transport()
        paused = track is not None and not track.playing
        if paused:
            if self._paused_since is None:
                self._paused_since = now
        else:
            self._paused_since = None
        track_key = (track.title, track.artist) if track else None
        if self._state == "released":
            resumed = bool(track and track.playing and (
                track_key != self._release_track or not self._release_playing))
            fresh_audio = (self._audio_token != self._release_audio_token
                           and now - self._last_audio < max(2, self._config.release_after_idle_s))
            if self._release_kind == "idle" and not paused and (fresh_audio or resumed):
                # Consume metadata edges even if another controller blocks acquisition.
                # Fresh publications can retry, but stale audio cannot reclaim idle lights.
                self._release_track = track_key
                self._release_playing = bool(track and track.playing)
                await self.take_lights(explicit=False)
            return
        limit = self._config.release_after_idle_s
        idle_since = self._paused_since if paused else self._last_audio
        if limit and now - idle_since >= limit:
            # An app may have taken over since the last ten-second poll.
            await self._check_remote()
            if self._state == "released":
                return
            self._release_track = track_key
            self._release_playing = bool(track and track.playing)
            await self.release("Released while idle", idle=True)
        elif not self._session.is_streaming:
            self._local_failure_at = now
            self._request_recovery("Light connection dropped")

    async def _monitor_local(self) -> None:
        while self._active:
            await self._sleep(2)
            await self._local_tick()

    async def _disconnect(self, *, external=False):
        # The library has no local-only disconnect and its default REST client
        # can wait minutes. Separate local teardown from our bounded area stop.
        self._session._area_id = None
        await self._session_operation(self._session.stop)
        if not external:
            try:
                await self._rest.stop_area()
            except Exception:
                log.warning("Bridge light stream stop failed; local connection is closed")

    async def release(self, reason, *, idle=False, external=False, explicit=False):
        async with self._lifecycle_lock:
            if self._state == "released":
                return
            self._state, self._reason = "released", reason
            self._release_kind = ("explicit" if explicit else "external" if external
                                  else "idle" if idle else "explicit")
            self._release_audio_token = self._audio_token
            self.output_generation += 1
            self._last_commands = []
            task = self._recovery_task
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            try:
                await self._disconnect(external=True)
            except Exception:
                log.warning("Local light stream cleanup failed; ownership remains released")
            try:
                async with asyncio.timeout(10):
                    if not external:
                        try:
                            await self._rest.stop_area()
                        except Exception:
                            log.warning("Bridge light stream stop failed; "
                                        "ownership remains released")
                    await self._rest.finish(self._config.on_release, external=external)
            except Exception:
                log.warning("Light release REST budget exhausted; ownership remains released")
            log.info("Light output released: %s", reason)

    async def take_lights(self, *, explicit=True):
        connected = False
        async with self._lifecycle_lock:
            if not self._active or self._state != "released":
                return
            if not explicit:
                try:
                    if not await self._rest.available():
                        self._reason = "Another controller is using the lights"
                        return
                except Exception:
                    self._reason = "Cannot check whether the lights are available"
                    return
            self._state, self._reason = "reconnecting", "Connecting the lights"
            try:
                await self._connect(stop_others=explicit, capture=True, check_remote=False)
                self._last_audio = self._clock()
                connected = True
            except Exception:
                self._local_failure_at = self._clock()
                self._request_recovery("Could not connect the lights")
        if connected:
            # A remote release can acquire the lifecycle lock only after this
            # connection transaction has finished (the lock is not re-entrant).
            await self._check_remote()
            if self._state == "streaming":
                log.info("Light output re-acquired")

    async def _monitor_remote(self) -> None:
        while self._active:
            await self._sleep(10)
            if (self._state != "released"
                    and (self._recovery_task is None or self._recovery_task.done())):
                await self._check_remote()

    async def _check_remote(self) -> None:
        if self._state == "released":
            return
        try:
            status, owner = await asyncio.wait_for(self._session.remote_status(), timeout=5)
        except Exception as exc:
            if self._state != "failed":
                log.warning("Light output health check failed: %s", exc)
            self._state, self._reason = "failed", "Cannot verify the light connection"
            return
        if self._state == "released":
            return
        if status != "active" or self._owner is not None and owner != self._owner:
            if not self._session.is_streaming:
                self._local_failure_at = self._clock()
            if self._clock() - self._local_failure_at <= 15:
                self._request_recovery("Bridge ended the light stream" if status != "active"
                                       else "Another controller took over the lights")
            else:
                await self.release("Stopped from the Hue app or another controller", external=True)
        else:
            self._owner = owner
            if self._state == "failed":
                log.info("Light output health verification recovered")
            self._state, self._reason = "streaming", None
            self._release_kind = None

    def _request_recovery(self, reason: str) -> None:
        if self._state == "released":
            return
        self._state, self._reason = "reconnecting", reason
        if (not self._active or
                self._recovery_task is not None and not self._recovery_task.done()):
            return
        log.warning("Light output down: %s; reconnecting", reason)
        self._recovery_task = asyncio.create_task(self._recover(), name="hue-output-recovery")

    async def _recover(self) -> None:
        attempt = 0
        while self._active:
            delay = (1, 2, 5, 10)[min(attempt, 3)]
            await self._sleep(delay)
            if not self._active:
                return
            self._state = "reconnecting"
            try:
                await self._disconnect()
                await self._connect()
                if self._state == "reconnecting" or not self._session.is_streaming:
                    raise RuntimeError(self._reason or "Light connection is not streaming")
                if self._state == "failed":
                    log.info("Light output reconnected; awaiting bridge health verification")
                    return
            except Exception as exc:
                self._local_failure_at = self._clock()
                self._state, self._reason = "failed", "Could not reconnect the lights; retrying"
                log.warning("Light output reconnect failed (retry in %s s): %s",
                            (1, 2, 5, 10)[min(attempt + 1, 3)], exc)
                attempt += 1
            else:
                log.info("Light output recovered: streaming")
                return

    def send(self, scene: Scene, t: float) -> None:
        """Sample *scene* at each channel's position and send to the bridge.

        Converts Colour.to_16bit() values into LightColorCommands.  If start()
        has not been called yet (or after stop()/aclose()), this is a no-op.
        """
        if self._session is None or self._state != "streaming":
            return
        colours = [scene.color_at(ch.position, t) for ch in self._channels]
        self.last_colours = colours
        commands = [
            LightColorCommand(channel_id=ch.channel_id, red=r, green=g, blue=b)
            for ch, (r, g, b) in zip(self._channels, (c.to_16bit() for c in colours), strict=True)
        ]
        self._last_commands = commands
        try:
            self._session.send(commands)
        except Exception:
            self._local_failure_at = self._clock()
            self._request_recovery("Light connection dropped")

    async def stop(self) -> None:
        """Stop health/recovery ownership before ending the bridge stream."""
        self._active = False
        for attribute in ("_health_task", "_remote_task", "_recovery_task"):
            task = getattr(self, attribute)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                setattr(self, attribute, None)
        if self._session is not None and self._state != "released":
            await self.release("Stopped")

    async def aclose(self) -> None:
        """Release the connection and every task even after failed teardown."""
        try:
            await self.stop()
        finally:
            if self._session is not None:
                await self._session.aclose()
                self._session = None
