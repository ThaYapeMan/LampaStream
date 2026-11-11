"""Rigid tempo sections and private, opt-in field acceptance."""
import asyncio
import io
import os
from itertools import groupby
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from test_grid import integration

from lampastream.grid import VERSION, TrackGrid
from lampastream.grid.analyser import (
    analyse,
    analyse_head,
    decode,
    fit_sections,
    kick_evidence,
    low_band_attacks,
)
from lampastream.grid.cache import GridCache

REFERENCE = Path(__file__).parent/'fixtures/ab-references'


def run_lengths(flags):
    return [len(list(group)) for _, group in groupby(flags)]


def synth(beats, duration, quiet=False):
    sr = 16000
    audio = np.zeros(round(sr*duration))
    indices = np.arange(1600)
    tone = np.sin(indices*2*np.pi*80/sr)*np.exp(-indices/250)
    for beat in beats:
        if quiet and beat < 20:
            continue
        start = round(beat*sr)
        end = min(len(audio), start+len(tone))
        audio[start:end] += tone[:end-start]*(.25 if quiet and beat < 60 else 1)
    output = io.BytesIO()
    sf.write(output, audio, sr, format='FLAC')
    return output.getvalue()


def test_quiet_intro_and_kickless_opening():
    expected = np.arange(.5, 89.8, 60/128)
    raw = synth(expected, 90, quiet=True)
    grid = analyse(raw)
    assert grid.tempo == pytest.approx(128, abs=.05)
    assert np.all(np.min(abs(expected[:, None]-grid.beats), axis=1) <= .01)
    assert min(run_lengths(grid.kick_flags)) >= 4
    assert not any(k for b, k in zip(grid.beats, grid.kick_flags, strict=True) if b < 20)
    assert all(k for b, k in zip(grid.beats, grid.kick_flags, strict=True) if 21 < b < 89)
    head = analyse_head(raw)
    assert not any(k for b, k in zip(head.beats, head.kick_flags, strict=True) if b < 19)


def test_two_tempo_sections():
    expected = np.r_[np.arange(.5, 90, 60/126), np.arange(90, 179.8, 60/130)]
    grid = analyse(synth(expected, 180))
    sections = [s for s in grid.sections if s.kind == 'tempo']
    assert len(sections) == 2
    assert [s.tempo for s in sections] == pytest.approx([126, 130], abs=.05)
    assert np.all(np.min(abs(expected[:, None]-grid.beats), axis=1) <= .01)


def test_expressive_positions_are_kept():
    intervals = 60/128*(1+.04*np.tile([-1, 1], 100))
    observed = .5+np.r_[0, np.cumsum(intervals)]
    energy = np.zeros(20000)
    energy[np.rint(observed/.005).astype(int)] = 1
    beats, _, _, _ = fit_sections(observed, energy, .005, 100)
    assert np.array_equal(beats, observed)


def test_old_grid_cache_is_rejected(tmp_path):
    grid = analyse(synth(np.arange(.5, 16, .5), 16))
    cache = GridCache(tmp_path)
    cache.put('file', grid)
    path = tmp_path/f'{grid.file_sha256}.json'
    import json
    data = json.loads(path.read_text())
    data['analyser_version'] = '1'
    path.write_text(json.dumps(data))
    assert cache.get('file') is None
    cache.put('file', grid)
    assert cache.get('file') == grid
    assert grid.analyser_version == VERSION == '2'
    assert TrackGrid.from_dict(grid.to_dict()) == grid


@pytest.mark.skipif(not os.environ.get('LAMPASTREAM_GRID_FIXTURE_UDKM'),
                    reason='private UDKM fixture')
def test_udkm_reference_and_loopback(tmp_path):
    path = Path(os.environ['LAMPASTREAM_GRID_FIXTURE_UDKM'])
    grid = analyse(path.read_bytes())
    ref = np.genfromtxt(REFERENCE/'avh-udkm/beats.csv', delimiter=',', names=True)
    nearest = abs(ref['time_s'][:, None]-grid.beats).argmin(axis=1)
    errors = abs(np.asarray(grid.beats)[nearest]-ref['time_s'])
    assert np.all(errors[ref['time_s'] <= 480] <= .01)
    assert grid.tempo == pytest.approx(129.985, abs=.05)
    assert np.mean(np.asarray(grid.kick_flags)[nearest] == ref['kick']) >= .98
    audio, sr, _ = decode(path.read_bytes())
    energy, hop, _ = low_band_attacks(audio, sr)
    _, ambiguous, _ = kick_evidence(np.asarray(grid.beats), energy, hop/sr, 60/grid.tempo)
    start = 0
    for _, group in groupby(grid.kick_flags):
        length = len(list(group))
        assert length >= 4 or not np.all(ambiguous[start:start+length])
        start += length
    head = analyse_head(path.read_bytes())
    assert not any(k for b, k in zip(head.beats, head.kick_flags, strict=True) if b < 28)
    asyncio.run(integration(path, tmp_path/'cache'))


@pytest.mark.skipif(not os.environ.get('LAMPASTREAM_GRID_FIXTURE_LOU'),
                    reason='private Lou Rawls fixture')
def test_lou_tempo_and_loopback(tmp_path):
    path = Path(os.environ['LAMPASTREAM_GRID_FIXTURE_LOU'])
    grid = analyse(path.read_bytes())
    assert grid.tempo == pytest.approx(77.10, abs=.1)
    asyncio.run(integration(path, tmp_path/'cache'))


@pytest.mark.skipif(not os.environ.get('LAMPASTREAM_GRID_FIXTURE'), reason='private Mau P fixture')
def test_mau_p_reference_acceptance():
    raw = Path(os.environ['LAMPASTREAM_GRID_FIXTURE']).read_bytes()
    grid = analyse(raw)
    reference = np.genfromtxt(REFERENCE/'mau-p-jalbm/beats.csv', delimiter=',', names=True)
    times = reference['time_s']
    nearest = abs(times[:, None]-grid.beats).argmin(axis=1)
    errors = abs(np.asarray(grid.beats)[nearest]-times)
    truth = reference['kick'].astype(bool)
    flags = np.asarray(grid.kick_flags)[nearest]
    assert grid.tempo == pytest.approx(127.998, abs=.05)
    assert np.all(errors[:797] <= .01)
    assert np.count_nonzero(flags & truth) == 653
    assert np.count_nonzero(flags & ~truth) == 0
    assert len([s for s in grid.sections if s.kind == 'break']) == 9
