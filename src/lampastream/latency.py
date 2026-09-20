"""LatencyProbe implementations for the LampaStream output delay subsystem.

NoLatencyProbe    — always returns 0; for local squeezelite players.
FixedLatencyProbe — returns a configured constant; for AirPlay and any other
                    player where the delay is negotiated and stable.

UpnpPositionProbe (step 3) will be added here to handle the Sonos case where
the offset is not negotiated and may drift with WiFi conditions.
"""

from __future__ import annotations


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
