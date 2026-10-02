"""Deterministic artwork colours, implemented from the owner's extraction specification."""

from __future__ import annotations

import colorsys
import hashlib
import io
import logging
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


def merge(rows):
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
    if len(chosen) < 3 and len(rows) > len(chosen):
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


def extract(data):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Artwork exceeds 8 MB")
    with Image.open(io.BytesIO(data)) as opened:
        if opened.width * opened.height > 16_000_000:
            raise ValueError("Artwork exceeds 16 million pixels")
        image = opened.convert("RGB")
        image.thumbnail((192, 192))
    first = quantise(image, 12)
    background = first[0][0] if first[0][1] >= 0.5 else None
    rows = merge(first)
    if background is not None:
        pixels = np.asarray(image).reshape(-1, 3)
        keep = [
            p
            for p in pixels
            if not (
                colorsys.rgb_to_hsv(*(n / 255 for n in p))[2] < 0.12
                or (
                    colorsys.rgb_to_hsv(*(n / 255 for n in p))[1] < 0.10
                    and colorsys.rgb_to_hsv(*(n / 255 for n in p))[2] < 0.22
                )
            )
        ]
        masked = (
            Image.fromarray(np.asarray(keep, dtype=np.uint8).reshape(1, -1, 3))
            if len(keep) >= 0.02 * len(pixels)
            else image
        )
        second = merge(quantise(masked, 9))
        rows = second if len(second) >= 5 else [row for row in rows if row[0] != background]
        rows = [row for row in rows if row[0] != background]
    if not rows:
        colour = punchy(background or first[0][0])
        stops = [{"position": 0, "colour": colour}, {"position": 100, "colour": colour}]
    elif background is not None:
        # Two strongest accents permit flat regions/background within the shared eight-stop budget.
        accents, stops = rows[:2], [{"position": 0, "colour": punchy(background)}]
        width = 100 / len(accents)
        for i, (colour, _) in enumerate(accents):
            stops.extend(
                [
                    {"position": (i + 0.3) * width, "colour": punchy(colour)},
                    {"position": (i + 0.7) * width, "colour": punchy(colour)},
                    {"position": (i + 1) * width, "colour": punchy(background)},
                ]
            )
    else:
        rows = rows[:4]  # 2 + 2*(n-1) stops, at most eight
        total = sum(share for _, share in rows)
        widths = [share / total * 100 for _, share in rows]
        stops = [{"position": 0, "colour": punchy(rows[0][0])}]
        boundary = 0.0
        for i in range(len(rows) - 1):
            boundary += widths[i]
            b = min(0.10 * widths[i], 0.45 * min(widths[i], widths[i + 1]))
            stops.extend(
                [
                    {"position": boundary - b, "colour": punchy(rows[i][0])},
                    {"position": boundary + b, "colour": punchy(rows[i + 1][0])},
                ]
            )
        stops.append({"position": 100, "colour": punchy(rows[-1][0])})
    return Palette(id="album-art", name="Album art", stops=stops)


class ArtworkCache:
    def __init__(self):
        self.cache = OrderedDict()
        self.failed = set()

    def palette(self, data, current=None):
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.cache:
            self.cache.move_to_end(digest)
            return self.cache[digest]
        if digest in self.failed:
            return current
        try:
            palette = extract(data)
        except (OSError, ValueError, Image.DecompressionBombError):
            if len(self.failed) >= 128:
                self.failed.clear()
            self.failed.add(digest)
            log.warning("Album artwork could not be read; keeping the current palette")
            return current
        self.cache[digest] = palette
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return palette
