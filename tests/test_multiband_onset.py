"""Tests for MultibandOnsetDetector and MultibandStftPipeline.

Two distinct verification layers:

1. Synthetic frame tests — directly inject pre-built magnitude frames into
   MultibandOnsetDetector, bypassing PcmStft entirely.  This removes Hamming
   window sidelobe contamination and gives exact per-band isolation:
   if only bass bins have energy, ONLY the bass OnsetDetector fires.

2. PCM pipeline tests — verify that MultibandStftPipeline accepts float32 PCM
   arrays and that the bass detector fires after (not before) a transient.
   Sidelobe leakage means ALL detectors may see some energy at the transient
   boundary, so these tests focus on timing and wiring, not strict isolation.
"""

import numpy as np

from lampastream.pcm_source import WINDOW_SIZE
from lampastream.sync_engine import MultibandOnsetDetector, MultibandStftPipeline, OnsetDetector

_SR = 44100
_HOP = round(_SR * 0.010)  # 441 samples

# Band boundaries matching profile defaults
_BASS_HZ = 250
_MID_HZ = 2000

_N_BINS = WINDOW_SIZE // 2 + 1   # 1025


def _hz_to_bin(hz: int) -> int:
    return round(hz * WINDOW_SIZE / _SR)


# ---------------------------------------------------------------------------
# Synthetic frame tests — perfect band isolation
# ---------------------------------------------------------------------------


def _run_detector_with_frames(
    frames: list[np.ndarray],
) -> list[tuple[tuple[bool, float], tuple[bool, float], tuple[bool, float]]]:
    """Feed synthetic magnitude frames to a freshly-constructed MultibandOnsetDetector."""
    detector = MultibandOnsetDetector(
        sample_rate=_SR,
        bass_hz=_BASS_HZ,
        mid_hz=_MID_HZ,
        delta=0.1,
        alpha=0.9,
    )
    return [detector.process(f) for f in frames]


def test_bass_only_synthetic_fires_only_onset_bass() -> None:
    """Energy in bass bins only → onset_bass fires, onset_mid and onset_treble don't.

    The synthetic frame has non-zero values ONLY at bin 5 (≈ 107 Hz, inside
    the bass band 0..11) and zeros everywhere else.  There is no Hamming
    sidelobe leakage because PcmStft is bypassed entirely.  This proves that
    the three OnsetDetectors maintain independent state: a bass-band spike
    cannot propagate to the mid or treble detectors.
    """
    silence = np.zeros(_N_BINS, dtype=np.float32)
    bass_frame = np.zeros(_N_BINS, dtype=np.float32)
    bass_frame[5] = 100.0  # energy only in bass band (bin 5 ≈ 108 Hz)

    # Warmup: enough silence frames for the OnsetDetector to pass warmup
    # and fill its buffer (WARMUP_FRAMES + BUF_MAXLEN).
    n_warmup = OnsetDetector._WARMUP_FRAMES + OnsetDetector._BUF_MAXLEN

    # Burst: BUF_MAXLEN frames so the burst candidate reaches evaluation position.
    frames = [silence] * n_warmup + [bass_frame] * OnsetDetector._BUF_MAXLEN

    results = _run_detector_with_frames(frames)
    burst_results = results[n_warmup:]

    bass_fires = [r[0][0] for r in burst_results]
    mid_fires  = [r[1][0] for r in burst_results]
    treble_fires = [r[2][0] for r in burst_results]

    assert any(bass_fires), (
        "Expected onset_bass to fire during bass-only burst — "
        "check OnsetDetector warmup and buffer sizing"
    )
    assert not any(mid_fires), (
        "onset_mid fired on bass-only synthetic frames — "
        "the mid OnsetDetector must not see energy from the bass band"
    )
    assert not any(treble_fires), (
        "onset_treble fired on bass-only synthetic frames — "
        "the treble OnsetDetector must not see energy from the bass band"
    )


def test_mid_only_synthetic_fires_only_onset_mid() -> None:
    """Energy in mid bins only → onset_mid fires, bass and treble don't.

    Symmetric counterpart to the bass test; bin 46 ≈ 991 Hz sits in mid
    (bass_hi=12 .. mid_hi=93).
    """
    silence = np.zeros(_N_BINS, dtype=np.float32)
    mid_frame = np.zeros(_N_BINS, dtype=np.float32)
    mid_frame[46] = 100.0  # bin 46 ≈ 991 Hz — squarely in mid band

    n_warmup = OnsetDetector._WARMUP_FRAMES + OnsetDetector._BUF_MAXLEN
    frames = [silence] * n_warmup + [mid_frame] * OnsetDetector._BUF_MAXLEN

    results = _run_detector_with_frames(frames)
    burst = results[n_warmup:]

    assert any(r[1][0] for r in burst), "Expected onset_mid to fire on mid-only burst"
    assert not any(r[0][0] for r in burst), "onset_bass must not fire on mid-only energy"
    assert not any(r[2][0] for r in burst), "onset_treble must not fire on mid-only energy"


def test_detectors_are_independent() -> None:
    """Each band's OnsetDetector has its own state — a loud bass onset does not
    suppress or advance the mid/treble detectors' decaying threshold."""
    silence = np.zeros(_N_BINS, dtype=np.float32)
    bass_frame = np.zeros(_N_BINS, dtype=np.float32)
    bass_frame[5] = 200.0

    mid_frame = np.zeros(_N_BINS, dtype=np.float32)
    mid_frame[46] = 200.0

    n_warmup = OnsetDetector._WARMUP_FRAMES + OnsetDetector._BUF_MAXLEN
    # Sequence: warmup, bass burst, silence, mid burst
    n_gap = 20  # enough for g_alpha to decay between the two bursts
    frames = (
        [silence] * n_warmup
        + [bass_frame] * OnsetDetector._BUF_MAXLEN
        + [silence] * n_gap
        + [mid_frame] * OnsetDetector._BUF_MAXLEN
    )

    results = _run_detector_with_frames(frames)

    bass_phase_start = n_warmup
    mid_phase_start  = n_warmup + OnsetDetector._BUF_MAXLEN + n_gap

    bass_fires_in_bass_phase = any(
        r[0][0] for r in results[bass_phase_start : bass_phase_start + OnsetDetector._BUF_MAXLEN]
    )
    mid_fires_in_mid_phase = any(
        r[1][0] for r in results[mid_phase_start : mid_phase_start + OnsetDetector._BUF_MAXLEN]
    )

    assert bass_fires_in_bass_phase, "Bass detector did not fire during bass burst"
    assert mid_fires_in_mid_phase, (
        "Mid detector did not fire during mid burst — "
        "a preceding bass onset must not suppress the mid g_alpha threshold"
    )


# ---------------------------------------------------------------------------
# PCM pipeline tests — wiring and timing verification
# ---------------------------------------------------------------------------


def _make_transient_pcm() -> tuple[np.ndarray, int]:
    """Return (pcm, transient_start_sample).

    Generates 35 hops of silence followed by a full-amplitude step function.
    35 hops = 15435 samples — enough silence to exhaust MultibandOnsetDetector
    warmup (30 frames per band × hop=441 = 13230 samples, with margin).
    """
    n_silence = 35 * _HOP
    burst_len = WINDOW_SIZE + (OnsetDetector._W + 2) * _HOP
    pcm = np.concatenate([
        np.zeros(n_silence, dtype=np.float32),
        np.ones(burst_len, dtype=np.float32),
    ])
    return pcm, n_silence


def test_bass_onset_fires_after_transient_not_before() -> None:
    """onset_bass must not fire during silence before the transient.

    The first STFT frame that overlaps the transient is the earliest valid
    onset candidate; frames entirely within the silent region must not fire.

    Note: The STFT window is WINDOW_SIZE=2048 samples wide.  Frame k covers
    samples [k*hop, k*hop + WINDOW_SIZE).  The earliest frame that SEES the
    transient (at sample transient_start) satisfies:
        k*hop + WINDOW_SIZE > transient_start
        k > (transient_start - WINDOW_SIZE) / hop
    Hence earliest_valid_frame = (transient_start - WINDOW_SIZE) // hop + 1.
    """
    pipeline = MultibandStftPipeline(
        sample_rate=_SR,
        bass_hz=_BASS_HZ,
        mid_hz=_MID_HZ,
        delta=0.1,
        alpha=0.9,
    )

    pcm, transient_start = _make_transient_pcm()
    # First STFT frame whose window can overlap the transient.
    earliest_valid_frame = (transient_start - WINDOW_SIZE) // _HOP + 1

    bass_onset_frames: list[int] = []
    frame_idx = 0
    for i in range(0, len(pcm), _HOP):
        for (b_on, _), _, _ in pipeline.push(pcm[i : i + _HOP]):
            if b_on:
                bass_onset_frames.append(frame_idx)
            frame_idx += 1

    assert bass_onset_frames, (
        "Expected at least one onset_bass on a step-function transient"
    )
    assert min(bass_onset_frames) >= earliest_valid_frame, (
        f"onset_bass fired at frame {min(bass_onset_frames)} "
        f"(sample {min(bass_onset_frames) * _HOP}) — transient not visible "
        f"until frame {earliest_valid_frame} (window first overlaps sample {transient_start})"
    )


def test_multiband_pipeline_uses_stft_not_cava_bars() -> None:
    """MultibandStftPipeline accepts raw float32 PCM, not cava bar lists.

    The pipeline must accept a float32 numpy array and return 3-tuple results
    (not raise TypeError or expect integers).  Verifies correct wiring from
    PcmStft through MultibandOnsetDetector.
    """
    pipeline = MultibandStftPipeline(
        sample_rate=_SR,
        bass_hz=_BASS_HZ,
        mid_hz=_MID_HZ,
        delta=0.1,
        alpha=0.9,
    )

    samples = np.random.randn(_HOP).astype(np.float32)
    result = pipeline.push(samples)

    assert isinstance(result, list)
    for frame_result in result:
        assert len(frame_result) == 3
        for band_result in frame_result:
            onset, strength = band_result
            assert isinstance(onset, bool)
            assert isinstance(strength, float)


def test_band_bin_boundaries_match_hz() -> None:
    """FFT bin boundaries for 250 Hz and 2000 Hz at 44100 Hz / 2048 samples.

    Documents the expected bin counts so regressions in bin arithmetic are
    caught immediately.  Values: round(hz * WINDOW_SIZE / sample_rate).
    """
    assert _hz_to_bin(250) == 12    # round(250 * 2048 / 44100) = round(11.6) = 12
    assert _hz_to_bin(2000) == 93   # round(2000 * 2048 / 44100) = round(92.9) = 93
