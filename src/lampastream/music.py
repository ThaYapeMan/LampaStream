"""Session-owned metadata choices; all I/O runs independently of light rendering."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from .album_art import CACHE_VERSION, ArtworkCache
from .genres import GenreLookup, matching_rule

log = logging.getLogger(__name__)


def track_key(track):
    return (
        (track.title, track.artist, track.album, track.genre, track.artwork_hash, track.artwork_url)
        if track
        else None
    )


class MusicDirector:
    def __init__(self, storage, apply, current_track, *, transport=None, current_palette=None):
        self.storage, self.apply, self.current_track = storage, apply, current_track
        self.lookup = GenreLookup(storage.music_settings, transport=transport)
        self.transport = transport
        self.current_palette = current_palette or (lambda: self.album_palette)
        self.art = ArtworkCache()
        self.images = {}
        self.image_failures = set()
        self.album_palette = None
        self.last_key = None
        self.applied = None
        self.status = {
            "genre": "other",
            "raw_tags": [],
            "source": "Unknown",
            "palette_id": "",
            "energy_profile_id": "",
            "manual": False,
        }

    async def artwork(self, track):
        if track.artwork_data:
            return await asyncio.to_thread(
                self.art.palette, track.artwork_data, self.current_palette())
        url = track.artwork_url
        cache_key = (CACHE_VERSION, url)
        if not url or urlparse(url).scheme not in ("http", "https"):
            self.art.outcome = ""
            return self.current_palette()
        if cache_key in self.images:
            palette, self.art.outcome = self.images[cache_key]
            return palette
        if cache_key in self.image_failures:
            self.art.outcome = "unavailable → kept current palette"
            return self.current_palette()
        try:
            async with httpx.AsyncClient(timeout=1.0, transport=self.transport) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 8 * 1024 * 1024:
                            raise ValueError("Artwork too large")
            palette = await asyncio.to_thread(self.art.palette, bytes(data), self.current_palette())
            if len(self.images) >= 128:
                self.images.pop(next(iter(self.images)))
            self.images[cache_key] = (palette, self.art.outcome)
            return palette
        except (httpx.HTTPError, ValueError):
            if len(self.image_failures) >= 128:
                self.image_failures.clear()
            self.image_failures.add(cache_key)
            log.warning("Album artwork unavailable; keeping the current palette")
            self.art.outcome = "unavailable → kept current palette"
            return self.current_palette()

    def render_signature(self, coupling):
        identity = self.status["energy_profile_id"] or coupling.energy_profile_id
        profile = self.storage.get_energy_profile(identity)
        if profile is None:
            return None
        effects = [self.storage.get_effect(identity) for identity in
                   (profile.high_energy_effect_id, profile.low_energy_effect_id)]
        return (profile.to_dict(), tuple(e.to_dict() if e else None for e in effects))

    async def step(self, track, coupling):
        settings = self.storage.music_settings()
        rules = self.storage.list_genre_rules()
        # Do not include secrets in diagnostic identities or status.
        key = (
            track_key(track),
            CACHE_VERSION,
            self.render_signature(coupling),
            settings.lastfm_enabled,
            bool(settings.lastfm_api_key),
            tuple(settings.genre_mapping.items()),
            tuple(r.to_dict().items() for r in rules),
            coupling.manual_palette_id,
            coupling.manual_energy_profile_id,
            settings.transition_mode,
            settings.transition_duration_s,
        )
        if key == self.last_key:
            return
        self.last_key = key
        if track is not None:
            resolution = await self.lookup.resolve(track)
            album = await self.artwork(track)
            if track_key(self.current_track()) != track_key(track):
                self.last_key = None  # stale response must not recolour the next track
                return
            if self.art.outcome == "monochrome cover":
                rule_palette, _ = matching_rule(rules, resolution["genre"])
                genre_palette = (self.storage.get_palette(rule_palette)
                                 if rule_palette != "album-art" else None)
                album = genre_palette or self.current_palette()
                self.art.outcome += (" → genre palette" if genre_palette
                                     else " → kept current palette")
            self.album_palette = album
            self.status.update(resolution)
            self.status["album_art_outcome"] = ("Album art: " + self.art.outcome
                                               if self.art.outcome else "")
        palette_id, energy_id = matching_rule(
            rules,
            self.status["genre"],
            coupling.manual_palette_id,
            coupling.manual_energy_profile_id,
        )
        self.status.update(
            palette_id=palette_id,
            energy_profile_id=energy_id,
            manual=bool(coupling.manual_palette_id or coupling.manual_energy_profile_id),
            album_art_available=(self.album_palette is not None and bool(self.art.outcome)
                                 and not self.art.outcome.startswith("unavailable")),
        )
        palette = (
            self.album_palette
            if palette_id == "album-art"
            else self.storage.get_palette(palette_id)
        )
        applied = (
            palette_id,
            palette.key if palette else None,
            energy_id,
            settings.transition_mode,
            settings.transition_duration_s,
            self.render_signature(coupling),
        )
        # The regular effect may itself select album art. Always supply its latest palette.
        album_key = self.album_palette.key if self.album_palette else None
        if (applied, album_key) != self.applied:
            self.apply(
                replace(coupling, energy_profile_id=energy_id or coupling.energy_profile_id),
                palette,
                self.album_palette,
            )
            self.applied = (applied, album_key)

    async def run(self, coupling):
        while True:
            current = self.storage.get_coupling(coupling.id) or coupling
            await self.step(self.current_track(), current)
            await asyncio.sleep(0.5)
