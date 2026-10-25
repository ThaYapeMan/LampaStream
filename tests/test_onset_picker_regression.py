"""Dixon timing/strength pins and deliberately red TIME-01 contracts."""
from __future__ import annotations

import numpy as np
import pytest

from lampastream.sync_engine import OnsetDetector

CASES = [({50: 10.0}, [51]), ({50: 10.0, 70: 10.0}, [51, 71]),
         ({50: 10.0, 52: 3.0}, [51])]


def series(peaks):
    # Feed the public precomputed-ODF entry point: it normalizes these raw
    # nonnegative flux values internally. A zero tail makes the mismatch clear.
    values = np.r_[np.full(50, .1), np.zeros(40)]
    for frame, strength in peaks.items():
        values[frame] = strength
    return values


def drive(values):
    picker = OnsetDetector()
    hits = []
    for frame, value in enumerate(values):
        result = picker.process_odf(float(value))
        if result[0]:
            hits.append((frame, result[1], getattr(picker, "last_event", None)))
    return picker, hits


@pytest.mark.parametrize("peaks,reported", CASES)
def test_pin_current_peak_candidate_and_strength(peaks, reported):
    """TIME-01 changes current-frame attribution; only the larger close peak fires."""
    _, hits = drive(series(peaks))
    assert [frame for frame, _, _ in hits] == reported
    assert [strength for _, strength, _ in hits] == pytest.approx([10.] * len(reported), abs=1e-12)
    assert all(frame - 1 in peaks for frame, _, _ in hits)
    assert all(peaks[frame - 1] == 10 for frame, _, _ in hits)


@pytest.mark.parametrize("peaks,reported", CASES)
def test_contract_peak_candidate_and_strength(peaks, reported):
    """TIME-01 must supply candidate metadata without confusing it with decision time."""
    _, hits = drive(series(peaks))
    assert len(hits) == len(reported)
    for (availability, _, event), expected in zip(hits, reported, strict=True):
        assert event is not None, "Picker currently exposes only (onset, current_flux)"
        assert event.candidate_frame == expected - 1
        assert event.candidate_strength == pytest.approx(peaks[expected - 1], abs=1e-12)
        assert event.availability_frame == availability == expected


@pytest.mark.parametrize("peaks,reported", CASES)
def test_pin_current_silence_trains_reference_and_adds_transition_onset(peaks, reported):
    """Phase 2: silence freezes statistics; confirmation is one hop after the candidate."""
    _, ordinary = drive(series(peaks))
    _, padded = drive(np.r_[np.zeros(500), series(peaks)])
    assert [(f, s) for f, s, _ in ordinary] == [(f, 10.) for f in reported]
    assert [(f, s) for f, s, _ in padded] == [(500 + f, 10.) for f in reported]
    picker = OnsetDetector()
    for _ in range(50):
        picker.process_odf(.2)
    trained = picker._flux_ema
    for _ in range(500):
        picker.process_odf(0.)
    assert trained == pytest.approx(.198969244958536, abs=1e-15)
    assert picker._flux_ema == pytest.approx(trained, abs=1e-12)


@pytest.mark.parametrize("peaks,reported", CASES)
def test_contract_silence_preserves_reference_and_peak_decisions(peaks, reported):
    """TIME-01 should not create an extra onset when low flux resumes after silence."""
    _, hits = drive(np.r_[np.zeros(500), series(peaks)])
    assert [f - 500 for f, _, _ in hits] == reported
    picker = OnsetDetector()
    for _ in range(50):
        picker.process_odf(.2)
    trained = picker._flux_ema
    for _ in range(500):
        picker.process_odf(0.)
    assert picker._flux_ema == pytest.approx(trained, abs=1e-12)
