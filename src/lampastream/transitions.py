"""Real-time scene changes. The phase begins at output sampling, not PCM arrival."""

from __future__ import annotations

from .types import Colour


def transition_colour(old, new, w, mode):
    w = max(0.0, min(1.0, w))
    if w == 0:
        return old
    if w == 1:
        return new
    if mode == "crossfade":
        return old.lerp(new, w)
    values = (old.r, old.g, old.b) if w < 0.5 else (new.r, new.g, new.b)
    if mode == "through-black":
        cap = 1 - 2 * w if w < 0.5 else 2 * w - 1
        return Colour(*(min(v, cap) for v in values))
    floor = 2 * w if w < 0.5 else 2 * (1 - w)
    return Colour(*(max(v, floor) for v in values))


class FrozenScene:
    def __init__(self, scene, timestamp):
        self.scene, self.timestamp = scene, timestamp

    def color_at(self, position, t):
        return self.scene.color_at(position, self.timestamp)


class TransitionPhase:
    def __init__(self, mode="crossfade", duration=0.7, baseline=None):
        self.mode, self.duration, self.baseline = mode, duration, baseline
        self.start = None
        self.frozen = None
        self.completed = duration == 0

    def advance(self, t):
        """Advance once on the render clock; arbitrary scene samples are pure."""
        if self.start is None:
            self.start = t
            if self.baseline:
                scene, stamp = self.baseline()
                if scene is not None:
                    self.frozen = FrozenScene(scene, stamp)
        self.completed = self.completed or self.weight(t) == 1

    def weight(self, t):
        if self.start is None:
            return 1. if self.duration == 0 else 0.
        weight = 1 if self.duration == 0 else max(0., min(1., (t-self.start)/self.duration))
        return 1. if weight >= 1-1e-9 else weight


class TransitionScene:
    def __init__(self, old, new, phase):
        from copy import copy
        self.old, self.new, self.phase = old, new, copy(phase)

    def color_at(self, position, t):
        w = self.phase.weight(t)
        old = self.phase.frozen or self.old
        return transition_colour(
            old.color_at(position, t), self.new.color_at(position, t), w, self.phase.mode
        )
