"""Generic verified track-time prior for the existing beat fusion processor."""
from __future__ import annotations

import bisect
import logging
from collections import deque
from dataclasses import replace

log = logging.getLogger(__name__)


class GridPrior:
    def __init__(self):
        self.identity = None
        self.grid = None
        self.origin = 0.
        self.blocked = None
        self.next_index = None
        self.started = None
        self.onsets = deque()
        self.loud = deque()
        self.reason = None
        self.metadata = {}

    def set(self, value, now):
        if value is None:
            self.metadata = {}
            self.grid = None
            self.next_index = None
            return
        identity, grid, origin, *metadata = value
        self.metadata = metadata[0] if metadata else {}
        identity_changed = identity != self.identity
        if identity_changed:
            self.blocked = None
            self.onsets.clear()
            self.loud.clear()
            self.reason = None
        changed = identity_changed or self.grid is None or abs(origin-self.origin) > .1
        self.identity, self.origin = identity, origin
        if grid is None:
            self.grid = None
            self.next_index = None
            return
        self.grid = grid if identity != self.blocked else None
        if changed and self.grid:
            self.next_index = bisect.bisect_right(grid.beats, now+origin)
            self.started = now

    def observe(self, events):
        self.onsets.extend(e.candidate_sample/48000 for e in events if not e.predicted)

    def ticks(self, t, loud, *, horizon=0.):
        self.loud.append((t, loud))
        while self.loud and self.loud[0][0] < t-8:
            self.loud.popleft()
        while self.onsets and self.onsets[0] < t-9:
            self.onsets.popleft()
        grid = self.grid
        if grid is None:
            return []
        if self.started is not None and t-self.started >= 8:
            expected = [b-self.origin for b, kick in zip(grid.beats, grid.kick_flags, strict=True)
                        if kick and t-8 <= b-self.origin <= t-.07]
            if expected and self.loud and sum(v for _, v in self.loud)/len(self.loud) > .5:
                confirmed = sum(any(abs(o-b) <= .07 for o in self.onsets) for b in expected)
                if confirmed < .5*len(expected):
                    self.blocked, self.grid = self.identity, None
                    self.reason = 'audio contradicts grid'
                    log.warning('Grid dropped for %s: %s (%d/%d)', self.identity,
                                self.reason, confirmed, len(expected))
                    return []
        result = []
        while self.next_index is not None and self.next_index < len(grid.beats):
            i = self.next_index
            if grid.beats[i]-self.origin > t+horizon:
                break
            self.next_index += 1
            if grid.kick_flags[i]:
                drop = any(s.kind == 'drop' and abs(s.start-grid.beats[i]) < .001
                           for s in grid.sections)
                result.append((grid.beats[i]-self.origin, 1. if drop else .8, i))
        return result

    def event(self, template, stamp, strength, index):
        sample = round(stamp*48000)
        return replace(template, id=(template.epoch, 'grid', sample), candidate_sample=sample,
                       strength=strength, confidence=self.grid.confidence, predicted=True,
                       on_beat=True, bar_position=index % 4, beat_phase=0.)

    def phase(self, now):
        if self.grid is None:
            return 0.
        position = now+self.origin
        i = bisect.bisect_right(self.grid.beats, position)-1
        if i < 0 or i+1 >= len(self.grid.beats):
            return 0.
        start, end = self.grid.beats[i:i+2]
        return (position-start)/(end-start)

    def status(self, now):
        grid = self.grid
        drops = ([s.start-self.origin-now for s in grid.sections
                  if s.kind == 'drop' and s.start >= now+self.origin] if grid else [])
        return dict(**self.metadata, beat_source='grid' if grid else 'tracker',
                    grid_confidence=grid.confidence if grid else None,
                    grid_tempo=grid.tempo if grid else None,
                    grid_dropped_reason=self.reason,
                    time_to_next_drop_s=min(drops) if drops else None)
