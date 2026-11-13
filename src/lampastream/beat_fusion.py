"""Fuse bass triggers with the tempo grid while retaining event identities."""
from __future__ import annotations

import bisect
import logging
import math

from .beat_trigger import BassBeatTrigger
from .spectrum_engine import ProcessorUpdate
from .tempo_clock import TempoClock
from .types import BeatPosition, OnsetEvent

log = logging.getLogger(__name__)


class BeatFusion:
    """MusicalTimeline (see docs/ANALYSIS_ARCHITECTURE.md).

    Owns prior grid, live observations, correction, confidence and prediction.
    BeatPosition is produced here from canonical content-clock inputs only.
    """

    processor_id = 'beat_fusion'

    def __init__(self, sensitivity=50., band='bass', latency_ms=0., gate_dbfs=-60.):
        from .grid.prior import GridPrior
        self.prior = GridPrior()
        self.grid_provider = None
        self.grid_state = None
        self.accent_mode = "tracker"
        self.options = sensitivity, band, latency_ms, gate_dbfs
        self.agc_max_gain = 64.
        self.trigger = BassBeatTrigger(sensitivity, band)
        self.clock = TempoClock(latency_ms)
        self.gate = 10**(gate_dbfs/20)
        self.last_grid = None
        self.last_live_beat = -math.inf
        self.next_grid = None
        self.last_update = -math.inf
        self.current_time = 0.
        self.content_origin = 0.
        self.position_epoch = None
        self.position_identity = None
        self.position_source = None
        self.position_offset = 0
        self.position_last = None
        self.beat_index_jumps = 0

    def position(self, content_t, *, identity=None, epoch=None, advance=True):
        """Build the complete record once from a normalized beat coordinate.

        Adapters supply clocks and opaque identities, never player/output kinds.
        Grid lookup and the continuously running tracker normalize to the same
        fractional beat coordinate before the shared counting/phase arithmetic.
        Event lookups do not advance the publication cursor (predictions can be
        ahead of the current frame). The current record never uses wall time.
        """
        grid = self.prior.grid if self.accent_mode == 'tracker' else None
        identity = self.prior.identity if self.prior.identity is not None else identity
        changed = identity != self.position_identity
        if changed and advance:
            self.position_identity = identity
            self.position_source = None
            self.position_offset = 0
            self.position_last = None
        epoch_changed = epoch is not None and epoch != self.position_epoch
        sample_t = content_t-self.content_origin
        tempo, confidence, coordinate, downbeat, meter = None, 0., 0., 0, 4
        source = 'onset'
        if grid is not None and grid.beats:
            source, tempo, confidence = 'grid', grid.tempo, grid.confidence
            i = bisect.bisect_right(grid.beats, content_t+1e-9)-1
            if i >= 0:
                period = (grid.beats[i+1]-grid.beats[i]
                          if i+1 < len(grid.beats) else 60/tempo)
                coordinate = i+max(0., (content_t-grid.beats[i])/period)
            section = next((s for s in grid.sections if s.start <= content_t < s.end), None)
            meter = (section.bar_length if section else None) or 4
            downbeat = (bisect.bisect_left(grid.beats, grid.downbeats[0])
                        if grid.downbeats else 0)
        elif (self.accent_mode == 'tracker' and self.clock.period
              and self.clock.anchor is not None):
            source, tempo, confidence = 'tracker', self.clock.tempo_bpm, self.clock.confidence
            coordinate = max(0., self.clock.beat_index
                             +(sample_t-self.clock.anchor)/self.clock.period)
            downbeat = self.clock.downbeat_index
        if tempo is None:
            return BeatPosition(source='tracker' if self.accent_mode == 'tracker' else 'onset')
        raw = math.floor(coordinate+1e-9)
        phase = min(1.-1e-12, max(0., coordinate-raw))
        offset = 0 if changed else self.position_offset
        previous = None if changed else self.position_last
        if advance and previous is not None and (epoch_changed or content_t >= previous[0]):
            target = raw+offset
            if source != self.position_source and abs(target-previous[1]) > 1:
                self.beat_index_jumps += 1
                log.warning('beat_index_jumps=%d: handover %s → %s raw jump %d',
                            self.beat_index_jumps, self.position_source, source,
                            target-previous[1])
                offset += previous[1]-target
            if raw+offset < previous[1]:
                offset += previous[1]-(raw+offset)
        index = max(0, raw+offset)
        bar_coordinate = max(0., index-downbeat+phase)
        record = BeatPosition(tempo, phase, index, (bar_coordinate % meter)/meter,
                              math.floor(bar_coordinate/meter), min(.5, confidence),
                              source, meter, False)
        if advance and (previous is None or epoch_changed or content_t >= previous[0]):
            self.position_epoch = epoch
            self.position_source, self.position_offset = source, offset
            self.position_last = content_t, index
        return record

    def reset(self):
        continuity = {key: getattr(self, key) for key in (
            'position_epoch', 'position_identity', 'position_source', 'position_offset',
            'position_last', 'beat_index_jumps')}
        ceiling = self.agc_max_gain
        provider, prior, mode = self.grid_provider, self.prior, self.accent_mode
        self.__init__(*self.options)
        self.__dict__.update(continuity)
        self.agc_max_gain = ceiling
        self.grid_provider, self.prior, self.accent_mode = provider, prior, mode
        self.prior.next_index = None
        self.prior.grid = None
        self.prior.onsets.clear()
        self.prior.reset_attacks()
        self.prior.loud.clear()
        self.prior.started = None
        self.prior.available = None
        self.prior.pending_grid = None
        self.prior.last_emitted = -math.inf

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
        band = trigger.band if texture else 'bass'
        sample = round(t*48000)
        return OnsetEvent((epoch, 'texture-'+band if texture else 'beat', sample), epoch,
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
        for trigger in (self.trigger.primary, self.trigger.energy,
                        self.trigger.texture, self.trigger.treble):
            trigger.max_gain = self.agc_max_gain
        for start, mag in zip(frame.hop_sample_starts, frame.mag_frames, strict=True):
            # The long STFT labels its leading edge. Its energy rise labels the
            # containing attack hop; availability remains the full window end.
            t = (start+960)/48000
            availability = start+2048
            self.current_time = t
            gate = float(sum(mag**2))**.5/2048 >= self.gate
            beat, texture = self.trigger.process(mag, t, locked=self.clock.locked,
                                                period=self.clock.period, gate=gate)
            if t-self.last_update >= .1-1e-9:
                self.clock.update(t, gate=gate)
                self.last_update = t
            events = []
            if beat:
                self.last_live_beat = t
                self.clock.trigger(t, beat.strength)
                # Do not duplicate a predicted grid point already emitted.
                if self.last_grid is None or abs(t-self.last_grid) > .04:
                    events.append(self._event(frame.epoch_id, t, availability, beat))
                if self.clock.locked:
                    self.last_grid = t
                    self.next_grid = self.clock.next_beat
            for tick in texture:
                events.append(self._event(frame.epoch_id, t, availability, tick, texture=True))
            if (self.clock.locked and self.next_grid is not None
                    and t >= self.next_grid+.04):
                events.append(self._event(frame.epoch_id, self.next_grid, availability,
                                          predicted=True))
                self.last_grid = self.next_grid
                self.next_grid += self.clock.period
            if self.grid_provider is not None and self.accent_mode == 'tracker':
                active = self.prior.grid is not None
                ticks = self.prior.ticks(t, gate, horizon=.1)
                if self.prior.grid is not None:
                    events = [self.prior.event(self._event(frame.epoch_id, stamp, availability),
                                              stamp, strength, index)
                              for stamp, strength, index in ticks
                              if abs(stamp-self.last_live_beat) > .07]
                elif active:
                    # The live estimator has kept running throughout grid use.
                    self.last_grid = None
                self.grid_state = {**(self.grid_state or {}), **self.prior.status(t)}
                if self.prior.grid is None and not self.clock.locked:
                    self.grid_state['beat_source'] = 'onset'
            for event in events:
                # A prior can predict future events. Its contribution describes
                # this observed hop; the event retains its future sample coordinate.
                sample = start+960 if event.id[1] == 'grid' else event.candidate_sample
                result.append(ProcessorUpdate(self.processor_id, sample,
                    sample+480, availability_sample=availability,
                    onset_events=(event,), onset=True, onset_strength=event.strength))
        return result
