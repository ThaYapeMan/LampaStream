"""Canonical processor adapter for the existing mono PcmHpss algorithm."""

import threading

import numpy as np

from .pcm_source import PcmHpss
from .spectrum_engine import ProcessorUpdate, SharedAnalysisFrame

_SAMPLE_RATE = 48000
_HOP = _SAMPLE_RATE // 100


class HpssAnalyzer:
    """Optional HPSS with its own aligned hop clock and worker-owned PCM state.

    Use the same (L+R)/2 projection as the legacy tap. PcmHpss remains unchanged;
    it owns its rolling STFT and median history. Like Beat, incomplete windows
    are not padded at EOS. Configuration changes serialize with feed/reset.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._lock = threading.Lock()
        self._enabled = enabled
        self._hpss = PcmHpss(_SAMPLE_RATE) if enabled else None
        self._next_start: int | None = None

    @property
    def processor_id(self) -> str:
        return "hpss_analyzer"

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            if enabled != self._enabled:
                self._enabled = enabled
                self._hpss = PcmHpss(_SAMPLE_RATE) if enabled else None
                self._next_start = None

    def feed(self, frame: SharedAnalysisFrame) -> list[ProcessorUpdate]:
        with self._lock:
            if self._hpss is None:
                return []
            if self._next_start is None:
                self._next_start = frame.sample_start
            results = self._hpss.push(np.mean(frame.pcm, axis=1))
            updates = []
            for percussive, harmonic in results:
                updates.append(ProcessorUpdate(
                    processor_id=self.processor_id,
                    sample_start=self._next_start,
                    sample_end=self._next_start + _HOP,
                    percussive_energy=percussive,
                    harmonic_energy=harmonic,
                ))
                self._next_start += _HOP
            return updates

    def flush(self) -> list[ProcessorUpdate]:
        return []

    def reset(self) -> None:
        with self._lock:
            self._hpss = PcmHpss(_SAMPLE_RATE) if self._enabled else None
            self._next_start = None

    def close(self) -> None:
        with self._lock:
            self._hpss = None
            self._next_start = None
