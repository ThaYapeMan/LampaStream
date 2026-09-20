"""Small standalone helpers with no other module dependencies."""

from __future__ import annotations

import random


def generate_locally_administered_mac() -> str:
    """A random MAC in the locally-administered range (02:xx:xx:xx:xx:xx).

    Locally-administered addresses are guaranteed to never collide with a
    real vendor-assigned MAC, which matters here since squeezelite's shared
    memory segment and LMS's player list are both keyed by this MAC.
    """
    octets = [0x02] + [random.randint(0x00, 0xFF) for _ in range(5)]
    return ":".join(f"{o:02x}" for o in octets)
