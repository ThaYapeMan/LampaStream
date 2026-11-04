"""Synthetic CSVs identify producer pacing and mismatched reader clocks."""
import csv
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'clock_rate_probe', Path(__file__).resolve().parents[1] / 'scripts/clock-rate-probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.mark.parametrize(('pacer', 'reader', 'expected'), [
    (1., 1., 'none'),
    (.9995, 1., '1. Producer pacer rate, 2. Arrival rate, 3. Content rate'),
    (1., .9995, '2. Arrival rate, 3. Content rate, '
     '4. Stamp clock vs reader clock, 5. Pipeline mapping'),
])
def test_synthetic_csv(tmp_path, pacer, reader, expected):
    path = tmp_path / 'synthetic.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=probe.FIELDS)
        writer.writeheader()
        for i in range(1200):
            t = i/10
            writer.writerow(dict(t_mono=1000+t*reader, t_wall=1700000000+t,
                                 abs_write_pos=t*48000*pacer,
                                 ynpt_anchor_frame=t*48000*pacer,
                                 ynpt_play_mono_ns=(1000+t)*1e9, ynpt_rate=48000,
                                 ynpt_flags=0, ynpt_event_sequence=1,
                                 content_frame=t*48000*pacer, content_flags=1,
                                 generation=1, gap_seq=0, running=1,
                                 lampastream_audible_t=1000+t))
    report = probe.analyse(path)
    print(report)
    assert report.splitlines()[-1] == 'Deviates beyond ±30 ppm: ' + expected
    assert report.count('(SE ') == 5


def test_short_capture_is_not_reported_as_exact(tmp_path):
    path = tmp_path / 'empty.csv'
    path.write_text(','.join(probe.FIELDS)+'\n')
    assert 'insufficient data' in probe.analyse(path)
