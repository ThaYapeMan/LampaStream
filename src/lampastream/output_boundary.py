"""Precision guard shared by output drivers, independent of effect rendering."""
from __future__ import annotations

from .types import Colour, OutputCapabilities


class QuantisationGuard:
    """Keep a trigger above the measured idle baseline by eight output codes.

    Sub-code falling steps hold their last value until a full code is crossed.
    Idle colours pass through exactly and refresh the per-position baseline.
    Console fall tails retain sub-code guarding without the peak minimum lift.
    """

    def __init__(self, capabilities: OutputCapabilities):
        self.lsb = 1 / ((1 << capabilities.colour_depth_bits) - 1)
        self.baseline = {}
        self.previous = {}

    def colour(self, key, colour: Colour, active: bool, *, minimum_lift=True) -> Colour:
        values = (colour.r, colour.g, colour.b)
        if not active:
            self.baseline[key] = values
            self.previous[key] = values
            return colour
        base = self.baseline.get(key, (0.0,) * 3)
        previous = self.previous.get(key, base)
        guarded = (tuple(min(1.0, max(value, floor + (1 << 3) * self.lsb))
                        if value > floor else value
                        for value, floor in zip(values, base, strict=True))
                   if minimum_lift else values)
        guarded = tuple(old if 0 < old-new < self.lsb else new
                        for old, new in zip(previous, guarded, strict=True))
        self.previous[key] = guarded
        return Colour(*guarded)


class BoundaryScene:
    """Immutable output samples; precision state advances once at render time."""

    def __init__(self, scene, guard, positions, t, active, *, minimum_lift=True):
        self.scene = scene
        self.colours = {position: guard.colour(position, scene.color_at(position, t), active,
                                               minimum_lift=minimum_lift)
                        for position in positions}

    def __getattr__(self, name):
        return getattr(self.scene, name)

    def color_at(self, position, t):
        if position in self.colours:
            return self.colours[position]
        return self.scene.color_at(position, t)
