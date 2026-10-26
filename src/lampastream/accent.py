"""Universal event-envelope accents, applied once after the energy blend."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

from .types import Colour


def _linear(value):
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def _encoded(value):
    return value * 12.92 if value <= .0031308 else 1.055 * value ** (1 / 2.4) - .055


@dataclass
class AccentScene:
    scene: object
    profile: object
    band_values: dict
    accent_value: float
    phase: float
    positions: tuple
    palette: object = None

    def __getattr__(self, name):
        return getattr(self.scene, name)

    def value_at(self, position):
        if self.profile.accent_spatial == "uniform" or not self.positions:
            return self.accent_value
        ordered = self.positions
        index = ordered.index(position) if position in ordered else 0
        furthest = max(ordered, key=lambda p: p.x*p.x + p.y*p.y + p.z*p.z)
        return max(self.band_values["bass"],
                   self.band_values["mid"] if index % 2 == 0 else 0,
                   self.band_values["treble"] if position == furthest else 0)

    def color_at(self, position, t):
        old = self.scene.color_at(position, t)
        amount = min(1., self.value_at(position))
        h, s, v = colorsys.rgb_to_hsv(old.r, old.g, old.b)
        if self.profile.accent_mode == "palette_step":
            colour = self.palette.sample((h + self.phase) % 1)
            h, s, _ = colorsys.rgb_to_hsv(colour.r, colour.g, colour.b)
        elif self.profile.accent_mode == "pop":
            s += (1-s)*amount
        # Interpolate peak intensity in linear light, then scale the encoded
        # components together: HSV angle and saturation are preserved exactly.
        peak = _encoded(_linear(v) + (1-_linear(v))*amount)
        return Colour(*colorsys.hsv_to_rgb(h, s, min(1., peak)))


class AccentLayer:
    """No clock or decay: EVENT-01 envelopes own the entire time course."""

    def __init__(self):
        self.phase = 0.
        self.newest = None
        self.last_value = 0.
        self.palette_key = None
        self.palette = None

    def render(self, scene, features, profile, positions=()):
        if profile.accent_mode == "off" or profile.effect_type == "none":
            self.last_value = 0.
            return scene
        if features.onset_events:
            self.newest = features.onset_events[-1]
        strength = self.newest.strength if self.newest else features.onset_strength
        confidence = self.newest.confidence if self.newest else 1.
        # Envelopes already include peak strength. Divide it out before applying
        # the configurable curve, so gamma=1 does not square the event strength.
        scale = strength ** (profile.accent_strength_curve-1) if strength > 0 else 0.
        values = {band: profile.accent_amount * weight * scale * confidence *
                  getattr(features, f"onset_envelope_{band}")
                  for band, weight in profile.accent_band_weights.items()}
        if not any(getattr(features, f"onset_envelope_{band}")
                   for band in profile.accent_band_weights):
            values["bass"] = profile.accent_amount * scale * confidence * features.onset_envelope
        legacy = profile.onset_flash_intensity * features.onset_envelope
        values = {band: value + legacy for band, value in values.items()}
        self.last_value = max(values.values())
        if profile.accent_mode == "palette_step":
            self.phase = (self.phase + features.onset_count_since_render *
                          profile.accent_palette_step) % 1
        if profile.accent_mode == "palette_step":
            from .palettes import STARTERS, Palette, palette_from_colours
            key = repr((profile.palette_stops, profile.gradient_palette))
            if key != self.palette_key:
                self.palette_key = key
                self.palette = (Palette(stops=profile.palette_stops) if profile.palette_stops
                    else palette_from_colours(*STARTERS.get(
                        profile.gradient_palette, STARTERS["sunset"])))
        ordered = tuple(sorted(set(positions), key=lambda p: (p.x, p.y, p.z)))
        return AccentScene(scene, profile, values, self.last_value, self.phase, ordered,
                           self.palette)
