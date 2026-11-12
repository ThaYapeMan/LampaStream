"""Canonical decoder continuity and the native-rate time-base probes."""
import subprocess

import numpy as np
import soundfile as sf
import soxr

from lampastream.grid.analyser import canonical_decode, stereo_attacks


def sine_file(path, seconds):
    rate = 44100
    time = np.arange(rate, dtype=np.float32)/rate
    second = np.repeat((.25*np.sin(2*np.pi*50*time))[:, None], 2, axis=1)
    with sf.SoundFile(path, 'w', samplerate=rate, channels=2,
                      format='FLAC', subtype='PCM_24') as stream:
        for _ in range(seconds):
            stream.write(second)


def test_sixty_second_sine_has_no_chunk_boundary_attack_artifacts(tmp_path):
    path = tmp_path/'sine.flac'
    sine_file(path, 60)
    actual, rate, *_ = canonical_decode(path.read_bytes())
    native, native_rate = sf.read(path, dtype='float32', always_2d=True)
    expected = soxr.resample(native, native_rate, rate, quality='HQ')
    assert len(actual) == 60*48000
    assert np.array_equal(actual, expected)
    attacks, _, _ = stereo_attacks(actual, rate)
    reference, _, _ = stereo_attacks(expected, rate)
    assert np.array_equal(attacks, reference)


def test_five_minute_flac_and_alac_have_exact_canonical_extent(tmp_path):
    path, alac = tmp_path/'sine.flac', tmp_path/'sine.m4a'
    sine_file(path, 300)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-c:a', 'alac', str(alac)],
                   check=True, capture_output=True, timeout=30)
    for source in (path, alac):
        actual, rate, lossless, source_rate, channels = canonical_decode(source.read_bytes())
        assert (rate, lossless, source_rate, channels) == (48000, True, 44100, 2)
        assert len(actual) == 300*48000
