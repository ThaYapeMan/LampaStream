"""Lighting-only admission of confirmed onset candidates; analysis is unchanged."""
import math
from dataclasses import replace
from statistics import median


def gain_progress(gain, ceiling):
    """Tracker's existing gain-floor mapping, unchanged by the relative gate."""
    if gain <= 8:
        return 0.
    return min(1., (gain-8)/max(ceiling-8, 1e-9))


class RelativeOnsetGate:
    def __init__(self, k=2., window_s=3., refractory_ms=120., full_k=3., absolute_min=.02):
        self.configure(k, window_s, refractory_ms, full_k, absolute_min)
        self.reset()

    def configure(self, k, window_s, refractory_ms, full_k, absolute_min):
        values = (k, window_s, refractory_ms, full_k, absolute_min)
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
                or k <= 1 or window_s <= 0 or not 60 <= refractory_ms <= 200
                or full_k < k or absolute_min <= 0):
            raise ValueError("Invalid relative onset gate parameters")
        self.k, self.window_s, self.refractory_s = k, window_s, refractory_ms/1000
        self.full_k, self.absolute_min = full_k, absolute_min

    def reset(self):
        self.epoch = None
        self.history = []
        self.last_fire = -float('inf')
        self.watermark = -float('inf')

    def accepts(self, event, bass_strength=0.):
        if event.predicted:
            return False
        if event.epoch != self.epoch:
            self.reset()
            self.epoch = event.epoch
        stamp = event.candidate_sample/48000
        self.watermark = max(self.watermark, stamp)
        self.history = [row for row in self.history if row[0] >= self.watermark-self.window_s]
        if any(row[3] == event.id for row in self.history):
            return False
        recent = [row for row in self.history if stamp-self.window_s <= row[0] <= stamp]
        full = event.strength_raw
        bass = bass_strength if 'bass' in event.bands else 0.
        if bass <= 0 and event.bands == frozenset({'bass'}):
            bass = full
        if bass > 0:
            reference = median([row[2] for row in recent if row[2] > 0] or [bass])
            value, factor = bass, self.k
        else:
            reference = median([row[1] for row in recent] or [full])
            value, factor = full, self.full_k
        # Every distinct candidate trains the reference, including refractory rejects.
        self.history.append((stamp, full, bass, event.id))
        fires = (value >= self.absolute_min and value >= factor*reference
                 and stamp-self.last_fire >= self.refractory_s-1e-9)
        if fires:
            self.last_fire = stamp
        return fires


def select_events(mode, tracker_events, records, *, gate=None):
    if mode == "off":
        return []
    if mode == "tracker":
        return list(tracker_events)
    if mode != "onset":
        raise ValueError("Invalid beat_accent_mode")
    gate = gate if gate is not None else RelativeOnsetGate()
    events = []
    for record in records:
        features = record.features
        for event in features.diagnostic_events:
            if not gate.accepts(event, features.onset_bass_strength):
                continue
            offset = (event.candidate_sample-record.sample_pos)/48000
            events.append(replace(event, kind="beat", on_beat=False,
                received_monotonic=(features.received_monotonic+offset
                                    if features.received_monotonic is not None else None),
                play_monotonic=(features.play_monotonic+offset
                                if features.play_monotonic is not None else None)))
    return events
