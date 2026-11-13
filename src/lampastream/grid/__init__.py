"""Source-independent, content-addressed beat grids."""
import math
from dataclasses import asdict, dataclass

VERSION = '4'
GRID_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class Section:
    kind: str
    start: float
    end: float
    tempo: float | None = None
    beat_band: str = 'none'
    bar_length: int | None = None
    bar_phase: int | None = None
    downbeat_confidence: float = 0.


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
    source_sample_rate: int = 48000
    source_channels: int = 2
    grid_schema_version: int = GRID_SCHEMA_VERSION
    audio_fingerprint: dict | None = None
    downbeats: tuple[float, ...] = ()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['beats'] = tuple(data['beats'])
        if 'downbeats' in data:
            data['downbeats'] = tuple(data['downbeats'])
        data['kick_flags'] = tuple(data['kick_flags'])
        data['sections'] = tuple(Section(**s) for s in data['sections'])
        if data.get('audio_fingerprint') is not None:
            from .fingerprint import Fingerprint
            data['audio_fingerprint'] = Fingerprint.from_dict(data['audio_fingerprint']).to_dict()
        grid = cls(**data)
        if (grid.grid_schema_version != GRID_SCHEMA_VERSION or grid.analyser_version != VERSION
                or len(grid.beats) != len(grid.kick_flags)
                or not math.isfinite(grid.duration) or grid.duration <= 0
                or grid.sample_rate != 48000
                or grid.source_sample_rate <= 0 or grid.source_channels not in (1, 2)
                or len(grid.file_sha256) != 64
                or not 60 <= grid.tempo <= 180 or not 0 <= grid.confidence <= 1
                or not all(math.isfinite(b) and 0 <= b <= grid.duration for b in grid.beats)
                or any(b <= a for a, b in zip(grid.beats, grid.beats[1:], strict=False))):
            raise ValueError('Invalid or obsolete track grid')
        if any(section.beat_band not in ('low', 'mid', 'high', 'none')
               or not 0 <= section.downbeat_confidence <= 1
               or (section.bar_length is not None and section.bar_length not in (3, 4))
               or (section.bar_phase is not None and (section.bar_length is None
                   or not 0 <= section.bar_phase < section.bar_length))
               for section in grid.sections):
            raise ValueError('Invalid grid section')
        if any(not math.isfinite(beat) or beat < 0 or beat > grid.duration
               for beat in grid.downbeats):
            raise ValueError('Invalid downbeats')
        if grid.audio_fingerprint is not None:
            from .fingerprint import Fingerprint
            value = Fingerprint.from_dict(grid.audio_fingerprint)
            if abs(value.duration-grid.duration) > .001:
                raise ValueError('Fingerprint duration differs from grid')
        return grid
