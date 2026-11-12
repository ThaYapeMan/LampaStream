"""Isolated six-minute grid RSS measurement; invoked by test_grid_memory."""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


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
    command = ['nice', '-n', '10', sys.executable, '-m',
               'lampastream.grid.analyser', str(path)]
    if '--profile-memory' in sys.argv:
        command.append('--profile-memory')
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    print(completed.stderr, file=sys.stderr, end='')
    completed.check_returncode()
    peak = int(re.search(r'Grid worker peak_rss_bytes=(\d+)', completed.stderr)[1])
    print(json.dumps(dict(grid=json.loads(completed.stdout), peak_rss_bytes=peak)))
