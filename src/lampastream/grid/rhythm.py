"""Non-neural section band and bar estimates on the shared attack envelopes."""
from dataclasses import replace
from itertools import groupby

import numpy as np

from . import Section


def beat_energy(beats, envelope, step, *, radius=.03):
    values = []
    for beat in beats:
        start = max(0, int((beat-radius)/step))
        end = min(len(envelope), int((beat+radius)/step)+1)
        values.append(float(np.max(envelope[start:end])) if start < end else 0.)
    return np.asarray(values)


def estimate_bar(energy):
    """Choose 3/4 by periodicity and the strongest beat-1 phase.

    Equal beats deliberately have zero confidence. Section-start alignment is
    only a tie breaker and cannot create confidence on an unaccented pattern.
    """
    energy = np.asarray(energy, dtype=float)
    if len(energy) < 12 or not np.any(energy):
        return 4, 0, 0.
    centered = energy-np.mean(energy)
    choices = []
    for length in (3, 4):
        means = np.array([np.mean(energy[phase::length]) for phase in range(length)])
        phase = int(np.argmax(means+np.r_[np.mean(energy)*.03, np.zeros(length-1)]))
        ordered = sorted(means, reverse=True)
        contrast = max(0., (means[phase]-ordered[1])/max(1e-12, means[phase]))
        left, right = centered[:-length], centered[length:]
        norm = float(np.linalg.norm(left)*np.linalg.norm(right))
        periodicity = max(0., float(np.dot(left, right))/norm) if norm > 1e-12 else 0.
        confidence = min(1., 2*contrast)*periodicity*min(1., len(energy)/24)
        choices.append((confidence, length == 4, length, phase))
    confidence, _, length, phase = max(choices)
    return length, phase, float(np.clip(confidence, 0, 1))


def describe(beats, flags, tempo_sections, bands, step, duration):
    """Add bar metadata and hysteretic carrying-band sections; never move beats.

    Existing bass-drum flags stay authoritative. In their absence, a carrier
    requires on/off attack ratio >2 across four bars. A sub-four-beat fragment
    inherits the preceding carrier instead of alternating individual decisions.
    """
    beats, flags = np.asarray(beats), np.asarray(flags, dtype=bool)
    on = {band: beat_energy(beats, values, step) for band, values in bands.items()}
    labels = np.where(flags, 'low', 'none').astype(object)
    tempos, rhythm, downbeats = [], [], []
    for section in tempo_sections:
        indices = np.flatnonzero((beats >= section.start-1e-8) & (beats < section.end-1e-8))
        if not len(indices):
            continue
        period = 60/section.tempo
        off = {band: beat_energy(beats[indices]+period/2, values, step)
               for band, values in bands.items()}
        local = labels[indices].copy()
        cursor = 0
        for present, group in groupby(flags[indices]):
            stop = cursor+len(list(group))
            if not present:
                previous = 'none'
                for start in range(cursor, stop, 16):
                    end = min(stop, start+16)
                    if end-start < 4:
                        local[start:end] = previous
                        continue
                    candidates = []
                    for band in ('mid', 'high'):
                        value = float(np.median(on[band][indices[start:end]]))
                        background = float(np.median(off[band][start:end]))
                        ratio = value/max(1e-12, background)
                        if value > 1e-8 and ratio > 2:
                            candidates.append((ratio, band))
                    previous = max(candidates)[1] if candidates else 'none'
                    local[start:end] = previous
            cursor = stop
        labels[indices] = local
        # Normalise bands separately so a quiet riff can support a bar pattern
        # without its absolute level competing with the bass drum's amplitude.
        pattern = on['low'][indices].copy()
        pattern /= max(1e-12, float(np.percentile(pattern, 90)))
        for band in ('mid', 'high'):
            values = on[band][indices]
            pattern += .25*values/max(1e-12, float(np.percentile(values, 90)))
        length, phase, confidence = estimate_bar(pattern)
        dominant = max(('low', 'mid', 'high', 'none'), key=lambda band: np.sum(local == band))
        tempos.append(replace(section, beat_band=dominant, bar_length=length,
                              bar_phase=(-phase) % length, downbeat_confidence=confidence))
        downbeats.extend(map(float, beats[indices[phase::length]]))
        cursor = 0
        for band, group in groupby(local):
            stop = cursor+len(list(group))
            start_time = float(beats[indices[cursor]])
            end_time = float(beats[indices[stop]]) if stop < len(indices) else section.end
            rhythm.append(Section('rhythm', start_time, min(duration, end_time), section.tempo,
                                  str(band), length, (cursor-phase) % length, confidence))
            cursor = stop
    return tuple(tempos), tuple(rhythm), tuple(sorted(set(downbeats)))
