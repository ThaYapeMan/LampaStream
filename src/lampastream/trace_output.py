"""Offline-only Scene sink. No bridge, session, network or audio-device access."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .types import Colour, OutputCapabilities, Position, Scene


@dataclass(frozen=True)
class TraceChannel:
    channel_id: int
    position: Position


def load_room(path: str | Path) -> list[TraceChannel]:
    """Read channels in the same coordinate order as Hue ChannelInfo (x,y,z)."""
    data = json.loads(Path(path).read_text())
    rows = data["channels"] if isinstance(data, dict) else data
    channels = []
    for row in rows:
        position = row["position"]
        if isinstance(position, dict):
            position = [position[axis] for axis in ("x", "y", "z")]
        if len(position) != 3 or not all(math.isfinite(v) for v in position):
            raise ValueError("Room positions must contain three finite coordinates")
        identity = row["channel_id"]
        if type(identity) is not int or not 0 <= identity <= 255:
            raise ValueError("Room channel IDs must be integers in [0,255]")
        channels.append(TraceChannel(identity, Position(*position)))
    if not channels or len({c.channel_id for c in channels}) != len(channels):
        raise ValueError("Room needs nonempty, unique channel IDs")
    return channels


def load_capabilities(path: str | Path) -> OutputCapabilities:
    data = json.loads(Path(path).read_text())
    return OutputCapabilities(**data.get("capabilities", {})) if isinstance(data, dict) else (
        OutputCapabilities())


def wire_rgb(colour: Colour) -> tuple[int, int, int]:
    """Match hue-entertainment 0.1.2 dtls.py, including its <=255 branch.

    The HueDriver first calls to_16bit(); the dependency reduces values >255
    by shifting, but passes values <=255 through. Each resulting byte is
    duplicated on the wire. Do not replace this with round(channel * 255).
    """
    return tuple(min(255, value >> 8) if value > 255 else value
                 for value in colour.to_16bit())


class TraceOutput:
    """Output protocol implementation with Hue-like channels and no-op lifecycle."""

    def __init__(self, channels: list[TraceChannel], route: str = "normal",
                 capabilities: OutputCapabilities | None = None) -> None:
        self.capabilities = capabilities or OutputCapabilities()
        self.channels = channels
        self.route = route
        self.output_generation = 0
        self.accepting_frames = True
        self.rows: list[dict] = []
        self.last_colours: list[Colour] = []
        self._previous_send: float | None = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def send(self, scene: Scene, t: float) -> None:
        self.last_colours = [scene.color_at(channel.position, t) for channel in self.channels]
        interval = None if self._previous_send is None else (t - self._previous_send) * 1000
        send_id = len(self.rows) // len(self.channels) + 1
        for channel, colour in zip(self.channels, self.last_colours, strict=True):
            self.rows.append({
                "send_id": send_id, "virtual_time_s": t,
                "route": getattr(scene, "route", self.route),
                "generation": getattr(scene, "generation", self.output_generation),
                "scene_id": getattr(scene, "scene_id", ""),
                "channel_id": channel.channel_id,
                "r": colour.r, "g": colour.g, "b": colour.b,
                "r8": wire_rgb(colour)[0], "g8": wire_rgb(colour)[1],
                "b8": wire_rgb(colour)[2], "interval_ms": interval,
            })
        self._previous_send = t
