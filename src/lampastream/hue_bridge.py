"""Bridge pairing and Entertainment Area discovery.

Thin wrapper around the `hue-entertainment` library (the same one that powers
Music Assistant's Hue Entertainment plugin) - LampaStream doesn't reimplement any
DTLS/HueStream protocol details itself.

All method signatures here were verified against the installed library
(introspected with `inspect`), not guessed from documentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from hue_entertainment import HueEntertainmentAPI, discover_bridges

from .models import BridgeConfig


@dataclass
class DiscoveredBridge:
    host: str
    name: str
    bridge_id: str


@dataclass
class EntertainmentAreaInfo:
    id: str
    name: str
    light_count: int


async def find_bridges(timeout: float = 5.0) -> list[DiscoveredBridge]:
    """mDNS discovery of Hue bridges on the LAN."""
    found = await discover_bridges(timeout=timeout)
    return [DiscoveredBridge(host=b.host, name=b.name, bridge_id=b.id) for b in found]


async def pair(host: str, bridge_name: str = "Hue Bridge") -> BridgeConfig:
    """Pair with a bridge.

    The bridge's physical link button must be pressed within the last ~30
    seconds before calling this, exactly like the official Hue app's
    pairing flow. Retries internally until the button is pressed or it
    times out.
    """
    api = HueEntertainmentAPI(host)
    try:
        creds = await api.pair(device_type="lampastream#lms")
    finally:
        await api.close()
    return BridgeConfig(
        name=bridge_name,
        host=host,
        app_key=creds["username"],
        client_key=creds["clientkey"],
    )


async def list_entertainment_areas(bridge: BridgeConfig) -> list[EntertainmentAreaInfo]:
    api = HueEntertainmentAPI(bridge.host, app_key=bridge.app_key)
    try:
        areas = await api.get_entertainment_areas()
    finally:
        await api.close()
    return [
        EntertainmentAreaInfo(id=a.id, name=a.name, light_count=len(a.channels))
        for a in areas
    ]
