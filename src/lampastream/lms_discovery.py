"""LMS server discovery via the Slim protocol UDP broadcast.

Protocol reference: Slim/Networking/Discovery.pm in the LMS source tree
and the Rust implementation in mprisqueeze.

The client sends a UDP broadcast to port 3483 with the payload:
    b"eNAME\\0JSON\\0UUID\\0VERS\\0"

The 'e' is the discovery request opcode; each subsequent null-terminated
token names a field the client wants back.  The server replies with a
tag-length-value (TLV) frame:
    - 1 byte:  uppercase request opcode echo ('E')
    - repeated: 4-byte ASCII tag, 1-byte value length, <length>-byte UTF-8 value

Known tags:
    NAME  server hostname
    JSON  web / JSON-RPC port (usually 9000; NOT the slimproto port 3483)
    UUID  server UUID
    VERS  LMS version string

The responding server's IP address comes from the UDP sender address, not
from the payload.  Discovery only works within the same broadcast domain
(subnet); it will not cross a router.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass

_DISCOVERY_PORT = 3483
_REQUEST_PAYLOAD = b"eNAME\0JSON\0UUID\0VERS\0"


@dataclass
class DiscoveredLMS:
    """One Lyrion Music Server found on the local network."""

    host: str       # IP address of the responding server (from UDP sender addr)
    name: str       # server hostname (NAME tag)
    json_port: int  # web / JSON-RPC port (JSON tag; usually 9000)
    uuid: str       # server UUID (UUID tag)
    version: str    # LMS version string (VERS tag)


def _parse_tlv_response(data: bytes) -> dict[str, str]:
    """Parse a TLV discovery response into a {tag: value} dict.

    data[0] is the echoed request opcode ('E'); the TLV fields start at
    data[1].  Returns an empty dict for data that is too short or malformed;
    never raises.
    """
    if len(data) < 1:
        return {}
    pos = 1  # skip the echoed opcode byte
    result: dict[str, str] = {}
    while pos + 5 <= len(data):
        tag = data[pos : pos + 4].decode("ascii", errors="replace")
        length = data[pos + 4]
        value = data[pos + 5 : pos + 5 + length].decode("utf-8", errors="replace")
        result[tag] = value
        pos += 5 + length
    return result


def _discover_blocking(timeout: float) -> list[DiscoveredLMS]:
    """Blocking UDP discovery; run in a thread via run_in_executor."""
    results: list[DiscoveredLMS] = []
    seen: set[str] = set()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        try:
            sock.sendto(_REQUEST_PAYLOAD, ("<broadcast>", _DISCOVERY_PORT))
        except OSError:
            return results  # no network interface, or broadcast blocked

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(1024)
            except (TimeoutError, OSError):
                break

            host = addr[0]
            if host in seen:
                continue
            seen.add(host)

            fields = _parse_tlv_response(data)
            try:
                json_port = int(fields.get("JSON", "9000"))
            except ValueError:
                json_port = 9000

            results.append(
                DiscoveredLMS(
                    host=host,
                    name=fields.get("NAME", host),
                    json_port=json_port,
                    uuid=fields.get("UUID", ""),
                    version=fields.get("VERS", ""),
                )
            )

    return results


async def discover_lms(timeout: float = 3.0) -> list[DiscoveredLMS]:
    """Discover Lyrion Music Servers on the local network.

    Sends a UDP broadcast and collects responses for *timeout* seconds.
    Returns a (possibly empty) list of DiscoveredLMS.  Only servers on
    the same broadcast domain (subnet) will respond.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _discover_blocking, timeout)
