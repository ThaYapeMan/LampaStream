"""Canonical processor adapter; the standalone BS.1770 DSP stays independent."""

import numpy as np

from .loudness_meter import SAMPLE_RATE, MomentaryLoudnessMeter, _RunningMeanSquare
from .pcm_source import WINDOW_SIZE
from .spectrum_engine import ProcessorUpdate, SharedAnalysisFrame


class KWeightedLoudnessAnalyzer:
    """LoudnessAnalyzer/AnalysisProcessor implementation using canonical PCM.

    Uses BeatDetector's shared-hop interval convention (480 samples). For each
    hop, feed PCM only through that STFT window's completion, never through a
    later hop first. This preserves chunk-independent readings and exact-interval
    merging with Beat/V2 without changing the live Effects clock. No FFT data is
    used: the shared hop positions are only a reporting clock.

    All PCM, including pre-roll and the final partial hop, reaches the meter.
    Like BeatDetector, flush emits no padded or duplicate hop. State is bounded
    by the loudness windows and one shared-window raw-power ring; no transport
    PCM is retained here. Raw stereo RMS is reported alongside LUFS, before any
    K-weighting, for amplitude-domain energy selection.
    """

    def __init__(self) -> None:
        self._meter = MomentaryLoudnessMeter()
        self._raw_power = _RunningMeanSquare(WINDOW_SIZE, 2)

    @property
    def processor_id(self) -> str:
        return "loudness_analyzer"

    def feed(self, frame: SharedAnalysisFrame) -> list[ProcessorUpdate]:
        updates = []
        consumed = 0
        for start in frame.hop_sample_starts:
            stop = start + WINDOW_SIZE - frame.sample_start
            if not consumed < stop <= len(frame.pcm):
                raise ValueError("Shared loudness hop outside canonical PCM frame")
            momentary, short_term = self._meter.feed(frame.pcm[consumed:stop])
            self._raw_power.push(np.square(frame.pcm[consumed:stop], dtype=np.float64))
            consumed = stop
            updates.append(ProcessorUpdate(
                processor_id=self.processor_id,
                sample_start=start,
                sample_end=start + SAMPLE_RATE // 100,
                level=float(np.sqrt(np.mean(self._raw_power.mean()))),
                loudness_momentary_lufs=momentary,
                loudness_short_term_lufs=short_term,
            ))
        if consumed < len(frame.pcm):
            self._meter.feed(frame.pcm[consumed:])
            self._raw_power.push(np.square(frame.pcm[consumed:], dtype=np.float64))
        return updates

    def flush(self) -> list[ProcessorUpdate]:
        return []

    def reset(self) -> None:
        self._meter.reset()
        self._raw_power.reset()

    def close(self) -> None:
        self.reset()
