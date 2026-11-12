"""Isolated six-minute grid RSS measurement; invoked by test_grid_memory."""
import json
import resource
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from lampastream.grid.analyser import analyse


def generate(path, rate):
    # One second of storage regardless of rate or duration; do not count a
    # six-minute native-rate generator array as analyser memory.
    t = np.arange(rate, dtype=np.float32)/rate
    y = np.zeros(rate, np.float32)
    for start in (0., .5):
        dt = t-start
        y += np.where((dt >= 0) & (dt < .1),
                      np.sin(2*np.pi*80*dt)*np.exp(-np.maximum(dt, 0)*40), 0)
    with sf.SoundFile(path, 'w', samplerate=rate, channels=2, format='FLAC') as out:
        for _ in range(360):
            out.write(np.column_stack((y, y)))


if __name__ == '__main__':
    path, rate = Path(sys.argv[1]), int(sys.argv[2])
    generate(path, rate)
    result = analyse(path.read_bytes())
    print(json.dumps(dict(grid=result.to_dict(),
                          peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)))
