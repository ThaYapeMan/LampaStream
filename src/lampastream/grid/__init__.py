"""Source-independent, content-addressed beat grids."""
import math
from dataclasses import asdict, dataclass

VERSION = '1'


@dataclass(frozen=True)
class Section:
    kind: str
    start: float
    end: float


@dataclass(frozen=True)
class TrackGrid:
    analyser_version: str
    file_sha256: str
    duration: float
    sample_rate: int
    tempo: float
    beats: tuple[float, ...]
    kick_flags: tuple[bool, ...]
    sections: tuple[Section, ...]
    confidence: float
    timing_basis: str
    provisional: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['beats'] = tuple(data['beats'])
        data['kick_flags'] = tuple(data['kick_flags'])
        data['sections'] = tuple(Section(**s) for s in data['sections'])
        grid = cls(**data)
        if (grid.analyser_version != VERSION or len(grid.beats) != len(grid.kick_flags)
                or not math.isfinite(grid.duration) or grid.duration <= 0
                or grid.sample_rate <= 0
                or len(grid.file_sha256) != 64
                or not 60 <= grid.tempo <= 180 or not 0 <= grid.confidence <= 1
                or not all(math.isfinite(b) and 0 <= b <= grid.duration for b in grid.beats)
                or any(b <= a for a, b in zip(grid.beats, grid.beats[1:], strict=False))):
            raise ValueError('Invalid or obsolete track grid')
        return grid
