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
from dataclasses import dataclass

from hue_entertainment import EntertainmentSession, HueEntertainmentAPI, LightColorCommand

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
        await driver.stop()           # sends a final black frame, closes stream
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
        self._sleep = asyncio.sleep
        self._state = "failed"
        self._reason: str | None = "Light output is not active"
        self._owner: str | None = None
        self._health_task: asyncio.Task | None = None
        self._remote_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None

    @property
    def channels(self) -> list[ChannelInfo]:
        return self._channels

    @property
    def output_status(self) -> dict:
        if self._active and self._state == "streaming" and not self._session.is_streaming:
            return {"state": "reconnecting", "reason": "Light connection dropped"}
        return {"state": self._state, "reason": self._reason}

    async def start(self) -> None:
        """Own the stream for the entire coupling, including silence and pause."""
        b = self._config.bridge
        self._session = EntertainmentSession(b.host, b.app_key, b.client_key, idle_timeout=0)
        try:
            await self._connect()
        except BaseException:
            await self._session.aclose()
            self._session = None
            raise
        self._active = True
        if self._state == "reconnecting":
            self._request_recovery(self._reason)
        self._health_task = asyncio.create_task(self._monitor_local(), name="hue-output-health")
        self._remote_task = asyncio.create_task(self._monitor_remote(), name="hue-output-remote")

    async def _session_operation(self, operation, *args):
        # The library's handshake/disconnect executor must finish before teardown.
        task = asyncio.create_task(operation(*args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def _connect(self) -> None:
        await self._session_operation(self._session.start, self._config.area_id)
        # The library can resend only after it has received a first frame.
        commands = self._last_commands or [LightColorCommand(channel_id=c.channel_id)
                                          for c in self._channels]
        self._session.send(commands)
        self._owner = None
        self._state, self._reason = "streaming", None
        # Capture the auth RID immediately after our own activation, not the app key.
        await self._check_remote()

    async def _monitor_local(self) -> None:
        while self._active:
            await self._sleep(2)
            if not self._session.is_streaming:
                self._request_recovery("Light connection dropped")

    async def _monitor_remote(self) -> None:
        while self._active:
            await self._sleep(10)
            if self._recovery_task is None or self._recovery_task.done():
                await self._check_remote()

    async def _check_remote(self) -> None:
        try:
            status, owner = await asyncio.wait_for(self._session.remote_status(), timeout=5)
        except Exception as exc:
            if self._state != "failed":
                log.warning("Light output health check failed: %s", exc)
            self._state, self._reason = "failed", "Cannot verify the light connection"
            return
        if status != "active":
            self._request_recovery("Bridge ended the light stream")
        elif self._owner is not None and owner != self._owner:
            self._request_recovery("Another controller took over the lights")
        else:
            self._owner = owner
            if self._state == "failed":
                log.info("Light output health verification recovered")
            self._state, self._reason = "streaming", None

    def _request_recovery(self, reason: str) -> None:
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
                await self._session_operation(self._session.stop)
                await self._connect()
                if self._state == "reconnecting" or not self._session.is_streaming:
                    raise RuntimeError(self._reason or "Light connection is not streaming")
                if self._state == "failed":
                    log.info("Light output reconnected; awaiting bridge health verification")
                    return
            except Exception as exc:
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
        if self._session is None:
            return
        colours = [scene.color_at(ch.position, t) for ch in self._channels]
        self.last_colours = colours
        commands = [
            LightColorCommand(channel_id=ch.channel_id, red=r, green=g, blue=b)
            for ch, (r, g, b) in zip(self._channels, (c.to_16bit() for c in colours), strict=True)
        ]
        self._last_commands = commands
        self._session.send(commands)

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
        self._state, self._reason = "failed", "Light output is not active"
        if self._session is not None:
            await self._session.stop()

    async def aclose(self) -> None:
        """Release the connection and every task even after failed teardown."""
        try:
            await self.stop()
        finally:
            if self._session is not None:
                await self._session.aclose()
                self._session = None
