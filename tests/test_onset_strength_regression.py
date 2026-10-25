"""Candidate/current ODF and tied-rank Spearman pins; no SciPy dependency."""
from __future__ import annotations

import pytest
from onset_regression_support import events, expected, strengths, tone_levels
from onset_regression_support import regression_replays as regression_replays

ENABLED = [("combined", "all")] + [("multiband", b) for b in ("all", "bass", "mid", "treble")]


def assert_numeric(actual, pin):
    for key, value in actual.items():
        if value is None or isinstance(value, list) and not value:
            assert value == pin[key]
        else:
            assert value == pytest.approx(pin[key], abs=1e-6)


@pytest.mark.parametrize("fixture", ["clicks-120", "tone-steps"])
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
def test_pin_current_event_strengths(regression_replays, fixture, route, method, band):
    """TIME-01 changes current-frame strength attribution; pin every candidate separately."""
    replay = regression_replays.get(fixture, route, method=method)
    assert_numeric(strengths(replay, band), expected("strength")[f"{fixture}/{method}"][band])


@pytest.mark.parametrize("fixture", ["clicks-120", "tone-steps"])
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: onset strength must be the candidate's raw flux")
def test_contract_event_strengths(regression_replays, fixture, route, method, band):
    """TIME-01 removes the candidate/current ODF mismatch without re-scaling raw strength."""
    replay = regression_replays.get(fixture, route, method=method)
    for row in events(replay, band):
        assert float(row[f"reported_strength_{band}"]) == pytest.approx(
            float(row[f"candidate_strength_{band}"]), abs=1e-6)


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
def test_pin_current_click_strength_below_tenth_fraction(regression_replays, route, method, band):
    """TIME-01: every main click currently reports below 10% of the largest candidate."""
    replay = regression_replays.get("clicks-120", route, method=method)
    actual = strengths(replay, band)["below_tenth_fraction"]
    assert actual == expected("strength")[f"clicks-120/{method}"][band]["below_tenth_fraction"]
    assert actual == 1.


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: click strength must not collapse to current-frame zero")
def test_contract_click_strength_below_tenth_fraction(regression_replays, route, method, band):
    """TIME-01's candidate-attributed clicks should not have zero reported strengths."""
    assert strengths(regression_replays.get("clicks-120", route, method=method), band)[
        "below_tenth_fraction"] == 0.


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
def test_pin_current_tone_rank_and_candidate_strength(regression_replays, route, method, band):
    """TIME-01 preserves rho=1 where already true; bass's all-zero ranks are undefined."""
    replay = regression_replays.get("tone-steps", route, method=method)
    assert_numeric(tone_levels(replay, band), expected("tone_levels")[method][band])


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: tone strength must be monotonic AND candidate-attributed")
def test_contract_tone_rank_and_candidate_strength(regression_replays, route, method, band):
    """TIME-01: rho=1 is necessary but not sufficient when strength names the wrong frame."""
    replay = regression_replays.get("tone-steps", route, method=method)
    values = tone_levels(replay, band)
    assert values["rho"] == pytest.approx(1., abs=1e-12)
    assert values["reported"] == pytest.approx(values["candidate"], abs=1e-6)
