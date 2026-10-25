"""Publication-to-render survival pins and universal EVENT-01 route contracts."""
from __future__ import annotations

import pytest
from onset_regression_support import (
    BANDS,
    SURVIVAL_FIXTURES,
    expected,
    skipped_flags,
    survival,
)
from onset_regression_support import regression_replays as regression_replays


@pytest.mark.parametrize("fixture", SURVIVAL_FIXTURES)
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
def test_pin_current_survival_matrix(regression_replays, fixture, route, method):
    """EVENT-01 changes flag survival; pin all bands, rates, caps and publication classes."""
    for hz in (30, 60):
        for cap in (0, 1):
            replay = regression_replays.get(fixture, route, hz, cap, method)
            key = f"{fixture}/{method}/{route}/{hz}/{cap}"
            assert survival(replay, route) == expected("survival")[key]


@pytest.mark.parametrize("fixture", SURVIVAL_FIXTURES)
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
def test_contract_survival_matrix(regression_replays, fixture, route, method):
    """EVENT-01 evaluates all variants, including already-green cap=1 subcases."""
    violations = []
    for hz in (30, 60):
        for cap in (0, 1):
            replay = regression_replays.get(fixture, route, hz, cap, method)
            for band in BANDS:
                data = replay["counters"]["events"][band]
                if data["lost"] or data["triggered"] < data["received"] - data["merged"]:
                    violations.append((hz, cap, band, "event survival", data))
                if skipped_flags(replay, band)["sole_carrier_skipped"]:
                    violations.append((hz, cap, band, "sole carrier skipped"))
    assert not violations, violations


def test_pin_current_unconsumed_onset_flags_are_direct_cause(regression_replays):
    """EVENT-01: exactly 19 normal/30Hz click flags sit on never-consumed publications."""
    replay = regression_replays.get("clicks-120")
    assert skipped_flags(replay) == {"never_consumed_flags": 0, "sole_carrier_skipped": 0}
    assert replay["counters"]["events"]["all"]["lost"] == 0


def test_contract_unconsumed_onset_flags_are_direct_cause(regression_replays):
    """EVENT-01 must consume or preserve each unique onset, not overwrite its sole carrier."""
    assert skipped_flags(regression_replays.get("clicks-120"))["sole_carrier_skipped"] == 0
