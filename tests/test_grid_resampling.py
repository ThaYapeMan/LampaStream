"""Private acceptance: resampler/noise robustness across canonical ingress routes."""
import io
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from lampastream.grid.analyser import analyse, canonical_decode

FIXTURES = (
    ('mau-p', 'LAMPASTREAM_GRID_FIXTURE'),
    ('udkm', 'LAMPASTREAM_GRID_FIXTURE_UDKM'),
    ('lou', 'LAMPASTREAM_GRID_FIXTURE_LOU'),
)


def fixture_path(variable):
    if not os.environ.get(variable):
        pytest.skip(f'private fixture: set {variable}')
    return Path(os.environ[variable])


@pytest.mark.parametrize('name,variable', FIXTURES)
def test_private_flags_survive_resampler_and_minus_90_dbfs_dither(tmp_path, name, variable):
    source = fixture_path(variable)
    variants = [('native-canonical', source)]
    for resampler in ('swr', 'soxr'):
        output = tmp_path/f'{resampler}.flac'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-af',
                        f'aresample=48000:resampler={resampler}', '-sample_fmt', 's16',
                        '-c:a', 'flac', str(output)],
                       check=True, capture_output=True, timeout=120)
        variants.append((resampler, output))
    counts = []
    rng = np.random.default_rng(90001)
    for label, path in variants:
        raw = path.read_bytes()
        for dither in (False, True):
            if dither:
                pcm, rate, *_ = canonical_decode(raw)
                # Generate in chunks to keep test preparation bounded too.
                noisy = io.BytesIO()
                with sf.SoundFile(noisy, 'w', samplerate=rate, channels=2,
                                  format='WAV', subtype='FLOAT') as stream:
                    for start in range(0, len(pcm), 16384):
                        block = pcm[start:start+16384]
                        noise = rng.normal(0, 10**(-90/20), block.shape).astype(np.float32)
                        stream.write(block+noise)
                data = noisy.getvalue()
            else:
                data = raw
            grid = analyse(data)
            count = sum(grid.kick_flags)
            counts.append(count)
            print(f'{name} {label} dither={dither} '
                  f'tempo={grid.tempo:.6f} beats={len(grid.beats)} flags={count}', flush=True)
    assert max(counts)-min(counts) <= .01*min(counts)
