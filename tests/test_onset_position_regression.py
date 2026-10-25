"""Truth/candidate/availability relationships, including stereo and disabled bands."""
from __future__ import annotations

import numpy as np
import pytest
from onset_regression_support import (
    BANDS,
    HOP,
    POSITION_FIXTURES,
    events,
    expected,
    panning_halves,
    positions,
)
from onset_regression_support import (
    regression_replays as regression_replays,
)


@pytest.mark.parametrize("fixture", POSITION_FIXTURES)
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
def test_pin_current_fixture_positions(regression_replays, fixture, route, method):
    """TIME-01 changes candidate attribution; combined intentionally has no band flags."""
    replay = regression_replays.get(fixture, route, method=method)
    measured = {band: positions(replay, band) for band in BANDS}
    assert measured == expected("position")[f"{fixture}/{method}"]
    # Explicitly assert the hop conversion as well as the sample-domain pins.
    for band in BANDS:
        for kind in ("availability", "candidate"):
            for key in ("median_samples", "max_abs_samples"):
                actual = measured[band][kind][key]
                pin = expected("position")[f"{fixture}/{method}"][band][kind][key]
                if actual is not None:
                    assert actual / HOP == pytest.approx(pin / HOP, abs=1 / HOP)


ENABLED = [("combined", "all")] + [("multiband", b) for b in BANDS]


@pytest.mark.parametrize("fixture", POSITION_FIXTURES)
@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method,band", ENABLED)
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: candidate must identify the event, with constant lookahead")
def test_contract_fixture_positions(regression_replays, fixture, route, method, band):
    """TIME-01 must define event reference and its constant availability lookahead."""
    replay = regression_replays.get(fixture, route, method=method)
    found = events(replay, band)
    assert found
    candidates = np.array([int(row[f"candidate_sample_{band}"]) for row in found])
    distance = abs(candidates[:, None] - replay["truth"][None, :])
    assert np.all(np.min(distance, axis=0) <= HOP)
    gaps = np.array([int(r["availability_sample"]) - int(r[f"candidate_sample_{band}"])
                     for r in found])
    # TIME-01 chooses the authoritative numeric value. Require one constant,
    # not the multiple transport-chunk-dependent values seen at 24 kHz today.
    assert np.all(gaps == gaps[0])


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
def test_pin_current_panning_position_and_strength(regression_replays, route, method):
    """TIME-01: pin left (<5s) versus right (>=5s) window positions and both strengths."""
    replay = regression_replays.get("panning", route, method=method)
    bands = BANDS if method == "multiband" else ("all",)
    for band in bands:
        for actual, pin in zip(panning_halves(replay, band), expected("panning")[method][band],
                               strict=True):
            for key in actual:
                assert actual[key] == pytest.approx(pin[key], abs=1e-6)


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: panned click event position and strength belong to candidate")
def test_contract_panning_position_and_strength(regression_replays, route, method):
    """TIME-01 should preserve stereo detection while removing current-frame attribution."""
    replay = regression_replays.get("panning", route, method=method)
    for band in (BANDS if method == "multiband" else ("all",)):
        for row in events(replay, band):
            candidate = int(row[f"candidate_sample_{band}"])
            assert min(abs(replay["truth"] - candidate)) <= HOP
            assert float(row[f"reported_strength_{band}"]) == pytest.approx(
                float(row[f"candidate_strength_{band}"]), abs=1e-6)


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
def test_pin_current_antiphase_detection(regression_replays, route, method):
    """TIME-01 preserves phase-safe detection: combined=19; multiband union=20 today."""
    replay = regression_replays.get("anti-phase", route, method=method)
    assert {b:positions(replay, b) for b in BANDS} == expected("position")[f"anti-phase/{method}"]
    assert len(events(replay)) == (19 if method == "combined" else 20)


@pytest.mark.parametrize("route", ["normal", "timestamped"])
@pytest.mark.parametrize("method", ["combined", "multiband"])
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="TIME-01: phase-safe events must also have correct candidate attribution")
def test_contract_antiphase_detection_and_attribution(regression_replays, route, method):
    """TIME-01 retains detection of L=-R and supplies event-aligned candidates."""
    replay = regression_replays.get("anti-phase", route, method=method)
    assert abs(len(events(replay)) - len(replay["truth"])) <= 1
    candidates = np.array([int(r["candidate_sample_all"]) for r in events(replay)])
    assert np.all(np.min(abs(candidates[:, None] - replay["truth"][None, :]), axis=0) <= HOP)
