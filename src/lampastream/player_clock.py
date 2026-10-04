"""Optional YNPT clock carried inside the SHM v1 PCM seqlock."""
import struct
from dataclasses import dataclass

TIMING_OFFSET = 32888
TIMING_SIZE = 64
TIMING_FORMAT = struct.Struct('<4sH2xQQIIIQq12x')
FLUSH, PAUSE, RESUME, DISCONTINUITY = 1, 2, 4, 8
SYNC_PAUSE, SYNC_SKIP = 64, 128


@dataclass(frozen=True)
class PlayerClock:
    anchor_abs_frame: int
    anchor_play_mono_ns: int
    rate_milli_hz: int
    event_seq: int
    event_flags: int
    event_abs_frame: int
    event_value: int

    def at(self, frame: int) -> float:
        return self.anchor_play_mono_ns / 1e9 + (
            frame - self.anchor_abs_frame) * 1000 / self.rate_milli_hz

    @classmethod
    def read(cls, mapping, flags):
        if not flags & 1 or len(mapping) < TIMING_OFFSET + TIMING_SIZE:
            return None
        magic, version, *fields = TIMING_FORMAT.unpack_from(mapping, TIMING_OFFSET)
        if magic != b'YNPT' or version != 1 or fields[1] == 0 or fields[2] == 0:
            return None
        return cls(*fields)
