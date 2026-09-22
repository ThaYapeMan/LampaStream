"""Band Colours renders and playback consume existing analysis without altering it."""

import colorsys
from dataclasses import replace

import pytest

from lampastream.models import Effect, Profile
from lampastream.sync_engine import (
    ColourModeEffect,
    _band_edges,
    _BandColoursRenderer,
    _BandColoursSpatialRenderer,
    _hz_to_frac,
)
from lampastream.types import AudioFeatures, Colour, Position

TABLE = ['#FF0000', '#00FF00', '#0000FF']
ORIGIN = Position(0, 0, 0)


def frame(bars=(.2, .4, .6), onset=False):
    return AudioFeatures(list(bars), 0, 0, 0, .5, onset=onset)


def rgb(colour):
    return colour.r, colour.g, colour.b


@pytest.mark.parametrize('count', [3, 5, 8])
@pytest.mark.parametrize('lower,upper', [(20, 20000), (50, 12000)])
def test_band_edges_follow_log_frequency_range(count, lower, upper):
    edges = _band_edges(count, lower, upper)
    assert edges == pytest.approx([i / count for i in range(1, count)])
    for i, edge in enumerate(edges, 1):
        hz = lower * (upper / lower) ** (i / count)
        assert edge == pytest.approx(_hz_to_frac(hz, lower, upper))


def test_composite_sums_colour_channels_with_band_energy_and_sensitivity():
    profile = Profile(effect_type='band_colours', band_colours=['#FF8000', '#00FF80', '#8000FF'],
        sensitivity=2)
    actual = ColourModeEffect(profile).render(frame(), 0).color_at(ORIGIN, 0)
    assert rgb(actual) == pytest.approx((min(1, .4 + 1.2 * 128 / 255),
                                        min(1, .4 * 128 / 255 + .8), 1))
    assert rgb(ColourModeEffect(profile).render(frame([]), 0).color_at(ORIGIN, 0)) == (0, 0, 0)


@pytest.mark.parametrize('count', [3, 5, 8])
def test_spatial_anchors_and_neighbour_cross_fades(count):
    table = ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#00FFFF', '#FF00FF', '#FFFFFF',
        '#888888'][:count]
    profile = Profile(effect_type='band_colours_spatial', band_colours=table)
    scene = ColourModeEffect(profile).render(frame([.5] * count), 0)
    colours = [tuple(int(hex_colour[i:i+2], 16) / 510 for i in (1, 3, 5)) for hex_colour in table]
    for i, expected in enumerate(colours):
        x = -1 + 2 * i / (count - 1)
        assert rgb(scene.color_at(Position(x, 0, 0), 0)) == pytest.approx(expected)
        if i < count - 1:
            halfway = x + 1 / (count - 1)
            assert rgb(scene.color_at(Position(halfway, 0, 0), 0)) == pytest.approx(
                [(a + b) / 2 for a, b in zip(expected, colours[i+1], strict=True)])
    assert scene.color_at(Position(-10, 0, 0), 0) == scene.color_at(Position(-1, 0, 0), 0)


@pytest.mark.parametrize('renderer_type', [_BandColoursRenderer, _BandColoursSpatialRenderer])
def test_loop_advances_only_on_beat_rising_edges(renderer_type):
    profile = Profile(band_colours=TABLE.copy(), band_playback='loop')
    renderer = renderer_type()
    trace = []
    for t, onset in enumerate([True, True, False, True, False]):
        renderer.render(profile, frame(onset=onset), t)
        trace.append([rgb(c) for c in renderer._colours])
    r, g, b = (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)
    assert trace == [[b, r, g], [b, r, g], [b, r, g], [g, b, r], [g, b, r]]
    assert profile.band_colours == TABLE
    other = renderer_type()
    other.render(profile, frame(), 0)
    assert [rgb(c) for c in other._colours] == [r, g, b]


def test_timer_advances_once_per_interval_and_resets_on_time_rewind_or_configuration_change():
    profile = Profile(band_colours=TABLE, band_playback='loop', band_advance='timer',
        band_advance_interval_s=2)
    renderer = _BandColoursRenderer()
    for t, expected in [(10, 0), (11.9, 0), (12, 2), (12.1, 2), (20, 1), (0, 1), (1, 1), (2, 0)]:
        renderer.render(profile, frame(onset=True), t)
        assert rgb(renderer._colours[0]) == tuple(float(i == expected) for i in range(3))
    renderer.render(replace(profile, band_colours=['#FFFFFF'] * 3), frame(), 3)
    assert renderer._colours == [Colour(1, 1, 1)] * 3


def test_static_never_advances_and_flash_is_independent_of_held_onset():
    profile = Profile(band_colours=TABLE, onset_flash_intensity=.5)
    renderer = _BandColoursRenderer()
    for t in [0, 10, 20]:
        colour = renderer.render(profile, frame(onset=True), t).color_at(ORIGIN, t)
        assert rgb(colour) == pytest.approx((.6, .7, .8))
        assert renderer._colours == [Colour(1, 0, 0), Colour(0, 1, 0), Colour(0, 0, 1)]


@pytest.mark.parametrize('count', [3, 5, 8])
def test_shuffle_draws_nonzero_rotations_without_repeats_across_refills(count):
    renderer = _BandColoursRenderer()
    renderer._rng.seed(42)
    table = [f'#{i:06X}' for i in range(count)]
    profile = Profile(band_colours=table, band_playback='shuffle',
                      band_advance='timer', band_advance_interval_s=1)
    renderer.render(profile, frame(), 0)
    offsets = []
    for t in range(1, (count - 1) * 10 + 1):
        before = renderer._colours.copy()
        renderer.render(profile, frame(), t)
        offset = renderer._last_offset
        offsets.append(offset)
        assert offset != 0
        assert renderer._colours == before[-offset:] + before[:-offset]
        assert renderer._colours != before
    for i in range(0, len(offsets), count - 1):
        assert set(offsets[i:i + count - 1]) == set(range(1, count))
    assert all(a != b for a, b in zip(offsets, offsets[1:], strict=False))
    assert profile.band_colours == table


def test_random_uses_bounded_hsl_and_mix_samples_original_table_with_duplicates():
    renderer = _BandColoursRenderer()
    renderer._rng.seed(1)
    profile = Profile(band_colours=TABLE, band_playback='random')
    renderer.render(profile, frame(onset=True), 0)
    for colour in renderer._colours:
        _, lightness, saturation = colorsys.rgb_to_hls(*rgb(colour))
        assert (lightness, saturation) == pytest.approx((.55, .85))
    before = renderer._colours.copy()
    renderer.render(profile, frame(onset=True), 1)
    assert renderer._colours == before
    renderer.render(profile, frame(), 2)
    renderer.render(profile, frame(onset=True), 3)
    assert renderer._colours != before
    profile.band_playback = 'mix'
    renderer._rng.seed(2)
    renderer.render(profile, frame(onset=True), 4)
    assert renderer._colours == [Colour(1, 0, 0)] * 3
    assert profile.band_colours == TABLE


@pytest.mark.parametrize('kwargs', [
    {'band_colours': []}, {'band_colours': ['#FFFFFF'] * 9}, {'band_colours': ['red'] * 3},
    {'band_colours': ['#abc'] * 3}, {'band_colours': [None] * 3},
    {'band_playback': 'unknown'}, {'band_advance': 'unknown'},
    {'band_advance_interval_s': 0}, {'band_advance_interval_s': float('inf')},
    {'band_advance_interval_s': float('nan')},
])
def test_profile_rejects_invalid_band_configuration(kwargs):
    with pytest.raises(ValueError):
        Profile(**kwargs)


def test_older_effects_default_and_round_trip_without_migration_or_shared_lists():
    first, second = Effect.from_dict({'name': 'Old'}), Effect()
    assert first.band_colours == ['#F42525', '#25F425', '#2525F4']
    assert first == Effect.from_dict(first.to_dict())
    first.band_colours[0] = '#FFFFFF'
    assert second.band_colours[0] == '#F42525'


def test_persisted_colour_lists_validate_without_migrating_older_effects():
    from lampastream.schema import empty_config, validate_current

    data = empty_config()
    data['effects'] = [{'id': 'old', 'name': 'Old effect'}]
    validate_current(data)
    data['effects'] = [Effect().to_dict()]
    validate_current(data)
    data['effects'][0]['band_colours'] = ['#FFFFFF', 123, '#000000']
    with pytest.raises(ValueError):
        validate_current(data)
