"""Lighting-only admission of confirmed candidates against the raw ODF background."""
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
        self.history = {}
        self.seen = {}
        self.last_fire = -float('inf')
        self.watermark = -float('inf')

    def _epoch(self, epoch):
        if epoch != self.epoch:
            self.reset()
            self.epoch = epoch

    def observe(self, epoch, frame):
        """Train on every analysis frame, including zeros and non-candidate frames."""
        self._epoch(epoch)
        stamp = frame.sample_pos/48000
        self.watermark = max(self.watermark, stamp)
        # Retain extra delivery slack for delayed candidates; reference() still
        # uses exactly [candidate-W, candidate], never future observations.
        cutoff = self.watermark-self.window_s-1.
        self.history = {t: row for t, row in self.history.items() if t >= cutoff}
        self.seen = {key: t for key, t in self.seen.items() if t >= cutoff}
        values = self.history.setdefault(stamp, {})
        for band in ('full', 'bass', 'mid', 'treble'):
            value = getattr(frame, band)
            if value is not None:
                values[band] = value
        if frame.full is None:
            values['full'] = max((v for key, v in values.items() if key != 'full'), default=0.)

    def reference(self, stamp, band='full'):
        values = [row[band] for t, row in self.history.items()
                  if stamp-self.window_s <= t <= stamp and band in row]
        if not values:
            return None
        background = median(values)
        spread = median(abs(value-background) for value in values)
        return background, spread

    def accepts(self, event, bass_strength=0.):
        if event.predicted:
            return False
        self._epoch(event.epoch)
        if event.id in self.seen:
            return False
        stamp = event.candidate_sample/48000
        self.seen[event.id] = stamp
        bass = bass_strength if 'bass' in event.bands else 0.
        if bass <= 0 and event.bands == frozenset({'bass'}):
            bass = event.strength_raw
        band, value, factor = (('bass', bass, self.k) if bass > 0
                               else ('full', event.strength_raw, self.full_k))
        reference = self.reference(stamp, band)
        if reference is None:
            return False
        background, spread = reference
        # A flat envelope (MAD=0) must not turn an equal-level candidate into a
        # new peak. Above the background, zero MAD needs no invented unit floor.
        fires = (value >= self.absolute_min and value > background
                 and value >= background+factor*spread
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
    events, actions, epochs = [], [], {}
    for record in records:
        epoch_index = epochs.setdefault(record.epoch, len(epochs))
        features = record.features
        actions.extend((epoch_index, frame.sample_pos, 0, record, frame)
                       for frame in features.onset_raw_frames)
        actions.extend((epoch_index, event.candidate_sample, 1, record, event)
                       for event in features.diagnostic_events)
    # Source batches may contain several hops and delayed candidates. Preserve
    # the same causal reference whether records arrive singly or in a batch.
    for _, _, kind, record, item in sorted(actions, key=lambda row: row[:3]):
        if kind == 0:
            gate.observe(record.epoch, item)
            continue
        features, event = record.features, item
        if not gate.accepts(event, features.onset_bass_strength):
            continue
        offset = (event.candidate_sample-record.sample_pos)/48000
        events.append(replace(event, kind="beat", on_beat=False,
            received_monotonic=(features.received_monotonic+offset
                                if features.received_monotonic is not None else None),
            play_monotonic=(features.play_monotonic+offset
                            if features.play_monotonic is not None else None)))
    return events
