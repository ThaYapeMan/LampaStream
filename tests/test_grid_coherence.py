"""Local phase coherence must not veto a whole tempo section."""
import numpy as np

from lampastream.grid.analyser import kick_evidence


def evidence(offset_scale, count=120):
    beats = 1+np.arange(count)*.5
    offsets = np.tile(np.linspace(-1, 1, 11), (count+10)//11)[:count]*offset_scale
    energy = np.zeros(round((beats[-1]+1)/.001), np.float32)
    energy[np.rint((beats+offsets)/.001).astype(int)] = 1
    energy[np.rint((beats+.25)/.001).astype(int)] = .2
    return beats, energy


def test_coherence_near_old_threshold_preserves_supported_kicks():
    counts = []
    for scale in (.035, .04):
        beats, energy = evidence(scale)
        counts.append(np.count_nonzero(kick_evidence(beats, energy, .001, .5)[0]))
    assert min(counts) >= 115
    assert max(counts)-min(counts) <= 1


def test_remote_incoherent_tail_cannot_erase_coherent_prefix():
    beats, energy = evidence(.004)
    before = kick_evidence(beats, energy, .001, .5)[0]
    following, tail = evidence(.065, count=120)
    following += beats[-1]+.5
    combined = np.zeros(round((following[-1]+1)/.001), np.float32)
    combined[:len(energy)] = energy
    start = round((beats[-1]+.5)/.001)
    combined[start:start+len(tail)] += tail[:len(combined)-start]
    after = kick_evidence(np.r_[beats, following], combined, .001, .5)[0]
    assert np.array_equal(after[:len(before)-8], before[:-8])
