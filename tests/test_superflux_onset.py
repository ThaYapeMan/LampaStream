"""Tests for SuperfluxStftPipeline — vibrato-suppressing onset detection.

Two key behavioral properties are verified:

1. Vibrato suppression: a signal that simulates vibrato (energy alternating
   between neighboring FFT bins) triggers plain spectral flux but NOT SuperFlux.
   This is the defining property of Böck & Widmer (2013) — what the max-filter
   is designed to achieve.

2. Transient detection: a genuine step-function transient (broadband energy
   change) IS detected by SuperFlux, confirming that suppression is selective,
   not wholesale.

Signal design for the vibrato test:
    Synthetic magnitude frames are injected directly into SuperfluxDetector and
    a plain OnsetDetector, bypassing PcmStft entirely (the same approach used
    in test_multiband_onset.py).  This avoids Hamming window sidelobe leakage
    and STFT frame-averaging effects.

    Two alternating frames after a steady-note warmup:
        frame_a: amplitude A at bin 46, zeros elsewhere  (reference pitch)
        frame_b: amplitude A at bin 47, zeros elsewhere  (vibrato shift)

    Warmup: _N_WARMUP_FRAMES of steady frame_a so both detectors calibrate
    their baselines to an already-playing note with flux=0.

    Vibrato phase: alternating frame_a / frame_b.

    Per-bin plain spectral flux: energy appears at bin 47 (or 46) every other
    frame → flux=A each frame → large f_norm → onset fires.

    SuperFlux (mu=3, lag=2): the max-filter covers bins 43..49 on the lagged
    frame.  The lagged frame alternates in sync with the current frame (lag=2,
    period=2), so x_max always has A at the current active bin → difference
    is max(0, A-A)=0 → SuperFlux≈0 → no onset.
"""

import numpy as np

from lampastream.pcm_source import WINDOW_SIZE
from lampastream.sync_engine import OnsetDetector, SuperfluxDetector, SuperfluxStftPipeline

_SR = 44100
_HOP = round(_SR * 0.010)  # 441 samples

_N_BINS = WINDOW_SIZE // 2 + 1   # 1025

# Warmup: 30 OnsetDetector frames + BUF_MAXLEN buffer fill.
_N_WARMUP_FRAMES = OnsetDetector._WARMUP_FRAMES + OnsetDetector._BUF_MAXLEN

_AMPLITUDE = 100.0

# Steady note at bin 46 (reference pitch before vibrato starts).
_FRAME_A = np.zeros(_N_BINS, dtype=np.float32)
_FRAME_A[46] = _AMPLITUDE

# Vibrato-shifted frame: energy moves to neighboring bin 47.
_FRAME_B = np.zeros(_N_BINS, dtype=np.float32)
_FRAME_B[47] = _AMPLITUDE


def _make_vibrato_sequence(n_vibrato: int) -> list[np.ndarray]:
    """Return n_warmup steady-note frames followed by n_vibrato alternating frames.

    Warmup on steady frame_a calibrates both detectors to zero-flux baseline
    (note already playing, no energy changes).  Vibrato then starts as a pure
    pitch shift, not a note onset.
    """
    warmup = [_FRAME_A] * _N_WARMUP_FRAMES
    vibrato = [_FRAME_A if i % 2 == 0 else _FRAME_B for i in range(n_vibrato)]
    return warmup + vibrato


def test_vibrato_suppressed_by_superflux_but_not_by_plain_flux() -> None:
    """Vibrato (alternating bin energy) triggers plain flux onsets but not SuperFlux.

    This is the core algorithm verification: the max-filter allows small
    bin-to-bin energy shifts (±mu bins) without counting them as new energy.

    Both detectors warm up on a steady note at bin 46 (flux=0).  When the note
    begins to vibrate (pitch oscillating between bins 46 and 47):

    - Per-bin plain spectral flux sees energy appearing at bin 47 every other
      frame and flags it as new energy → onset fires.
    - SuperFlux max-filters the lagged frame (lag=2, same phase as current)
      so x_max[47] ≥ A → difference ≈ 0 → no onset.
    """
    n_vibrato = 60  # 60 alternating frames after warmup

    sf_detector = SuperfluxDetector(mu=3, lag=2, delta=0.1, alpha=0.9)
    plain_detector = OnsetDetector(delta=0.1, alpha=0.9)

    frames = _make_vibrato_sequence(n_vibrato)

    sf_results: list[bool] = []
    plain_results: list[bool] = []

    # Initialise prev_frame to the steady note so the first warmup frame has
    # flux=0 (note already playing, not a new onset).
    prev_frame = _FRAME_A.copy()

    for frame in frames:
        sf_on, _ = sf_detector.process(frame)
        sf_results.append(sf_on)

        # Per-bin positive spectral flux (same as OnsetDetector.process() internals).
        flux = float(np.sum(np.maximum(0.0, frame - prev_frame)))
        plain_on, _ = plain_detector.process_odf(flux)
        plain_results.append(plain_on)
        prev_frame = frame.copy()

    vibrato_sf = sf_results[_N_WARMUP_FRAMES:]
    vibrato_plain = plain_results[_N_WARMUP_FRAMES:]

    assert any(vibrato_plain), (
        "Plain spectral flux should detect the vibrato's energy alternation as onsets "
        "(per-bin flux = A on every frame_a↔frame_b transition)"
    )
    assert not any(vibrato_sf), (
        f"SuperFlux should suppress vibrato — got {sum(vibrato_sf)} onset(s) "
        f"at frame(s) {[i for i, v in enumerate(vibrato_sf) if v]}. "
        "Check that the max-filter is applied with mu ≥ 1 over the lagged frame."
    )


def test_superflux_detects_genuine_transient() -> None:
    """SuperFlux still detects a broadband step-function transient.

    Ensures that vibrato suppression does not prevent detection of a real
    onset.  A step from silence to a full-amplitude signal creates energy
    across many bins simultaneously — far more than the max-filter can absorb.
    """
    n_silence = _N_WARMUP_FRAMES * _HOP
    burst_len = WINDOW_SIZE + (OnsetDetector._W + 2) * _HOP
    pcm = np.concatenate([
        np.zeros(n_silence, dtype=np.float32),
        np.ones(burst_len, dtype=np.float32),
    ])

    sf_pipeline = SuperfluxStftPipeline(_SR, mu=3, lag=2, delta=0.1, alpha=0.9)
    sf_onsets = [
        onset
        for i in range(0, len(pcm), _HOP)
        for onset, _ in sf_pipeline.push(pcm[i : i + _HOP])
    ]

    assert any(sf_onsets), (
        "SuperFlux failed to detect a step-function transient — "
        "the max-filter should not suppress broadband energy changes"
    )


def test_superflux_pipeline_accepts_float32_pcm() -> None:
    """SuperfluxStftPipeline accepts float32 PCM, not bar lists."""
    pipeline = SuperfluxStftPipeline(_SR, mu=3, lag=2, delta=0.1, alpha=0.9)
    samples = np.random.randn(_HOP).astype(np.float32)
    result = pipeline.push(samples)

    assert isinstance(result, list)
    for onset, strength in result:
        assert isinstance(onset, bool)
        assert isinstance(strength, float)


def test_process_odf_is_equivalent_to_process_for_scalar_bars() -> None:
    """OnsetDetector.process_odf() produces the same decisions as process().

    For a single-element bar list [v], process() computes flux = max(0, v - prev)
    and then peak-picks.  process_odf() feeds the pre-computed flux directly.
    When the input is always increasing (prev = 0, current = v), both paths
    agree on whether the result is an onset.

    This test catches regressions in the _peak_pick() refactor: if the shared
    internals are broken, the two code paths will diverge.
    """
    # Two independent detectors with identical parameters.
    det_process = OnsetDetector(delta=0.1, alpha=0.9)
    det_odf     = OnsetDetector(delta=0.1, alpha=0.9)

    n_warmup = OnsetDetector._WARMUP_FRAMES + OnsetDetector._BUF_MAXLEN

    # Same flux sequence for both paths.
    rng = np.random.default_rng(42)
    fluxes = rng.exponential(scale=5.0, size=n_warmup + 30).tolist()

    results_process = []
    results_odf = []
    prev = 0.0
    for f in fluxes:
        # process() with [f] as bars: flux = max(0, f - prev)
        onset_p, _ = det_process.process([f])
        # process_odf() with the same effective flux value
        flux_val = max(0.0, f - prev)
        onset_o, _ = det_odf.process_odf(flux_val)
        results_process.append(onset_p)
        results_odf.append(onset_o)
        prev = f

    # Both paths must agree on every frame.
    diverged = [
        i for i, (a, b) in enumerate(zip(results_process, results_odf, strict=True)) if a != b
    ]
    assert results_process == results_odf, (
        f"process() and process_odf() disagreed on frames: {diverged}"
    )
