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
        self.blocked_provisional = False
        self.next_index = None
        self.started = None
        self.onsets = deque()
        self.loud = deque()
        self.reason = None
        self.metadata = {}
        self.available = None
        self.pending_grid = None
        self.switch_at = None
        self.last_emitted = -float("inf")
        self.enabled = True

    def set(self, value, now, *, enabled=True):
        self.enabled = enabled
        if value is None:
            self.metadata = {}
            self.available = None
            self.pending_grid = None
            self.grid = None
            self.next_index = None
            return
        identity, grid, origin, *metadata = value
        self.metadata = metadata[0] if metadata else {}
        identity_changed = identity != self.identity
        if identity_changed:
            self.grid = None
            self.next_index = None
            self.blocked = None
            self.blocked_provisional = False
            self.onsets.clear()
            if hasattr(self, '_attack_tail'):
                self._attack_tail.clear()
                self._attack_levels.clear()
            self.loud.clear()
            self.reason = None
            self.pending_grid = None
            self.last_emitted = -float("inf")
        if (grid is not None and not grid.provisional and self.blocked_provisional
                and self.blocked == identity):
            self.blocked = None
            self.blocked_provisional = False
            self.reason = None
        self.available = grid if identity != self.blocked else None
        changed = identity_changed or self.grid is None or abs(origin-self.origin) > .1
        self.identity, self.origin = identity, origin
        if (grid is None or not enabled
                or (grid.provisional and now+origin >= grid.duration)):
            self.grid = None
            self.pending_grid = None
            self.next_index = None
            return
        if self.grid is not None and grid is not self.grid and self.pending_grid is not grid:
            period = 60/self.grid.tempo
            first = next((b for b, kick in zip(self.grid.beats, self.grid.kick_flags,
                                                strict=True) if kick), 0.)
            following = next((b for b, kick in zip(grid.beats, grid.kick_flags,
                                                    strict=True) if kick), 0.)
            phase_error = abs(first-following)
            disagree = (abs(grid.tempo/self.grid.tempo-1) > .02+1e-9
                        or phase_error > period+1e-9)
            if disagree:
                log.warning('Provisional grid dropped before full adoption: tempo/phase mismatch')
                self.grid = None
                self.pending_grid = grid
                next_index = bisect.bisect_right(grid.beats, now+self.origin)
                self.switch_at = (grid.beats[next_index]-self.origin
                                  if next_index < len(grid.beats) else now+.01)
                return
            self.pending_grid = grid
            index = bisect.bisect_right(self.grid.beats, now+self.origin)
            self.switch_at = (self.grid.beats[index]-self.origin
                              if index is not None and index < len(self.grid.beats) else now)
        if self.pending_grid is not None:
            return
        self.grid = grid if identity != self.blocked else None
        if changed and self.grid:
            self.next_index = bisect.bisect_right(grid.beats, now+origin)
            self.started = now

    def observe(self, events):
        self.onsets.extend(e.candidate_sample/48000 for e in events if not e.predicted)

    def reset_attacks(self):
        self._attack_tail = deque(maxlen=3)
        self._attack_levels = deque(maxlen=600)

    def observe_attacks(self, frames):
        """Confirm against the same per-channel canonical measurement as the grid.

        Keep the neighbours across feed boundaries; an envelope block boundary
        must not invent a peak or lose the last candidate of the preceding feed.
        """
        if not hasattr(self, '_attack_tail'):
            self.reset_attacks()
        for sample, value in frames:
            self._attack_tail.append((sample/48000, value))
            self._attack_levels.append(value)
            if len(self._attack_tail) < 3:
                continue
            before, candidate, after = self._attack_tail
            threshold = max(1e-9, max(self._attack_levels)*.015)
            if candidate[1] > before[1] and candidate[1] >= after[1] and candidate[1] > threshold:
                self.onsets.append(candidate[0])

    def ticks(self, t, loud, *, horizon=0.):
        self.loud.append((t, loud))
        while self.loud and self.loud[0][0] < t-8:
            self.loud.popleft()
        while self.onsets and self.onsets[0] < t-9:
            self.onsets.popleft()
        if self.pending_grid is not None and t >= self.switch_at:
            self.grid = self.pending_grid
            self.pending_grid = None
            self.next_index = bisect.bisect_right(
                self.grid.beats, max(t-.01, self.last_emitted+.07)+self.origin)
            log.info('Full grid adopted at beat boundary %.3fs', t+self.origin)
        grid = self.grid
        if grid is not None and grid.provisional and t+self.origin >= grid.duration:
            self.grid = grid = None
        if grid is None:
            return []
        if self.started is not None and t-self.started >= 8:
            expected = [b-self.origin for b, kick in zip(grid.beats, grid.kick_flags, strict=True)
                        if kick and t-8 <= b-self.origin <= t-.07]
            if expected and self.loud and sum(v for _, v in self.loud)/len(self.loud) > .5:
                confirmed = sum(any(abs(o-b) <= .07 for o in self.onsets) for b in expected)
                if confirmed < .5*len(expected):
                    self.blocked_provisional = grid.provisional
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
                stamp = grid.beats[i]-self.origin
                if stamp > self.last_emitted+.07:
                    result.append((stamp, 1. if drop else .8, i))
                    self.last_emitted = stamp
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
        fact = self.available if self.identity != self.blocked else None
        return dict(**self.metadata, beat_source='grid' if grid else 'tracker',
                    grid_confidence=fact.confidence if fact else None,
                    grid_tempo=fact.tempo if fact else None,
                    provisional=bool(grid.provisional if grid else fact and fact.provisional),
                    grid_dropped_reason=self.reason,
                    time_to_next_drop_s=min(drops) if drops else None)
