"""Independent specification fixtures for music colour selection (no hardware/network)."""

from __future__ import annotations

import asyncio
import copy
import io
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image
from pipeline_factory import make_pipeline

from lampastream.album_art import ArtworkCache, distance, extract, merge, punchy
from lampastream.canonicalizer import AnalysisPcmFrame
from lampastream.genres import GenreLookup, map_tags, matching_rule
from lampastream.migration import convert
from lampastream.models import GenreRule, MusicSettings, Profile
from lampastream.music import MusicDirector
from lampastream.palettes import (
    GAMUT_C,
    RGB_TO_XYZ,
    Palette,
    easing,
    from_oklab,
    hex_rgb,
    linear,
    map_gamut,
    palette_lookup,
    starter_palettes,
    to_oklab,
)
from lampastream.schema import empty_config, validate_current
from lampastream.storage import Storage
from lampastream.sync_engine import ColourModeEffect, LayerMixer, SustainedEnergyTracker
from lampastream.track_position import AirPlayTrackPositionSource, TrackPosition
from lampastream.transitions import TransitionPhase, TransitionScene, transition_colour
from lampastream.types import AudioFeatures, Colour, Position, UniformScene

ORIGIN = Position(0, 0, 0)


def test_default_sustained_source_follows_sections_and_holds_silence():
    pipeline = make_pipeline(
        source=Mock(),
        onset_method="combined",
        onset_delta=0.1,
        onset_alpha=0.9,
        superflux_mu=3,
        superflux_lag=2,
        bass_hz=250,
        mid_hz=2000,
    )
    features = []
    offset = 0
    for amplitude in (0.1, 0.4, 0.02, 0):
        for _ in range(100):
            samples = np.ones((480, 2), np.float32) * amplitude
            pipeline._process_canonical_frame(
                AnalysisPcmFrame(
                    samples=samples,
                    epoch_id="session",
                    sample_pos=offset,
                    source_id="test",
                    over_range=False,
                )
            )
            offset += 480
        features.append(pipeline.latest())
    assert features[0].sustained_energy == pytest.approx(0.5)
    assert features[1].sustained_energy > 0.95
    assert features[2].sustained_energy < 0.1
    assert features[3].sustained_energy == features[2].sustained_energy
    mixer = LayerMixer(Profile(blend_response=1), Profile())
    for f in features:
        f.full = 0.75  # exertion deliberately cannot explain these section changes
        mixer.render(f, 0)
        assert mixer.last_energy_input == f.sustained_energy


def test_stereo_phase_does_not_cancel_sustained_energy():
    tracker = SustainedEnergyTracker()
    assert tracker.push(np.array([0.3, -0.3] * 10), 0.01) == 0.5
    assert tracker.push(np.zeros(100), 1000) == 0.5


@pytest.mark.parametrize("rgb", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0.2, 0.5, 0.8)])
def test_oklab_round_trip(rgb):
    assert from_oklab(to_oklab(rgb)) == pytest.approx(rgb, abs=1e-6)


def test_palette_easing_endpoints_and_missing_edges():
    assert easing(0) == 0 and easing(1) == 1 and easing(0.5) == 0.5
    assert easing(0.1) < 0.1 and easing(0.9) > 0.9
    p = Palette(
        stops=[{"position": 20, "colour": "#ff0000"}, {"position": 80, "colour": "#0000ff"}]
    )
    assert len(palette_lookup(p.key)) == 1024
    assert p.sample(0) == map_gamut((1, 0, 0))
    assert p.sample(1) == map_gamut((0, 0, 1))
    assert p.sample(0.1) == p.sample(0)
    assert p.sample(0.9) == p.sample(1)
    assert p.sample(0.3, 1, 0.1) == p.sample(0.4)
    assert p.sample(0.3, 2, 0.1) == p.sample(0.5)


def test_gamut_mapping_keeps_distinct_saturated_colours_inside_triangle():
    colours = ["#00ff00", "#00fe01", "#01ff00", "#20ff00", "#00ff20", "#ff0000", "#0000ff"]
    commands = []
    inverse = np.linalg.inv(np.vstack([np.array(GAMUT_C).T, np.ones(3)]))
    for hex_colour in colours:
        colour = map_gamut(hex_rgb(hex_colour))
        commands.append(colour.to_16bit())
        xyz = RGB_TO_XYZ @ linear((colour.r, colour.g, colour.b))
        weights = inverse @ np.append(xyz[:2] / xyz.sum(), 1)
        assert min(weights) >= -1e-6
    assert len(set(commands)) == len(colours)


def test_palette_migration_round_trip_preserves_legacy_values():
    data = empty_config()
    data["schema_version"] = 1
    for key in ("palettes", "genre_rules", "music_settings"):
        del data[key]
    bands = ["#123456", "#abcdef", "#789abc", "#ffffff"]
    data["effects"] = [
        {"id": "bands", "band_colours": bands},
        *[
            {"id": name, "effect_type": "gradient", "gradient_palette": name}
            for name in ("sunset", "ocean", "neon", "monochrome")
        ],
    ]
    original = copy.deepcopy(data)
    migrated = convert(data)
    assert data == original
    validate_current(migrated, references=True)
    assert convert(migrated) == migrated
    assert migrated["effects"][0]["band_colours"] == bands
    palette = next(
        p for p in migrated["palettes"] if p["id"] == migrated["effects"][0]["palette_id"]
    )
    assert [s["colour"] for s in palette["stops"]] == bands
    assert [e["palette_id"] for e in migrated["effects"][1:]] == [
        "sunset",
        "ocean",
        "neon",
        "monochrome",
    ]


@pytest.mark.parametrize(
    "effect",
    [
        "band_colours",
        "band_colours_spatial",
        "gradient",
        "swirl",
        "wave",
        "solid",
        "pulses",
        "fireworks",
        "spectrum_rgb",
        "spectrum_rgb_spatial",
        "mono_pulse",
        "flashes",
        "splotches",
    ],
)
def test_colour_effects_accept_shared_palette_without_changing_onset(effect):
    profile = Profile(effect_type=effect, palette_stops=starter_palettes()[0].stops)
    renderer = ColourModeEffect(profile)
    features = AudioFeatures([0.4] * 30, 0.4, 0.4, 0.4, 0.3, onset=True)
    scene = renderer.render(features, 10)
    colour = scene.color_at(Position(0.2, 0.1, 0.3), 10)
    assert all(np.isfinite([colour.r, colour.g, colour.b]))
    assert features.onset is True


def image_bytes(colours, shares):
    pixels = [c for c, n in zip(colours, shares, strict=True) for _ in range(n)]
    image = Image.new("RGB", (len(pixels), 1))
    image.putdata(pixels)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    "colours,shares",
    [
        ([(255, 0, 0), (0, 255, 0), (0, 0, 255), (240, 220, 0)], [25] * 4),
        ([(0, 0, 0), (255, 0, 0), (0, 200, 255)], [70, 15, 15]),
        ([(255, 0, 0), (250, 4, 1), (0, 255, 0), (0, 0, 255)], [40, 30, 20, 10]),
        ([(220, 50, 10)], [100]),
    ],
)
def test_album_art_deterministic_bounded_stops(colours, shares):
    data = image_bytes(colours, shares)
    first, second = extract(data), extract(data)
    assert first.to_dict() == second.to_dict()
    assert 2 <= len(first.stops) <= 8
    assert first.stops[0]["position"] == 0 and first.stops[-1]["position"] == 100
    assert len(set(s["colour"] for s in first.stops)) >= min(2, len(colours))


def test_art_merge_led_correction_and_no_background_regions():
    rows = merge([((255, 0, 0), 0.4), ((253, 0, 0), 0.1), ((0, 0, 255), 0.3), ((0, 255, 0), 0.2)])
    assert sum(share for _, share in rows) == pytest.approx(1)
    assert len(rows) == 3
    assert punchy((255, 255, 255)) == "#ffffff"
    assert max(hex_rgb(punchy((255, 128, 80)))) <= 0.951
    assert distance((255, 0, 3), (255, 3, 0)) < 0.02
    palette = extract(image_bytes([(0, 0, 0), (255, 0, 0), (0, 200, 255)], [70, 15, 15]))
    assert [s["position"] for s in palette.stops] == [0, 100]


def test_art_cache_hit_and_failure_keep_current(monkeypatch, caplog):
    cache = ArtworkCache()
    palette = cache.palette(image_bytes([(255, 0, 0)], [100]))
    assert cache.palette(image_bytes([(255, 0, 0)], [100])) is palette
    assert cache.palette(b"broken", palette) is palette
    assert cache.palette(b"broken", palette) is palette
    assert caplog.text.count("keeping the current palette") == 1


@pytest.mark.anyio
async def test_track_tag_preferred_disabled_privacy_and_lastfm_fallback():
    settings = MusicSettings(lastfm_enabled=True, lastfm_api_key="SECRET")
    calls = []

    async def transport(params):
        calls.append(params.copy())
        tags = [] if params["method"] == "track.getTopTags" else [{"name": "deep house"}]
        return {"toptags": {"tag": tags}}

    lookup = GenreLookup(lambda: settings, transport=transport)
    track = TrackPosition(title="Song", artist="Artist", genre="Jazz")
    assert (await lookup.resolve(track))["genre"] == "jazz"
    assert calls == []
    settings.lastfm_enabled = False
    assert (await lookup.resolve(TrackPosition(title="Song", artist="Artist")))["genre"] == "other"
    assert calls == []
    settings.lastfm_enabled = True
    result = await lookup.resolve(TrackPosition(title="Song", artist="Artist"))
    assert result["genre"] == "house" and result["source"] == "Last.fm"
    assert [c["method"] for c in calls] == ["track.getTopTags", "artist.getTopTags"]
    await lookup.resolve(TrackPosition(title="Song", artist="Artist"))
    assert len(calls) == 2


@pytest.mark.anyio
async def test_lastfm_timeout_does_not_block_light_task_or_log_key(caplog):
    settings = MusicSettings(lastfm_enabled=True, lastfm_api_key="SECRET")

    async def timeout(params):
        raise TimeoutError("SECRET must not appear in logs")

    lookup = GenreLookup(lambda: settings, transport=timeout)
    ticks = []

    async def lights():
        for _ in range(5):
            ticks.append(1)
            await asyncio.sleep(0)

    await asyncio.gather(lookup.resolve(TrackPosition(artist="A", title="T")), lights())
    assert len(ticks) == 5 and "SECRET" not in caplog.text


def test_mapping_and_rules_manual_wins():
    assert map_tags(["Unknown", "TECH HOUSE"]) == "house"
    assert map_tags(["custom"], {"custom": "jazz"}) == "jazz"
    rules = [GenreRule(genre="house", palette_id="neon", energy_profile_id="party")]
    assert matching_rule(rules, "house") == ("neon", "party")
    assert matching_rule(rules, "house", "ocean", "calm") == ("ocean", "calm")


@pytest.mark.parametrize("mode", ["crossfade", "through-black", "through-white"])
def test_transition_endpoints_midpoint_and_real_time(mode):
    old, new = Colour(0.8, 0.2, 0.1), Colour(0.1, 0.4, 0.9)
    assert transition_colour(old, new, 0, mode) == old
    assert transition_colour(old, new, 1, mode) == new
    expected = (
        old.lerp(new, 0.5)
        if mode == "crossfade"
        else Colour.BLACK
        if mode == "through-black"
        else Colour.WHITE
    )
    assert transition_colour(old, new, 0.5, mode) == expected
    for fps in (10, 30, 120):
        phase = TransitionPhase(mode, 0.7)
        scene = TransitionScene(UniformScene(old), UniformScene(new), phase)
        scene.color_at(ORIGIN, 100)
        for i in range(1, fps):
            scene.color_at(ORIGIN, 100 + i / fps * 0.7)
        assert scene.color_at(ORIGIN, 100.7) == pytest.approx(new)


def test_mid_transition_starts_from_shown_frame_and_early_schedule_waits():
    phase = TransitionPhase(duration=1)
    first = TransitionScene(UniformScene(Colour(1, 0, 0)), UniformScene(Colour(0, 0, 1)), phase)
    first.color_at(ORIGIN, 10)
    shown = first.color_at(ORIGIN, 10.4)
    second = TransitionScene(
        UniformScene(Colour.BLACK),
        UniformScene(Colour(0, 1, 0)),
        TransitionPhase(duration=0.7, baseline=lambda: (first, 10.4)),
    )
    # Rendering/enqueuing it does not consume the transition before playout.
    assert second.phase.start is None
    assert second.color_at(ORIGIN, 11) == shown
    assert second.color_at(ORIGIN, 11.7) == pytest.approx(Colour(0, 1, 0))


@pytest.mark.anyio
async def test_music_director_applies_rule_track_change_and_override(tmp_path):
    from lampastream.models import Coupling

    storage = Storage(tmp_path / "config.json")
    storage.save_genre_rule(GenreRule(genre="house", palette_id="neon"))
    track = [TrackPosition(title="First", artist="Artist", genre="house")]
    calls = []
    director = MusicDirector(
        storage, lambda c, p, a: calls.append(p.id if p else None), lambda: track[0]
    )
    coupling = Coupling()
    await director.step(track[0], coupling)
    assert calls == ["neon"]
    coupling.manual_palette_id = "ocean"
    track[0] = TrackPosition(title="Next", artist="Artist", genre="house")
    await director.step(track[0], coupling)
    assert calls[-1] == "ocean"


def test_cover_art_single_metadata_reader_binary_payload():
    import base64

    image = image_bytes([(255, 0, 0)], [100])
    source = AirPlayTrackPositionSource()

    def wire(code, data):
        return (
            f"<item><type>{b'ssnc'.hex()}</type><code>{code.encode().hex()}</code>"
            f"<length>{len(data)}</length><data>{base64.b64encode(data).decode()}</data></item>"
        ).encode()

    source.feed(wire("PICT", image))
    assert source.read().artwork_data == image
    assert "artwork_data" not in source.read().for_delivery()

@pytest.mark.anyio
async def test_cover_art_decode_does_not_block_output_and_invalidated_metadata_is_discarded():
    import threading
    import time

    source = AirPlayTrackPositionSource()
    entered = threading.Event()
    release = threading.Event()

    def slow_decode(_):
        entered.set()
        release.wait(1)
        return 'core', 'minm', b'Stale track'

    source._decode_record = slow_decode
    task = asyncio.create_task(source.feed_async(b'<item></item>'))
    deadline = time.monotonic() + 1
    while not entered.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(.005)
    assert entered.is_set()
    source.invalidate()
    release.set()
    await task
    assert source.read() is None


def test_band_palette_rotation_changes_with_seconds_without_changing_onset():
    from lampastream.sync_engine import _BandColoursRenderer

    profile = Profile(palette_stops=[{'colour': '#ff0000', 'position': 0},
                                     {'colour': '#0000ff', 'position': 100}],
                      palette_rotation_cps=.25)
    renderer = _BandColoursRenderer()
    first = renderer._working_colours(profile, False, 0)
    second = renderer._working_colours(profile, False, 1)
    assert first != second
    assert renderer._prev_onset is False

@pytest.mark.parametrize('number,expected', [(36, 'house'), (43, 'soul'), (53, 'electronic'),
                                              (65535, 'ID3 genre 65534')])
def test_airplay_numeric_genre_is_decoded_without_a_second_reader(number, expected):
    import base64

    payload = base64.b64encode(number.to_bytes(2, 'big')).decode()
    wire = (f'<item><type>{b"core".hex()}</type><code>{b"gnre".hex()}</code>'
            f'<length>2</length><data>{payload}</data></item>').encode()
    source = AirPlayTrackPositionSource()
    source.feed(wire)
    assert source.read().genre == expected


def test_loudness_filter_scalar_execution_matches_original_recurrence_and_chunking():
    from lampastream.loudness_meter import _Biquad

    b, a = (1.5, -.8, .3), (-.4, .1)
    samples = np.random.default_rng(19).normal(size=(997, 4))
    expected = np.empty_like(samples)
    z1, z2 = np.zeros(4), np.zeros(4)
    for i, xi in enumerate(samples):
        yi = b[0] * xi + z1
        z1 = b[1] * xi - a[0] * yi + z2
        z2 = b[2] * xi - a[1] * yi
        expected[i] = yi
    meter = _Biquad(b, a, 4)
    actual = np.concatenate([meter.process(samples[:271]), meter.process(samples[271:])])
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(meter._z1, z1)
    np.testing.assert_array_equal(meter._z2, z2)


@pytest.mark.anyio
async def test_effective_rule_energy_profile_edits_refresh_without_reactivating(tmp_path):
    from lampastream.models import Coupling, Effect, EnergyProfile

    storage = Storage(tmp_path / 'config.json')
    effect = Effect(id='colour')
    storage.save_effect(effect)
    profile = EnergyProfile(id='genre-energy', high_energy_effect_id='colour')
    storage.save_energy_profile(profile)
    storage.save_genre_rule(GenreRule(genre='house', energy_profile_id=profile.id))
    track = TrackPosition(title='Track', genre='house')
    calls = []
    director = MusicDirector(storage, lambda c, p, a: calls.append(c.energy_profile_id),
                             lambda: track)
    coupling = Coupling(energy_profile_id='base')
    await director.step(track, coupling)
    await director.step(track, coupling)  # settle the resolved selection identity
    count = len(calls)
    assert calls[-1] == profile.id
    profile.blend_response = .6
    storage.save_energy_profile(profile)
    await director.step(track, coupling)
    assert len(calls) == count + 1
    effect.effect_speed = 1.7
    storage.save_effect(effect)
    await director.step(track, coupling)
    assert len(calls) == count + 2
    assert coupling.energy_profile_id == 'base'
