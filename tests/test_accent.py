"""ACCENT-01 production-scene acceptance, local synthetic PCM only."""
from __future__ import annotations

import asyncio
import colorsys
import json
from dataclasses import replace
from pathlib import Path

import pytest
from replay_chain import Replay, decode, parser

from lampastream.accent import AccentLayer
from lampastream.models import EFFECT_IDS, Effect, Profile
from lampastream.types import AudioFeatures, Colour, OnsetEvent, Position, UniformScene

FIXTURES = Path(__file__).parent / "fixtures/replay"
EFFECTS = sorted(EFFECT_IDS - {"none"})

EngineProfile = Profile


def Profile(**kwargs):
    return EngineProfile(diagnostic_onsets=True, **kwargs)


@pytest.fixture(scope="module")
def accent_replay(tmp_path_factory):
    base = tmp_path_factory.mktemp("accents")
    data = json.loads((FIXTURES / "default-config.json").read_text())
    cache = {}

    def run(effect, route, fast=False, fixture="clicks-120"):
        key = effect, route, fast, fixture
        if key in cache:
            return cache[key]
        config = base / f'{effect}.json'
        for item in data["configuration"]["effects"]:
            item["effect_type"] = effect
        config.write_text(json.dumps(data))
        args = parser().parse_args(["--diagnostic-onsets",
            "--input", str(FIXTURES / f"{fixture}.wav"),
            "--config", str(config), "--route", route,
            "--render-hz", "60" if fast else "30", "--room",
            str(FIXTURES.parent / "rooms" / ("two-channel-fast.json" if fast
                                            else "two-channel.json")),
            "--out", str(base / '-'.join(map(str, key)))])
        replay = Replay(args)
        try:
            pcm, rate, fmt = decode(args.input, 0, None)
            replay.analyse(pcm, rate)
            asyncio.run(replay.run())
            replay.save(fmt)
        finally:
            replay.pipeline.stop()
        cache[key] = replay
        return replay
    return run


@pytest.mark.parametrize("effect", EFFECTS)
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("fast", [False, True], ids=["25Hz-8bit", "60Hz-16bit"])
def test_every_effect_accents_every_received_event(accent_replay, effect, route, fast):
    replay = accent_replay(effect, route, fast)
    assert replay.counters()["events"]["all"]["lost"] == 0
    assert replay.counters()["events"]["all"]["received"] == 19
    codes = (1 << replay.output.capabilities.colour_depth_bits)-1
    hold = replay.output.capabilities.min_visible_hold_s
    for data in replay.engine.event_records.values():
        start = data["event_time"]
        rows = [r for r in replay.renders if start <= r["render_argument_s"] < start+hold]
        lifts = [max(r[f"post_{c}"]-r[f"pre_{c}"] for c in 'rgb')*codes for r in rows]
        assert max(lifts, default=0) >= 8, (effect, start, max(lifts, default=0))
        # Check displayed scenes, not just renders that a scheduler might drop.
        rendered = {r["render_id"] for r in replay.renders if
            start <= r["render_argument_s"] < start+.5 and
            max(r[f"post_{c}"]-r[f"pre_{c}"] for c in 'rgb')*codes >= 8}
        sends = sorted({r["virtual_time_s"] for r in replay.output.rows
                        if r["scene_id"] in rendered})
        assert sends
        assert sends[-1]-sends[0]+1/replay.output.capabilities.update_hz >= hold-1e-6
    for row in replay.renders:
        before = colorsys.rgb_to_hsv(*(row[f'pre_{c}'] for c in 'rgb'))
        after = colorsys.rgb_to_hsv(*(row[f'post_{c}'] for c in 'rgb'))
        if before[1] > 1e-6 and before[2] > 1e-6:
            delta = abs(before[0]-after[0])
            assert min(delta, 1-delta)*360 <= 1
        assert sum(row[f'post_{c}'] >= 1 for c in 'rgb') <= 1


def feature(band="bass", count=1):
    e = OnsetEvent(('e', band, 0), 'e', 0, 480, 1, .8, 2., .75,
                   frozenset({band}), band)
    return AudioFeatures([], 0, 0, 0, .5, onset_events=(e,), onset_strength=.8,
                         onset_envelope=.8, onset_count_since_render=count,
                         **{f'onset_envelope_{band}': .8})


def test_band_weights_curve_and_palette_counts():
    scene = UniformScene(Colour(.1, .2, .3))
    layer = AccentLayer()
    bass = layer.render(scene, feature(), Profile())
    treble = layer.render(scene, feature('treble'), Profile())
    assert bass.accent_value/treble.accent_value == pytest.approx(2.5)
    curved = layer.render(scene, feature(), Profile(accent_strength_curve=2))
    assert curved.accent_value/bass.accent_value == pytest.approx(.8)
    profile = Profile(accent_mode='palette_step', accent_palette_step=.13)
    assert layer.render(scene, feature(count=2), profile).phase == pytest.approx(.26)
    assert layer.render(scene, feature(count=3), profile).phase == pytest.approx(.65)


def test_off_is_exact_and_defaults_roundtrip():
    scene = UniformScene(Colour(.2, .4, .7))
    assert AccentLayer().render(scene, feature(), Profile(accent_mode='off')) is scene
    effect = Effect.from_dict({'id': 'legacy'})
    assert effect.accent_mode == 'lift' and effect.accent_amount == .35
    assert Effect.from_dict(effect.to_dict()).to_dict() == effect.to_dict()


def test_spatial_selection_is_deterministic():
    points = (Position(-.5, 0, 0), Position(1, 0, 0), Position(0, 0, 0))
    scene = UniformScene(Colour(.1, .2, .3))
    profile = Profile(accent_spatial='by_band')
    mid = AccentLayer().render(scene, feature('mid'), profile, points)
    assert [mid.value_at(p)>0 for p in mid.positions] == [True, False, True]
    treble = AccentLayer().render(scene, feature('treble'), profile, points)
    assert [treble.value_at(p)>0 for p in treble.positions] == [False, False, True]
    bass = AccentLayer().render(scene, feature(), profile, points)
    assert len({bass.value_at(p) for p in points}) == 1
    silent = replace(feature(), onset_events=(), onset_strength=0, onset_envelope=0,
                     onset_envelope_bass=0, onset_count_since_render=0)
    assert AccentLayer().render(scene, silent, profile).accent_value == 0


@pytest.mark.parametrize('case', json.loads(
    (FIXTURES.parent / 'accent-off-lat01.json').read_text())['cases'],
    ids=lambda c: c['fixture']+'-'+c['route'])
def test_accent_off_route01_byte_identity(tmp_path, case):
    import hashlib
    data = json.loads((FIXTURES / 'default-config.json').read_text())
    for effect in data['configuration']['effects']:
        effect['accent_mode'] = 'off'
    config = tmp_path/'config.json'
    config.write_text(json.dumps(data))
    args = parser().parse_args(["--diagnostic-onsets",
            '--input', str(FIXTURES/f"{case['fixture']}.wav"),
        '--config', str(config), '--route', case['route'], '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    try:
        pcm, rate, fmt = decode(args.input, 0, None)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        replay.save(fmt)
        for name, expected in case['hashes'].items():
            assert hashlib.sha256((args.out/name).read_bytes()).hexdigest() == expected, name
    finally:
        replay.pipeline.stop()


@pytest.mark.parametrize('fixture', ['panning', 'anti-phase'])
def test_multiband_fixture_weight_ratio(tmp_path, fixture):
    data = json.loads((FIXTURES/'default-config.json').read_text())
    data['configuration']['analysers'][0]['onset_method'] = 'multiband'
    config = tmp_path/'config.json'
    config.write_text(json.dumps(data))
    args = parser().parse_args(["--diagnostic-onsets",
            '--input', str(FIXTURES/f'{fixture}.wav'),
        '--config', str(config), '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    try:
        pcm, rate, _ = decode(args.input, 0, None)
        replay.analyse(pcm, rate)
        measured = {b: [] for b in ('bass', 'treble')}
        for record in replay.records:
            for event in record.features.onset_events:
                for band in event.bands & measured.keys():
                    view = replace(feature(band), onset_events=(event,),
                        onset_strength=event.strength,
                        **{f'onset_envelope_{band}': event.strength})
                    scene = AccentLayer().render(UniformScene(Colour.BLACK), view, replay.high)
                    measured[band].append(scene.accent_value/(event.strength*event.confidence))
        assert measured['bass'] and measured['treble']
        ratio = sum(measured['bass'])/len(measured['bass']) / (
            sum(measured['treble'])/len(measured['treble']))
        assert ratio == pytest.approx(1/.4)
    finally:
        replay.pipeline.stop()


def test_zero_weights_and_disabled_effect_stay_dark():
    scene = UniformScene(Colour.BLACK)
    profile = Profile(accent_band_weights={'bass': 0., 'mid': 0., 'treble': 0.})
    assert AccentLayer().render(scene, feature(), profile).accent_value == 0
    assert AccentLayer().render(scene, feature(), Profile(effect_type='none')) is scene


@pytest.mark.parametrize('fixture', ['clicks-128', 'clicks-174'])
@pytest.mark.parametrize('effect', EFFECTS)
def test_lift_preserves_angle_and_headroom_on_other_click_fixtures(
        accent_replay, effect, fixture):
    replay = accent_replay(effect, 'normal', fixture=fixture)
    for row in replay.renders:
        before = colorsys.rgb_to_hsv(*(row[f'pre_{c}'] for c in 'rgb'))
        after = colorsys.rgb_to_hsv(*(row[f'post_{c}'] for c in 'rgb'))
        if before[1] > 1e-6 and before[2] > 1e-6:
            delta = abs(before[0]-after[0])
            assert min(delta, 1-delta)*360 <= 1
        assert sum(row[f'post_{c}'] >= 1 for c in 'rgb') <= 1
