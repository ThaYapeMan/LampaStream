"""Tests for StftOnsetPipeline (PCM tap step 3: combined onset on STFT input).

Verifies that:
1. The pipeline detects a known transient in otherwise silent audio.
2. The 100 Hz STFT path detects the same transient earlier (in samples)
   than a simulated 30 Hz onset path, matching the timing advantage
   described in docs/LampaStream_pcm_tap_spec.md.
"""

import numpy as np

from lampastream.pcm_source import WINDOW_SIZE
from lampastream.sync_engine import OnsetDetector, StftOnsetPipeline

_SR = 44100
_HOP_100 = round(_SR * 0.010)   # 441 samples  (100 Hz STFT path)
_HOP_30 = round(_SR / 30)        # 1470 samples (simulated 30 Hz cava path)


def _make_transient_pcm() -> tuple[np.ndarray, int]:
    """Return (pcm, transient_start_sample).

    Generates enough silence to exhaust the OnsetDetector warmup on BOTH
    the 100 Hz and the 30 Hz paths, then a full-amplitude step function.

    Warmup = 30 frames.
    - 100 Hz path: 30 × 441 = 13 230 samples needed.
    - 30 Hz path: 30 × 1470 = 44 100 samples needed  ← the binding constraint.

    35 × hop_30 = 51 450 samples of silence gives 5 frames of margin for the
    30 Hz path and 116 frames for the 100 Hz path.

    Burst length is sized for the SLOWER (30 Hz) lookahead: the local-max
    window is w=3 frames, so 3 × hop_30 = 4410 samples of burst must follow
    the transient for the 30 Hz candidate to be evaluated.
    WINDOW_SIZE + (w+2) × hop_30 = 2048 + 5 × 1470 = 9398 samples.
    """
    n_silence = 35 * _HOP_30
    transient_start = n_silence
    burst_len = WINDOW_SIZE + (OnsetDetector._W + 2) * _HOP_30
    pcm = np.concatenate([
        np.zeros(n_silence, dtype=np.float32),
        np.ones(burst_len, dtype=np.float32),
    ])
    return pcm, transient_start


def test_stft_onset_pipeline_detects_transient() -> None:
    """StftOnsetPipeline fires onset=True after a step-function transient.

    Uses the production defaults (delta=0.1, alpha=0.9).  delta=0.0 is NOT
    used here even though it sounds "more sensitive": with a flat signal of
    all zeros, delta=0.0 makes condition 2 degenerate (0 >= mean([0]*13) + 0)
    and every post-warmup frame fires as an onset regardless of actual energy.
    delta=0.1 requires flux to exceed the rolling mean by a real margin, which
    silence (flux=0) cannot satisfy.

    Onset must not fire during the leading silence; it must fire after the
    step function begins.
    """
    pipeline = StftOnsetPipeline(_SR, delta=0.1, alpha=0.9)
    hop = pipeline.hop  # 441

    pcm, transient_start = _make_transient_pcm()

    all_results: list[tuple[bool, float]] = []
    for i in range(0, len(pcm), hop):
        all_results.extend(pipeline.push(pcm[i : i + hop]))

    onset_frames = [i for i, (onset, _) in enumerate(all_results) if onset]
    assert onset_frames, (
        "no onset detected — warmup length or transient amplitude may be off"
    )

    # Onset must not fire during the silence region.
    earliest_valid = transient_start // hop
    assert min(onset_frames) >= earliest_valid, (
        f"onset fired at frame {min(onset_frames)} "
        f"(≈ sample {min(onset_frames) * hop}) "
        f"but transient begins at frame {earliest_valid} "
        f"(sample {transient_start})"
    )


def test_stft_detects_sooner_than_30hz_path() -> None:
    """100 Hz STFT path detects the same transient earlier (in samples) than a
    simulated 30 Hz path.

    The 30 Hz path models cava-based onset detection: OnsetDetector fed with
    30-bar spectral snapshots taken every 1/30 s ≈ 1470 samples.  Bars are
    derived from the FFT magnitude of each 1470-sample window, averaged into
    30 equal-width frequency groups — a simplified but honest substitute for
    cava's output at the same frame rate.

    Expected latency difference (w=3 frames lookahead at each rate):
        100 Hz: 3 × 10 ms  = 30 ms detection lag
        30 Hz:  3 × 33 ms  = 100 ms detection lag
    → STFT path detects ≈ 90 ms sooner for the same transient.
    """
    pcm, _ = _make_transient_pcm()

    # --- 100 Hz STFT path ---
    stft_pipeline = StftOnsetPipeline(_SR, delta=0.1, alpha=0.9)
    hop_stft = stft_pipeline.hop          # 441
    stft_onset_sample: int | None = None
    for i in range(0, len(pcm), hop_stft):
        for onset, _ in stft_pipeline.push(pcm[i : i + hop_stft]):
            if onset and stft_onset_sample is None:
                stft_onset_sample = i + hop_stft

    # --- Simulated 30 Hz cava-bar path ---
    # Feed OnsetDetector with 30-bar snapshots derived from the FFT of each
    # 1470-sample window.  Bars are magnitudes averaged into equal-width bins.
    cava_detector = OnsetDetector(delta=0.1, alpha=0.9)
    n_bars = 30
    cava_onset_sample: int | None = None
    for i in range(0, len(pcm) - _HOP_30, _HOP_30):
        window = pcm[i : i + _HOP_30]
        fft_mag = np.abs(np.fft.rfft(window)).astype(np.float32)
        bin_size = len(fft_mag) // n_bars
        bars = [
            float(np.mean(fft_mag[j * bin_size : (j + 1) * bin_size]))
            for j in range(n_bars)
        ]
        onset, _ = cava_detector.process(bars)
        if onset and cava_onset_sample is None:
            cava_onset_sample = i + _HOP_30

    assert stft_onset_sample is not None, "100 Hz STFT path never detected onset"
    assert cava_onset_sample is not None, "30 Hz path never detected onset"
    assert stft_onset_sample < cava_onset_sample, (
        f"Expected 100 Hz path to detect sooner: "
        f"STFT at sample {stft_onset_sample} "
        f"({stft_onset_sample / _SR * 1000:.1f} ms), "
        f"30 Hz at sample {cava_onset_sample} "
        f"({cava_onset_sample / _SR * 1000:.1f} ms)"
    )
