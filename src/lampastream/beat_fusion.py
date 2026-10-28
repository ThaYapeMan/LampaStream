"""Fuse bass triggers with the tempo grid while retaining event identities."""
from __future__ import annotations

import math

from .beat_trigger import BassBeatTrigger
from .spectrum_engine import ProcessorUpdate
from .tempo_clock import TempoClock
from .types import OnsetEvent


class BeatFusion:
    processor_id = 'beat_fusion'

    def __init__(self, sensitivity=50., band='bass', latency_ms=0., gate_dbfs=-60.):
        self.options = sensitivity, band, latency_ms, gate_dbfs
        self.trigger = BassBeatTrigger(sensitivity, band)
        self.clock = TempoClock(latency_ms)
        self.gate = 10**(gate_dbfs/20)
        self.last_grid = None
        self.next_grid = None
        self.last_update = -math.inf

    def reset(self):
        self.__init__(*self.options)

    def close(self):
        pass

    def flush(self):
        return []

    def _event(self, epoch, t, availability, trigger=None, *, texture=False, predicted=False):
        clock = self.clock
        on_beat = not clock.locked or clock.phase(t) <= .04/(clock.period or 1)
        on_beat = on_beat or clock.phase(t) >= 1-.04/(clock.period or 1)
        strength = trigger.strength if trigger else clock.confidence*.5
        if predicted:
            strength *= math.exp(-max(0., t-clock.last_trigger)/clock.fade_s)
        elif not on_beat:
            strength *= .25
        band = 'mid' if texture else 'bass'
        sample = round(t*48000)
        return OnsetEvent((epoch, 'texture' if texture else 'beat', sample), epoch,
                          sample, availability, 0, strength,
                          trigger.ratio if trigger else 0.,
                          trigger.confidence if trigger else clock.confidence,
                          frozenset({band}), band, band=trigger.band if trigger else 'bass',
                          kind='onset' if texture else 'beat',
                          on_beat=False if texture else on_beat,
                          beat_phase=clock.phase(t), bar_position=clock.bar_position(t),
                          predicted=predicted)

    def feed(self, frame):
        result = []
        for start, mag in zip(frame.hop_sample_starts, frame.mag_frames, strict=True):
            # The long STFT labels its leading edge. Its energy rise labels the
            # containing attack hop; availability remains the full window end.
            t = (start+960)/48000
            availability = start+2048
            gate = float(sum(mag**2))**.5/2048 >= self.gate
            beat, texture = self.trigger.process(mag, t, locked=self.clock.locked,
                                                period=self.clock.period, gate=gate)
            if t-self.last_update >= .1-1e-9:
                self.clock.update(t, gate=gate)
                self.last_update = t
            events = []
            if beat:
                self.clock.trigger(t, beat.strength)
                # Do not duplicate a predicted grid point already emitted.
                if self.last_grid is None or abs(t-self.last_grid) > .04:
                    events.append(self._event(frame.epoch_id, t, availability, beat))
                if self.clock.locked:
                    self.last_grid = t
                    self.next_grid = self.clock.next_beat
            if texture:
                events.append(self._event(frame.epoch_id, t, availability, texture, texture=True))
            if (self.clock.locked and self.next_grid is not None
                    and t >= self.next_grid+.04):
                events.append(self._event(frame.epoch_id, self.next_grid, availability,
                                          predicted=True))
                self.last_grid = self.next_grid
                self.next_grid += self.clock.period
            for event in events:
                result.append(ProcessorUpdate(self.processor_id, event.candidate_sample,
                    event.candidate_sample+480, availability_sample=availability,
                    onset_events=(event,), onset=True, onset_strength=event.strength))
        return result
