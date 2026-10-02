"""Lamp-usable covers and contextual fallbacks, with no network or hardware."""
import colorsys
import hashlib
import io

import httpx
import pytest
from PIL import Image

from lampastream import album_art
from lampastream.album_art import ArtworkCache, extract
from lampastream.models import Coupling, GenreRule
from lampastream.music import MusicDirector
from lampastream.palettes import hex_rgb, starter_palettes
from lampastream.storage import Storage
from lampastream.track_position import TrackPosition


def cover(colours, counts):
    image = Image.new('RGB', (sum(counts), 1))
    image.putdata([c for c, count in zip(colours, counts, strict=True) for _ in range(count)])
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def assert_usable(palette):
    assert 2 <= len(palette.stops) <= 4
    positions = [s['position'] for s in palette.stops]
    assert positions == pytest.approx([i * 100 / (len(positions) - 1)
                                      for i in range(len(positions))])
    hsv = [colorsys.rgb_to_hsv(*hex_rgb(s['colour'])) for s in palette.stops]
    assert all(v >= .55 for _, _, v in hsv)
    assert all(s >= .12 for _, s, _ in hsv)


@pytest.mark.parametrize('colours,counts,outcome', [
    ([(0, 0, 0), (255, 0, 0)], [99, 1], 'single accent → extended'),
    ([(0, 0, 25), (255, 110, 0)], [90, 10], '2 colours'),
    ([(255, 0, 0), (0, 255, 0), (0, 0, 255)], [35, 35, 30], '3 colours'),
    ([(80, 5, 10)], [100], 'single accent → extended'),
    ([(180, 170, 165), (255, 0, 0), (0, 0, 255)], [90, 5, 5], '2 colours'),
])
def test_accents_are_usable_evenly_spaced_without_background(colours, counts, outcome):
    cache = ArtworkCache()
    data = cover(colours, counts)
    palette = cache.palette(data)
    assert_usable(palette)
    assert cache.outcome == outcome
    assert cache.palette(data) is palette
    assert cache.outcome == outcome
    if colours[-1] == (255, 0, 0) or colours == [(0, 0, 0), (255, 0, 0)]:
        h, _, _ = colorsys.rgb_to_hsv(*hex_rgb(palette.stops[0]['colour']))
        assert min(h, 1 - h) < .02


def test_small_vivid_accent_outranks_large_dull_chromatic_area():
    palette = extract(cover([(100, 90, 70), (255, 0, 0)], [99, 1]))
    assert_usable(palette)
    h, _, _ = colorsys.rgb_to_hsv(*hex_rgb(palette.stops[0]['colour']))
    assert min(h, 1 - h) < .02


@pytest.mark.parametrize('colours,counts', [
    ([(0, 0, 0), (255, 255, 255)], [80, 20]),
    ([(255, 255, 255)], [100]),
    ([(0, 0, 0)], [100]),
    ([(30, 30, 30), (180, 180, 180)], [50, 50]),
])
@pytest.mark.anyio
async def test_monochrome_falls_back_to_genre_then_actual_current_palette(
        tmp_path, colours, counts):
    storage = Storage(tmp_path / 'config.json')
    storage.save_genre_rule(GenreRule(genre='house', palette_id='ocean'))
    current = next(p for p in starter_palettes() if p.id == 'party')
    track = TrackPosition(title='Cover', genre='house', artwork_data=cover(colours, counts))
    applied = []
    director = MusicDirector(storage, lambda c, p, a: applied.append(a), lambda: track,
                             current_palette=lambda: current)
    coupling = Coupling(manual_palette_id='album-art')
    await director.step(track, coupling)
    assert applied[-1].id == 'ocean'
    assert director.status['album_art_outcome'] == 'Album art: monochrome cover → genre palette'
    storage.delete_genre_rule(storage.list_genre_rules()[0].id)
    await director.step(track, coupling)  # cache hit must re-evaluate contextual fallback
    assert applied[-1] is current
    assert director.status['album_art_outcome'] == (
        'Album art: monochrome cover → kept current palette')
    assert director.status['palette_id'] == 'album-art'


def test_cache_version_ignores_old_extraction_and_reextracts_on_version_change(monkeypatch):
    data = cover([(0, 0, 0), (255, 0, 0)], [90, 10])
    digest = hashlib.sha256(data).hexdigest()
    cache = ArtworkCache()
    old = starter_palettes()[0]
    cache.cache[digest] = old  # old unversioned format
    cache.cache[(1, digest)] = (old, 'old method')
    fresh = cache.palette(data)
    assert fresh is not old
    assert cache.palette(data) is fresh
    monkeypatch.setattr(album_art, 'CACHE_VERSION', album_art.CACHE_VERSION + 1)
    assert cache.palette(data) is not fresh


@pytest.mark.anyio
async def test_url_cache_preserves_extraction_outcome_and_resolves_fallback_per_genre(tmp_path):
    data = cover([(255, 255, 255)], [100])
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, content=data)

    storage = Storage(tmp_path / 'config.json')
    current = starter_palettes()[-1]
    track = TrackPosition(title='White', genre='house', artwork_url='http://art.test/cover')
    director = MusicDirector(storage, lambda *a: None, lambda: track,
                             current_palette=lambda: current,
                             transport=httpx.MockTransport(response))
    await director.step(track, Coupling(manual_palette_id='album-art'))
    assert director.status['album_art_outcome'].endswith('kept current palette')
    storage.save_genre_rule(GenreRule(genre='house', palette_id='ocean'))
    await director.step(track, Coupling(manual_palette_id='album-art'))
    assert director.album_palette.id == 'ocean'
    assert director.status['album_art_outcome'].endswith('genre palette')
    assert len(requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('colours,counts,outcome', [
    ([(0, 0, 0), (255, 0, 0)], [99, 1], 'single accent → extended'),
    ([(255, 0, 0), (0, 255, 0), (0, 0, 255)], [35, 35, 30], '3 colours'),
])
async def test_director_reports_chromatic_extraction_outcome(tmp_path, colours, counts, outcome):
    storage = Storage(tmp_path / 'config.json')
    track = TrackPosition(title='Artwork', artwork_data=cover(colours, counts))
    applied = []
    director = MusicDirector(storage, lambda c, p, a: applied.append(a), lambda: track)
    await director.step(track, Coupling(manual_palette_id='album-art'))
    assert director.status['album_art_outcome'] == 'Album art: ' + outcome
    assert_usable(applied[-1])


@pytest.mark.anyio
async def test_missing_artwork_keeps_current_without_claiming_a_cover(tmp_path):
    storage = Storage(tmp_path / 'config.json')
    current = starter_palettes()[-1]
    track = TrackPosition(title='No image')
    director = MusicDirector(storage, lambda *a: None, lambda: track,
                             current_palette=lambda: current)
    await director.step(track, Coupling(manual_palette_id='album-art'))
    assert director.album_palette is current
    assert director.status['album_art_available'] is False
    assert director.status['album_art_outcome'] == ''
