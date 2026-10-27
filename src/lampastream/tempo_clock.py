"""Pairwise interval tempo hypotheses and a persistent four-beat phase clock.

Original NumPy/Python implementation of the hypothesis clustering and median
idea described by FastLED TempoAnalyzer (MIT), not copied detector code.
Attribution: FastLED contributors, https://github.com/FastLED/FastLED.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from statistics import median


@dataclass
class Hypothesis:
    bpm: float
    score: float


class TempoClock:
    def __init__(self, latency_ms=0., fade_s=2.):
        self.latency_s = latency_ms/1000
        self.fade_s = fade_s
        self.hypotheses = []
        self.triggers = deque(maxlen=16)
        self.estimates = deque(maxlen=21)
        self.accents = deque(maxlen=4)
        self.tempo_bpm = None
        self.tempo_alt_bpm = None
        self.confidence = 0.
        self.locked = False
        self.stable_since = None
        self.last_update = None
        self.last_trigger = None
        self.anchor = None
        self.beat_index = 0
        self.downbeat_index = 0
        self.octave_rule = 'prefer 70–180 BPM unless alternative support is ≥1.5×'

    @property
    def period(self):
        return 60/self.tempo_bpm if self.tempo_bpm else None

    @property
    def next_beat(self):
        if self.anchor is None or self.period is None:
            return None
        return self.anchor + self.period + self.latency_s

    def phase(self, t):
        return ((t-self.anchor)/self.period) % 1 if self.period and self.anchor is not None else 0.

    def update(self, t, *, gate=True):
        dt = 0. if self.last_update is None else max(0., t-self.last_update)
        self.last_update = t
        for hypothesis in self.hypotheses:
            hypothesis.score *= math.exp(-dt)
        self.hypotheses = [h for h in self.hypotheses if h.score > .001]
        age = t-self.last_trigger if self.last_trigger is not None else math.inf
        if age > (self.period or 1.)*1.2:
            self.confidence *= math.exp(-dt/self.fade_s)
        if not gate and age >= 2:
            self.locked = False
            self.stable_since = None
        return self

    def trigger(self, t, strength=1.):
        self.update(t)
        old_bpm = self.tempo_bpm
        # Every pair votes for integral subdivisions of its interval. Weight by
        # recency and inverse subdivision, so distant harmonics cannot dominate.
        for previous in self.triggers:
            interval = t-previous
            if not .25-1e-9 <= interval <= 2.+1e-9:
                continue
            for subdivision in range(1, 8):
                bpm = 60*subdivision/interval
                if not 50 <= bpm <= 220:
                    continue
                weight = math.exp(-interval/2)/subdivision
                closest = min(self.hypotheses, key=lambda h: abs(h.bpm-bpm), default=None)
                if closest is not None and abs(closest.bpm-bpm) <= 3:
                    closest.bpm = (closest.bpm*closest.score+bpm*weight)/(closest.score+weight)
                    closest.score += weight
                else:
                    self.hypotheses.append(Hypothesis(bpm, weight))
        self.triggers.append(t)
        self.last_trigger = t
        if not self.hypotheses:
            self.anchor = t
            return self
        ranked = sorted(self.hypotheses, key=lambda h: h.score, reverse=True)
        winner = ranked[0]
        preferred = next((h for h in ranked if 70 <= h.bpm <= 180
                          and (abs(h.bpm*2-winner.bpm) <= 3
                               or abs(h.bpm/2-winner.bpm) <= 3)), None)
        if not 70 <= winner.bpm <= 180 and preferred and winner.score < 1.5*preferred.score:
            winner = preferred
        alternative = next((h for h in ranked if h is not winner
                            and (abs(h.bpm*2-winner.bpm) <= 3
                                 or abs(h.bpm/2-winner.bpm) <= 3)), None)
        self.tempo_alt_bpm = alternative.bpm if alternative else None
        # New-tempo evidence must not spend 21 beats behind the old median.
        if self.estimates and abs(winner.bpm-median(self.estimates)) > 3:
            recent = list(self.triggers)[-4:]
            intervals = [b-a for a, b in zip(recent, recent[1:], strict=False)]
            if len(intervals) == 3 and max(intervals)-min(intervals) < .025:
                local = 60/median(intervals)
                if abs(local-winner.bpm) < 3:
                    self.estimates.clear()
        self.estimates.append(winner.bpm)
        self.tempo_bpm = median(self.estimates)
        stability = max(0., 1-abs(winner.bpm-self.tempo_bpm)/3)
        self.confidence = min(1., winner.score/1.5)*stability
        if old_bpm is not None and abs(old_bpm-self.tempo_bpm) > 3:
            self.locked = False
            self.stable_since = None
        if self.confidence >= .5:
            if self.stable_since is None:
                self.stable_since = t
            if t-self.stable_since >= 2-1e-9:
                self.locked = True
        else:
            self.stable_since = None
        if self.anchor is None:
            self.anchor = t
        elif (not self.locked or abs(t-self.anchor
                - round((t-self.anchor)/self.period)*self.period) <= .04):
            steps = max(1, round((t-self.anchor)/self.period))
            self.beat_index += steps
            self.anchor = t
        self.accents.append((self.beat_index, strength))
        if len(self.accents) == 4:
            self.downbeat_index = max(self.accents, key=lambda pair: pair[1])[0] % 4
        return self

    def bar_position(self, t):
        if self.anchor is None or self.period is None:
            return None
        return (self.beat_index + round((t-self.anchor)/self.period)-self.downbeat_index) % 4
