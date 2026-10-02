"""Shared perceptual palettes. Mathematics: Björn Ottosson's public-domain OKLab paper."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import numpy as np

from .types import Colour

RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
XYZ_TO_RGB = np.linalg.inv(RGB_TO_XYZ)
M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
I1, I2 = np.linalg.inv(M1), np.linalg.inv(M2)
GAMUT_C = ((0.692, 0.308), (0.170, 0.700), (0.153, 0.048))
WHITE = np.array([0.3127, 0.3290])


def linear(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def srgb(rgb):
    rgb = np.maximum(np.asarray(rgb, dtype=float), 0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)


def to_oklab(rgb):
    return M2 @ np.cbrt(M1 @ linear(rgb))


def from_oklab(lab):
    return np.clip(srgb(I1 @ (I2 @ lab) ** 3), 0, 1)


def easing(t):
    t = max(0.0, min(1.0, t))
    a, b = t**1.5, (1 - t) ** 1.5
    return a / (a + b)


def hex_rgb(colour):
    return tuple(int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))


@lru_cache(maxsize=16)
def gamut_factor(gamut=GAMUT_C):
    # A single affine chromaticity compression, not nearest-edge clipping.
    # All RGB chromaticities are inside their primary triangle. Mapping its
    # vertices inside Hue's triangle maps every colour inside, injectively.
    triangle = np.array(gamut).T
    inverse = np.linalg.inv(np.vstack([triangle, np.ones(3)]))
    white_weights = inverse @ np.append(WHITE, 1)
    factor = 1.0
    for rgb in np.eye(3):
        xyz = RGB_TO_XYZ @ rgb
        xy = xyz[:2] / xyz.sum()
        delta = inverse @ np.append(xy - WHITE, 0)
        for w, d in zip(white_weights, delta, strict=True):
            if d < 0:
                factor = min(factor, -w / d)
    return factor * 0.999  # keep rounding just inside the physical boundary


def map_gamut(rgb, gamut=GAMUT_C):
    if max(rgb) - min(rgb) < 1e-12:
        return Colour(*rgb)
    values = linear(rgb)
    xyz = RGB_TO_XYZ @ values
    if xyz.sum() < 1e-12:
        return Colour.BLACK
    xy = WHITE + gamut_factor(gamut) * (xyz[:2] / xyz.sum() - WHITE)
    mapped = XYZ_TO_RGB @ np.array([xy[0] / xy[1], 1.0, (1 - xy.sum()) / xy[1]])
    mapped = np.maximum(mapped, 0)
    # Preserve the original peak brightness independently of chromaticity.
    mapped *= max(values) / max(max(mapped), 1e-12)
    return Colour(*np.clip(srgb(mapped), 0, 1))


@dataclass
class Palette:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "New palette"
    stops: list[dict] = field(
        default_factory=lambda: [
            {"colour": "#ef553b", "position": 0},
            {"colour": "#ffd16b", "position": 100},
        ]
    )

    def __post_init__(self):
        if not self.name.strip() or not 2 <= len(self.stops) <= 8:
            raise ValueError("A palette needs a name and 2–8 colour stops")
        previous = -1
        for stop in self.stops:
            if set(stop) != {"colour", "position"}:
                raise ValueError("Each stop needs a colour and position")
            p = stop["position"]
            if (
                type(p) not in (int, float)
                or not math.isfinite(p)
                or not 0 <= p <= 100
                or p <= previous
                or not isinstance(stop["colour"], str)
                or not re.fullmatch(r"#[0-9a-fA-F]{6}", stop["colour"])
            ):
                raise ValueError("Stops must have distinct increasing positions and hex colours")
            previous = p
        palette_lookup(self.key)  # warm once, before this palette reaches the light loop

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    @property
    def key(self):
        return tuple((s["position"], s["colour"]) for s in self.stops)

    def sample(self, value, t=0.0, rotation_cps=0.0):
        value = (value + t * rotation_cps) % 1 if rotation_cps else max(0.0, min(1.0, value))
        table = palette_lookup(self.key)
        index = value * (len(table) - 1)
        lo = int(index)
        return table[lo].lerp(table[min(lo + 1, len(table) - 1)], index - lo)


@lru_cache(maxsize=512)
def palette_lookup(key):
    stops = list(key)
    if stops[0][0] != 0:
        stops.insert(0, (0, stops[0][1]))
    if stops[-1][0] != 100:
        stops.append((100, stops[-1][1]))
    labs = [to_oklab(hex_rgb(c)) for _, c in stops]
    table = []
    for i in range(1024):
        p = i * 100 / 1023
        interval = next((j for j in range(len(stops) - 1) if p <= stops[j + 1][0]), len(stops) - 2)
        a, b = stops[interval][0], stops[interval + 1][0]
        w = easing((p - a) / (b - a))
        rgb = (
            hex_rgb(stops[interval][1])
            if w == 0 or stops[interval][1] == stops[interval + 1][1]
            else hex_rgb(stops[interval + 1][1])
            if w == 1
            else from_oklab(labs[interval] * (1 - w) + labs[interval + 1] * w)
        )
        table.append(map_gamut(rgb))
    return tuple(table)


STARTERS = {
    "sunset": ("Sunset", ["#1a0033", "#ff5900", "#ffcc1a"]),
    "ocean": ("Ocean", ["#000d59", "#008c8c", "#8cf2e6"]),
    "neon": ("Neon", ["#d900d9", "#00d9d9", "#99f226"]),
    "monochrome": ("Monochrome", ["#0d0d26", "#4c598c", "#d9e6ff"]),
    "ember": ("Ember", ["#8c1c13", "#ff7b25", "#ffd16b"]),
    "candlelight": ("Candlelight", ["#a84926", "#eaa65c", "#ffe3ae"]),
    "glacier": ("Glacier", ["#3168ba", "#7dc4e8", "#d7f6f5"]),
    "forest": ("Forest", ["#175c43", "#65a35a", "#d7d78c"]),
    "pastel-garden": ("Pastel garden", ["#f0b4d1", "#b4d9d2", "#d5c2f0"]),
    "lavender": ("Lavender", ["#543a86", "#ab83c7", "#eed2ed"]),
    "party": ("Party", ["#ff4765", "#ffc43d", "#46ddaa", "#498fff"]),
    "electric": ("Electric", ["#593cff", "#21cfff", "#a3ff47"]),
}


def palette_from_colours(name, colours, identity=None):
    return Palette(
        id=identity or str(uuid.uuid4()),
        name=name,
        stops=[
            {"colour": c, "position": i * 100 / (len(colours) - 1)} for i, c in enumerate(colours)
        ],
    )


def starter_palettes():
    return [
        palette_from_colours(name, colours, identity)
        for identity, (name, colours) in STARTERS.items()
    ]
