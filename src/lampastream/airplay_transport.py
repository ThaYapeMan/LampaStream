"""DACP transport adapter owned by the AirPlay player, independent of rendering."""
from __future__ import annotations

import asyncio
import re
import time

import httpx

ACTIONS = {"play": "play", "pause": "pause", "toggle": "playpause",
           "next": "nextitem", "previous": "previtem"}


async def resolve_dacp(identifier):
    from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf
    zeroconf = AsyncZeroconf()
    try:
        name = f"iTunes_Ctrl_{identifier}._dacp._tcp.local."
        info = AsyncServiceInfo("_dacp._tcp.local.", name)
        if await info.async_request(zeroconf.zeroconf, 1500):
            addresses = info.parsed_scoped_addresses()
            if addresses:
                return addresses[0], info.port
    finally:
        await zeroconf.async_close()
    raise OSError("AirPlay sender is gone or does not advertise remote control")


class DacpTransport:
    def __init__(self, resolver=resolve_dacp, *, clock=time.monotonic):
        self.identifier = self.active_remote = None
        self.endpoint = None
        self.expires = 0.
        self.reason = "Waiting for the AirPlay sender's remote-control announcement"
        self.resolver, self.clock = resolver, clock
        self.task = None

    def update(self, code, data):
        if code not in {"daid", "acre"}:
            return
        field, pattern = (("identifier", r"[0-9A-Fa-f]{1,16}") if code == "daid"
                          else ("active_remote", r"[0-9]{1,10}"))
        value = data if re.fullmatch(pattern, data) else None
        if value != getattr(self, field):
            setattr(self, field, value)
            self.endpoint, self.expires = None, 0.

    def reset(self):
        self.identifier = self.active_remote = self.endpoint = None
        self.expires = 0.
        self.reason = "Waiting for the AirPlay sender's remote-control announcement"

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="airplay-dacp")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.reset()

    @property
    def capability(self):
        available = bool(self.identifier and self.active_remote and self.endpoint
                         and self.clock() < self.expires)
        reason = self.reason or "Checking AirPlay sender availability"
        return dict(available=available, actions=list(ACTIONS),
                    reason=None if available else reason,
                    target_id=self.identifier, target_name="AirPlay sender")

    async def refresh(self):
        identity = self.identifier, self.active_remote
        if not all(identity):
            return
        try:
            endpoint = await self.resolver(identity[0])
            if identity == (self.identifier, self.active_remote):
                self.endpoint, self.expires = endpoint, self.clock() + 5
                self.reason = None
        except OSError as exc:
            self.endpoint, self.expires = None, 0.
            self.reason = str(exc)

    async def _run(self):
        while True:
            if self.clock() >= self.expires - 1:
                await self.refresh()
            await asyncio.sleep(.5)

    async def control(self, action):
        if action not in ACTIONS:
            raise RuntimeError("This AirPlay sender does not support that transport action")
        identity = self.identifier, self.active_remote
        if not self.capability['available']:
            await self.refresh()
        if not self.capability['available'] or identity != (self.identifier, self.active_remote):
            raise RuntimeError(self.reason or "AirPlay sender changed")
        address, port = self.endpoint
        host = f"[{address}]" if ':' in address else address
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(f"http://{host}:{port}/ctrl-int/1/{ACTIONS[action]}",
                                            headers={"Active-Remote": identity[1]})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            self.endpoint, self.expires = None, 0.
            self.reason = "AirPlay sender is unavailable or rejected remote control"
            raise OSError(self.reason) from exc
        return identity[0]
