import asyncio
import math
from unittest.mock import MagicMock

import pytest

from lampastream.energy_input import EnergyInput
from lampastream.models import EnergyProfile, Profile
from lampastream.spectrum_engine import ProcessorUpdate
from lampastream.sync_engine import LayerMixer, SyncEngine, _smoothstep
from lampastream.types import AudioFeatures


def features(lufs=-11.0, sustained=0.0, full=.2):
    return AudioFeatures([.2]*10, .2, .2, full, .5,
                         sustained_energy=sustained, loudness_momentary_lufs=lufs)


@pytest.mark.parametrize("mode,expected", [
    ("sustained", 0.0), ("loudness_fixed", 19/22), ("loudness_adaptive", 19/22),
])
def test_selected_input_precedes_unchanged_smoothstep_and_response(mode, expected):
    profile = Profile(energy_source=mode)
    mixer = LayerMixer(profile, profile)
    mixer.render(features(), 0)
    assert mixer.last_energy_input == pytest.approx(expected)
    assert mixer.mix == pytest.approx(.1 * _smoothstep(expected, .3, .7))


def test_constant_loud_programme_stays_high_in_fixed_mode_and_default_is_unchanged():
    fixed = EnergyInput(Profile(energy_source="loudness_fixed"))
    sustained = EnergyInput(Profile())
    for second in range(180):
        assert fixed.select(features(), second) == pytest.approx(19/22)
        assert sustained.select(features(), second) == 0
    assert sustained.select(features(sustained=None, full=.17), 181) == .17


@pytest.mark.parametrize("mode", ["loudness_fixed", "loudness_adaptive"])
@pytest.mark.parametrize("value", [None, -math.inf, math.inf, math.nan])
def test_silence_and_missing_input_are_zero_without_training(mode, value):
    selector = EnergyInput(Profile(energy_source=mode))
    before = selector.adaptive_floor, selector.adaptive_ceiling
    assert selector.select(features(value), 0) == 0
    assert selector.select(features(value), 100) == 0
    assert (selector.adaptive_floor, selector.adaptive_ceiling) == before


def test_fixed_clamps_and_honours_custom_bounds():
    selector = EnergyInput(
        Profile(energy_source="loudness_fixed", lufs_floor=-40, lufs_ceiling=-10))
    for value, expected in [(-50, 0), (-40, 0), (-25, .5), (-10, 1), (0, 1)]:
        assert selector.select(features(value), 0) == expected


def test_adaptive_expands_quickly_contracts_slowly_and_keeps_six_lu_span():
    selector = EnergyInput(Profile(energy_source="loudness_adaptive"))
    selector.select(features(-20), 0)
    before = selector.adaptive_ceiling - selector.adaptive_floor
    selector.select(features(0), 1)
    raised = selector.adaptive_ceiling
    assert raised > -4
    assert selector.adaptive_ceiling - selector.adaptive_floor > before
    selector.select(features(-20), 2)
    assert -1 < selector.adaptive_ceiling - raised < 0
    for second in range(3, 1000):
        value = selector.select(features(-20), second)
        assert 0 <= value <= 1
        assert selector.adaptive_ceiling - selector.adaptive_floor >= 6 - 1e-9
    assert value == pytest.approx(.5, abs=.001)


@pytest.mark.parametrize("kwargs", [
    {"energy_source": "unknown"}, {"lufs_floor": -8, "lufs_ceiling": -30},
    {"lufs_floor": -8, "lufs_ceiling": -8}, {"lufs_floor": math.nan},
    {"lufs_ceiling": math.inf}, {"adaptation_tau_s": 0}, {"adaptation_tau_s": math.inf},
])
def test_profile_validation(kwargs):
    with pytest.raises(ValueError):
        EnergyProfile(**kwargs)
    with pytest.raises(ValueError):
        Profile(**kwargs)


def test_sync_engine_uses_freshest_loudness_without_mutating_spectrum_publication(monkeypatch):
    from test_band_normalise import pipeline, publish
    cap = pipeline()
    record = publish(cap, [.2]*10, 960)
    cap._publish_by_interval(
        epoch_id="test", spectrum_updates=[], other_updates=[ProcessorUpdate(
            "loudness_analyzer", 0, 480, loudness_momentary_lufs=-11,
        )], clamp_end=None,
    )
    engine = SyncEngine(None, Profile(energy_source="loudness_fixed"), analyser=cap)

    async def stop_after_tick(_):
        raise asyncio.CancelledError

    monkeypatch.setattr("lampastream.sync_engine.asyncio.sleep", stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.run(MagicMock()))
    assert engine.last_energy_input == pytest.approx(19/22)
    assert record.features.loudness_momentary_lufs is None
    assert record.features.full == .2


def peak_features(level, lufs=None):
    result = features(lufs=lufs)
    result.level = level
    return result


def test_peak_normalisation_attack_release_and_clamping():
    selector = EnergyInput(Profile(energy_source="peak_envelope"))
    assert selector.select(peak_features(.5), 0) == 1
    assert selector.select(peak_features(1), .01) == 1
    raised = .5 + (1 - math.exp(-.01 / .05)) * .5
    assert selector._peak_envelope == pytest.approx(raised)
    assert .5 < raised < 1  # A single transient is not adopted instantly.
    result = selector.select(peak_features(.5), .02)
    released = raised + (1 - math.exp(-.01 / 2)) * (.5 - raised)
    assert selector._peak_envelope == pytest.approx(released)
    assert raised - released < raised - .5
    assert result == pytest.approx(.5 / released)
    assert selector.select(peak_features(0), .03) == 0
    before = selector._peak_envelope
    selector.select(peak_features(.1), .02)  # Backward time cannot advance the filter.
    assert selector._peak_envelope == before


@pytest.mark.parametrize("level", [None, math.nan, math.inf, -math.inf])
def test_peak_missing_level_does_not_train_or_use_lufs(level):
    selector = EnergyInput(Profile(energy_source="peak_envelope"))
    assert selector.select(peak_features(level, lufs=-1), 0) == 0
    assert selector._peak_envelope is None
    selector.select(peak_features(.8), 1)
    assert selector.select(peak_features(level, lufs=-1), 100) == 0
    assert selector._peak_envelope == .8
    selector.select(peak_features(.4), 100.01)
    assert selector._peak_envelope == pytest.approx(.8 + (1 - math.exp(-.01 / 2)) * -.4)


def test_peak_auto_ignores_manual_values_and_manual_honours_them():
    auto = EnergyInput(Profile(energy_source="peak_envelope", peak_attack_s=10, peak_release_s=-1))
    manual = EnergyInput(Profile(energy_source="peak_envelope", peak_envelope_auto=False,
                                 peak_attack_s=.2, peak_release_s=4))
    assert (auto.peak_attack_s, auto.peak_release_s) == (.05, 2)
    assert (manual.peak_attack_s, manual.peak_release_s) == (.2, 4)
    for selector in (auto, manual):
        selector.select(peak_features(.5), 0)
        selector.select(peak_features(1), .01)
    assert auto._peak_envelope > manual._peak_envelope


@pytest.mark.parametrize("attack,release", [(0, 2), (-1, 2), (.05, 0), (.05, -2),
                                           (2, 2), (3, 2), (math.nan, 2), (.05, math.inf)])
@pytest.mark.parametrize("model", [Profile, EnergyProfile])
def test_manual_peak_validation(model, attack, release):
    with pytest.raises(ValueError):
        model(energy_source="peak_envelope", peak_envelope_auto=False,
              peak_attack_s=attack, peak_release_s=release)


def test_peak_near_constant_mastered_level_retains_variation():
    selector = EnergyInput(Profile(energy_source="peak_envelope"))
    # Small RMS modulation survives even when momentary LUFS is completely flat.
    results = [selector.select(peak_features(.8 + .04 * math.sin(i * .1), lufs=-5), i * .01)
               for i in range(12000)]
    settled = results[-1000:]
    assert max(settled) - min(settled) > .07
    assert sum(settled) / len(settled) < .97
    assert all(0 <= result <= 1 for result in results)


def test_peak_exact_constant_limit_and_silence_are_explicit():
    selector = EnergyInput(Profile(energy_source="peak_envelope"))
    assert selector.select(peak_features(0), 0) == 0
    selector = EnergyInput(Profile(energy_source="peak_envelope"))
    for i in range(1000):
        assert selector.select(peak_features(.8), i * .01) == 1


def test_peak_profile_roundtrip_and_legacy_defaults():
    profile = EnergyProfile(energy_source="peak_envelope", peak_envelope_auto=False,
                            peak_attack_s=.1, peak_release_s=3)
    assert EnergyProfile.from_dict(profile.to_dict()) == profile
    legacy = EnergyProfile.from_dict({"name": "Existing"})
    assert legacy.energy_source == Profile().energy_source == "sustained"
    assert (legacy.peak_envelope_auto, legacy.peak_attack_s, legacy.peak_release_s) == (
        True, .05, 2)


def test_sync_engine_copies_latest_rms_into_peak_input(monkeypatch):
    from test_band_normalise import pipeline, publish
    cap = pipeline()
    record = publish(cap, [.2]*10, 960)
    cap._publish_by_interval(
        epoch_id="test", spectrum_updates=[], other_updates=[ProcessorUpdate(
            "loudness_analyzer", 0, 480, level=.6,
        )], clamp_end=None,
    )
    engine = SyncEngine(None, Profile(energy_source="peak_envelope"), analyser=cap)

    async def stop_after_tick(_):
        raise asyncio.CancelledError

    monkeypatch.setattr("lampastream.sync_engine.asyncio.sleep", stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.run(MagicMock()))
    assert engine.last_energy_input == 1
    assert record.features.level is None  # Rendering must not rewrite publications.
