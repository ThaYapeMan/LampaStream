"""Deterministic artwork colours, implemented from the owner's extraction specification."""

from __future__ import annotations

import colorsys
import hashlib
import io
import logging
import math
from collections import OrderedDict

import numpy as np
from PIL import Image

from .palettes import Palette

log = logging.getLogger(__name__)


def distance(a, b):
    ah, ass, av = colorsys.rgb_to_hsv(*(n / 255 for n in a))
    bh, bs, bv = colorsys.rgb_to_hsv(*(n / 255 for n in b))
    saturation = (ass + bs) / 2
    weights = (0.65, 0.20, 0.15) if saturation >= 0.15 else (0.1, 0.2, 0.7)
    hue = min(abs(ah - bh), 1 - abs(ah - bh)) * 2
    return sum(w * d for w, d in zip(weights, (hue, abs(ass - bs), abs(av - bv)), strict=True))


def punchy(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(n / 255 for n in rgb))
    if s < 0.15 and v > 0.95:
        return "#ffffff"
    v = min(v, 0.95)
    if s > 0.1:
        s += (1 - s) * 0.20
    return "#" + "".join(f"{round(n * 255):02x}" for n in colorsys.hsv_to_rgb(h, s, v))


def quantise(image, count):
    indexed = image.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = indexed.getpalette()
    size = image.width * image.height
    return sorted(
        [(tuple(palette[i * 3 : i * 3 + 3]), n / size) for n, i in indexed.getcolors()],
        key=lambda row: (-row[1], row[0]),
    )


def merge(rows, *, rescue=True):
    chosen = []
    for colour, share in rows:
        for i, (other, weight) in enumerate(chosen):
            avg = (
                colorsys.rgb_to_hsv(*(n / 255 for n in colour))[1]
                + colorsys.rgb_to_hsv(*(n / 255 for n in other))[1]
            ) / 2
            if distance(colour, other) < (0.12 if avg >= 0.25 else 0.20):
                chosen[i] = (other, weight + share)
                break
        else:
            chosen.append((colour, share))
    if rescue and len(chosen) < 3 and len(rows) > len(chosen):
        colours = [rows[0][0]]
        while len(colours) < min(3, len(rows)):
            candidates = [row for row in rows if row[0] not in colours]
            colour, _ = max(
                candidates,
                key=lambda row: min(distance(row[0], c) for c in colours) + 0.05 * row[1],
            )
            colours.append(colour)
        weights = {colour: 0.0 for colour in colours}
        for colour, share in rows:
            closest = min(colours, key=lambda c: distance(c, colour))
            weights[closest] += share
        chosen = list(weights.items())
    return sorted(chosen, key=lambda row: (-row[1], row[0]))


CACHE_VERSION = 2


def accent_score(row):
    _, saturation, value = colorsys.rgb_to_hsv(*(n / 255 for n in row[0]))
    # Colourfulness dominates area; even a small vivid logo can lead.
    return 0.85 * saturation * value + 0.15 * row[1]


def lamp_colour(rgb, hue_offset=0):
    h, s, v = colorsys.rgb_to_hsv(*(n / 255 for n in rgb))
    lifted = colorsys.hsv_to_rgb((h + hue_offset) % 1, s, max(v, math.ceil(.55 * 255) / 255))
    return punchy(tuple(n * 255 for n in lifted))


def _extract(data):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Artwork exceeds 8 MB")
    with Image.open(io.BytesIO(data)) as opened:
        if opened.width * opened.height > 16_000_000:
            raise ValueError("Artwork exceeds 16 million pixels")
        image = opened.convert("RGB")
        image.thumbnail((192, 192))
    # Quantise chromatic pixels separately so tiny accents survive a large
    # black/white area. Neutral colours cannot consume the accent budget.
    pixels = [tuple(int(n) for n in p) for p in np.asarray(image).reshape(-1, 3)
              if colorsys.rgb_to_hsv(*(n / 255 for n in p))[1] >= .12
              and max(p) > 0]
    if not pixels:
        return None, "monochrome cover"  # neutral-only covers use the fallback chain
    accents = Image.new("RGB", (len(pixels), 1))
    accents.putdata(pixels)
    rows = merge(quantise(accents, 12), rescue=False)
    rows = [row for row in rows
            if colorsys.rgb_to_hsv(*(n / 255 for n in row[0]))[1] >= .12]
    rows.sort(key=lambda row: (-accent_score(row), -row[1], row[0]))
    colours = [lamp_colour(rgb) for rgb, _ in rows[:4]]
    single = len(colours) == 1
    if single:
        # Lead with the detected accent, then extend either side by 30 degrees.
        colours = [colours[0], lamp_colour(rows[0][0], -1 / 12),
                   lamp_colour(rows[0][0], 1 / 12)]
    if len(colours) < 2:
        return None, "monochrome cover"
    palette = Palette(id="album-art", name="Album art", stops=[
        {"position": i * 100 / (len(colours) - 1), "colour": colour}
        for i, colour in enumerate(colours)])
    return palette, ("single accent → extended" if single else f"{len(colours)} colours")


def extract(data):
    return _extract(data)[0]


class ArtworkCache:
    def __init__(self):
        self.cache = OrderedDict()
        self.failed = set()
        self.outcome = ""

    def palette(self, data, current=None):
        digest = (CACHE_VERSION, hashlib.sha256(data).hexdigest())
        if digest in self.cache:
            self.cache.move_to_end(digest)
            palette, self.outcome = self.cache[digest]
            return palette
        if digest in self.failed:
            self.outcome = "unavailable → kept current palette"
            return current
        try:
            palette, self.outcome = _extract(data)
        except (OSError, ValueError, Image.DecompressionBombError):
            if len(self.failed) >= 128:
                self.failed.clear()
            self.failed.add(digest)
            log.warning("Album artwork could not be read; keeping the current palette")
            self.outcome = "unavailable → kept current palette"
            return current
        self.cache[digest] = (palette, self.outcome)
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return palette
