"""Track-tag-first genre lookup; optional bounded Last.fm requests off the audio path."""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen

GENRES = (
    "house",
    "techno",
    "trance",
    "drum & bass",
    "electronic/ambient",
    "hip-hop",
    "R&B/soul",
    "pop",
    "rock",
    "jazz",
    "classical",
    "other",
)
DEFAULT_MAPPING = {
    "house": "house",
    "deep house": "house",
    "tech house": "house",
    "techno": "techno",
    "minimal techno": "techno",
    "trance": "trance",
    "progressive trance": "trance",
    "drum and bass": "drum & bass",
    "dnb": "drum & bass",
    "drum & bass": "drum & bass",
    "ambient": "electronic/ambient",
    "electronic": "electronic/ambient",
    "electronica": "electronic/ambient",
    "hip hop": "hip-hop",
    "hip-hop": "hip-hop",
    "rap": "hip-hop",
    "r&b": "R&B/soul",
    "soul": "R&B/soul",
    "rnb": "R&B/soul",
    "pop": "pop",
    "rock": "rock",
    "alternative rock": "rock",
    "metal": "rock",
    "jazz": "jazz",
    "classical": "classical",
    "orchestral": "classical",
}

DEFAULT_MAPPING.update({genre.casefold(): genre for genre in GENRES})


def map_tags(tags, mapping=None):
    mapping = DEFAULT_MAPPING if mapping is None else mapping
    for tag in tags:
        genre = mapping.get(tag.strip().casefold())
        if genre in GENRES:
            return genre
    return "other"


class GenreLookup:
    TTL = 24 * 3600

    def __init__(self, settings, *, transport=None, clock=time.monotonic):
        self.settings, self.transport, self.clock = settings, transport, clock
        self.cache = {}
        self.last_request = -10.0
        self.cooldown = 0.0
        self.lock = asyncio.Lock()

    async def tags(self, artist, title=None):
        key = (artist.casefold(), title.casefold() if title else None)
        cached = self.cache.get(key)
        if cached and self.clock() - cached[0] < cached[2]:
            return cached[1]
        async with self.lock:
            settings = self.settings()
            if not settings.lastfm_enabled or not settings.lastfm_api_key or not artist:
                return []
            # One request per second at most, including retries and artist fallback.
            await asyncio.sleep(max(0.0, 1.1 - (self.clock() - self.last_request)))
            settings = self.settings()
            if not settings.lastfm_enabled or not settings.lastfm_api_key:
                return []
            self.last_request = self.clock()
            params = {
                "method": "track.getTopTags" if title else "artist.getTopTags",
                "artist": artist,
                "api_key": settings.lastfm_api_key,
                "format": "json",
            }
            if title:
                params["track"] = title
            try:
                if self.clock() < self.cooldown:
                    return []
                if self.transport:
                    body = await asyncio.wait_for(self.transport(params), 1.0)
                else:
                    # urllib does not log request URLs containing the API key.
                    def fetch():
                        with urlopen(
                            "https://ws.audioscrobbler.com/2.0/?" + urlencode(params), timeout=1.0
                        ) as response:
                            data = response.read(128 * 1024 + 1)
                            if len(data) > 128 * 1024:
                                raise ValueError("Tag response too large")
                            return json.loads(data)

                    body = await asyncio.wait_for(asyncio.to_thread(fetch), 1.2)
                rows = body.get("toptags", {}).get("tag", [])
                tags = [
                    row["name"][:100]
                    for row in rows[:20]
                    if isinstance(row, dict) and isinstance(row.get("name"), str)
                ]
                ttl = self.TTL if not body.get("error") else 300
                if body.get("error") == 29:
                    self.cooldown = self.clock() + 300
            except (OSError, TimeoutError, ValueError, TypeError, AttributeError):
                tags, ttl = [], 300
                self.cooldown = self.clock() + 60
            if len(self.cache) >= 512:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (self.clock(), tags, ttl)
            return tags

    async def resolve(self, track):
        raw = [tag.strip() for tag in (track.genre or "").split(";") if tag.strip()]
        settings = self.settings()
        genre = map_tags(raw, settings.genre_mapping)
        if genre != "other" or not settings.lastfm_enabled:
            return {"raw_tags": raw, "genre": genre, "source": "Track tag" if raw else "Unknown"}
        tags = await self.tags(track.artist or "", track.title)
        genre = map_tags(tags, self.settings().genre_mapping)
        if genre == "other":
            tags += await self.tags(track.artist or "")
            genre = map_tags(tags, self.settings().genre_mapping)
        return {
            "raw_tags": list(dict.fromkeys(raw + tags)),
            "genre": genre,
            "source": "Last.fm" if tags else "Track tag" if raw else "Unknown",
        }


def matching_rule(rules, genre, manual_palette="", manual_energy=""):
    rule = next((rule for rule in rules if rule.genre == genre), None)
    return (
        manual_palette or (rule.palette_id if rule else ""),
        manual_energy or (rule.energy_profile_id if rule else ""),
    )
