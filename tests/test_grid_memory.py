"""Canonical file ingress, stereo accents and the CI memory regression."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from lampastream.grid.analyser import analyse, decode, low_band_attacks
from lampastream.grid.worker import THREAD_VARIABLES, worker_environment


def stereo_clicks(layout):
    rate = 48000
    y = np.zeros((rate*16, 2), np.float32)
    t = np.arange(4800)/rate
    kick = (np.sin(2*np.pi*80*t)*np.exp(-t*40)).astype(np.float32)
    hat = (.05*np.sin(2*np.pi*5000*t)*np.exp(-t*120)).astype(np.float32)
    for beat in np.arange(.5, 15.6, .5):
        start = round(beat*rate)
        if layout == 'centre':
            y[start:start+len(kick)] += kick[:, None]
            y[start:start+len(hat)] += hat[:, None]
        else:
            y[start:start+len(kick), 0] += kick
            if layout == 'panned':
                y[start:start+len(hat), 1] -= hat
    out = io.BytesIO()
    sf.write(out, y, rate, format='FLAC', subtype='PCM_24')
    return out.getvalue()


def test_stereo_accents_preserve_strength_and_grid():
    centre = analyse(stereo_clicks('centre'))
    for layout in ('panned', 'left-only'):
        raw = stereo_clicks(layout)
        result = analyse(raw)
        assert result.beats == pytest.approx(centre.beats, abs=.002)
        assert result.kick_flags == centre.kick_flags
        assert all(k for b, k in zip(result.beats, result.kick_flags, strict=True) if b > .25)
        stereo, rate, _ = decode(raw)
        combined, _, _ = low_band_attacks(stereo, rate)
        left, _, _ = low_band_attacks(stereo[:, 0], rate)
        assert combined.max() == pytest.approx(left.max(), rel=1e-6)
        anti_phase = np.column_stack((stereo[:, 0], -stereo[:, 0]))
        assert np.array_equal(low_band_attacks(anti_phase, rate)[0], left)
        assert combined.max() > 1.99*low_band_attacks(stereo.mean(axis=1), rate)[0].max()


@pytest.mark.grid_memory
def test_six_minute_rates_have_same_grid_under_one_gb(tmp_path):
    grids, peaks = [], []
    for rate in (44100, 96000, 192000):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name('grid_memory_probe.py')),
             str(tmp_path/f'{rate}.flac'), str(rate)],
            capture_output=True, text=True, check=True, timeout=180)
        measurement = json.loads(completed.stdout)
        print(f'rate={rate} peak_rss_bytes={measurement["peak_rss_bytes"]}')
        peaks.append(measurement['peak_rss_bytes'])
        grid = measurement['grid']
        assert grid['sample_rate'] == 48000
        assert grid['source_sample_rate'] == rate
        assert grid['source_channels'] == 2
        assert grid['duration'] == 360
        grids.append(grid)
    if max(peaks) >= 1_000_000_000:
        rate = (44100, 96000, 192000)[int(np.argmax(peaks))]
        profile = subprocess.run(
            [sys.executable, str(Path(__file__).with_name('grid_memory_probe.py')),
             str(tmp_path/'profile.flac'), str(rate), '--profile-memory'],
            capture_output=True, text=True, timeout=360)
        print(f'Profile rate={rate} exit={profile.returncode}\n{profile.stderr}', flush=True)
    assert max(peaks) < 1_000_000_000
    for grid in grids[1:]:
        assert grid['beats'] == pytest.approx(grids[0]['beats'], abs=.002)
        assert grid['kick_flags'] == grids[0]['kick_flags']


def test_worker_allocation_failure_logs_tracker_fallback(tmp_path):
    path = tmp_path/'clicks.flac'
    path.write_bytes(stereo_clicks('centre'))
    code = '''
import os
import resource
from lampastream.grid.worker import worker_environment
os.environ.update(worker_environment())
import lampastream.grid.analyser as analyser
original = analyser.limit_address_space
def constrained(duration, **kwargs):
    original(duration, **kwargs)
    from pathlib import Path
    current = int(Path('/proc/self/statm').read_text().split()[0])*resource.getpagesize()
    resource.setrlimit(resource.RLIMIT_AS, (current+65536, resource.RLIM_INFINITY))
    return current+65536
analyser.limit_address_space = constrained
raise SystemExit(analyser.main())
'''
    completed = subprocess.run(
        [sys.executable, '-c', code, str(path)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 1  # A handled exit, never a signal/OOM kill.
    assert not completed.stdout
    assert 'Grid analysis unavailable; retaining tracker:' in completed.stderr
    assert 'MemoryError' in completed.stderr or 'Cannot allocate memory' in completed.stderr


def test_bounded_spectral_work_matches_librosa_defaults():
    import librosa

    from lampastream.grid.analyser import global_tempo, onset_envelope

    rng = np.random.default_rng(68)
    y = rng.normal(0, .05, 48000*4).astype(np.float32)
    expected = librosa.onset.onset_strength(y=y, sr=48000, hop_length=512, aggregate=np.median)
    actual = onset_envelope(y, 48000)
    np.testing.assert_allclose(actual, expected, atol=1e-5)
    assert np.array_equal(global_tempo(actual, 48000),
                          librosa.feature.tempo(onset_envelope=expected, sr=48000, hop_length=512))


def test_ffmpeg_native_mono_uses_canonicalizer_for_full_and_head(tmp_path):
    import hashlib
    import shutil

    from lampastream.grid.analyser import analyse_head, canonical_decode

    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for ALAC file ingress')
    source, encoded = tmp_path/'source.flac', tmp_path/'source.m4a'
    stereo, rate, _ = decode(stereo_clicks('left-only'))
    sf.write(source, stereo[:, 0], rate*2, format='FLAC')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-c:a', 'alac', str(encoded)],
                   check=True, capture_output=True, timeout=30)
    raw = encoded.read_bytes()
    audio, rate, lossless, native_rate, native_channels = canonical_decode(raw)
    assert (rate, lossless, native_rate, native_channels) == (48000, True, 96000, 1)
    assert audio.shape == (48000*8, 2)
    assert np.array_equal(audio[:, 0], audio[:, 1])
    head = analyse_head(raw, seconds=4)
    assert head.source_sample_rate == 96000 and head.source_channels == 1
    assert head.duration == 4 and head.sample_rate == 48000
    assert head.file_sha256 == hashlib.sha256(raw).hexdigest()


def test_head_worker_keeps_cold_numba_cache_unused(tmp_path):
    source = tmp_path/'clicks.flac'
    source.write_bytes(stereo_clicks('centre'))
    cache = tmp_path/'numba'
    completed = subprocess.run(
        [sys.executable, '-m', 'lampastream.grid.analyser', str(source), '--head'],
        capture_output=True, text=True, check=True, timeout=30,
        env={**{key: value for key, value in os.environ.items() if key not in THREAD_VARIABLES},
             'NUMBA_CACHE_DIR': str(cache)})
    assert json.loads(completed.stdout)['provisional']
    assert not cache.exists() or not list(cache.rglob('*.nbc'))
    assert 'Grid worker memory bound=' in completed.stderr
    for name in THREAD_VARIABLES:
        assert f"'{name}': '1'" in completed.stderr


def test_worker_environment_overrides_thread_counts_without_changing_parent(monkeypatch):
    for variable in THREAD_VARIABLES:
        monkeypatch.setenv(variable, '8')
    child = worker_environment()
    assert all(child[name] == '1' for name in THREAD_VARIABLES)
    assert all(os.environ[name] == '8' for name in THREAD_VARIABLES)
