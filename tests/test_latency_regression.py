"""LAT-01 software targets; physical transport and lamps are outside replay."""
import csv
import json

import pytest


@pytest.mark.parametrize('fixture', ['clicks-120', 'clicks-128', 'clicks-174', 'impulse'])
@pytest.mark.parametrize('route', ['normal', 'timestamped'])
@pytest.mark.parametrize('hz', [30, 60])
def test_software_latency(replay_cache, fixture, route, hz):
    replay = replay_cache.get(fixture, route, hz)
    with (replay['out']/'latency.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(replay['truth'])
    assert all(row['first_send_ms'] for row in rows)
    measured = replay['counters']['latency'][route]
    if route == 'normal':
        assert measured['first_send_ms']['median'] <= 30
        assert measured['first_send_ms']['max'] <= 40
    else:
        # Deadline scheduling and truth-relative timing are independent checks.
        assert max(abs(float(row['schedule_error_ms'])) for row in rows) <= 5
        # Default replay playback lead 1.5 s, positive light advance 20 ms;
        # midpoint estimation leaves at most half a 10 ms hop of truth error.
        assert max(abs(float(row['first_send_ms'])-1480) for row in rows) <= 5
    for row in rows:
        terms = sum(float(row[k]) for k in ('window_acquisition_ms', 'hop_ms',
                    'lookahead_ms', 'tick_wait_ms', 'schedule_wait_ms'))
        assert terms == pytest.approx(float(row['first_send_ms']), abs=3e-6, rel=0)


@pytest.mark.parametrize('fixture', ['clicks-120', 'clicks-174', 'pink-noise'])
@pytest.mark.parametrize('hz', [30, 60])
def test_event_send_spacing_and_one_per_drain(replay_cache, fixture, hz):
    stats = replay_cache.get(fixture, hz=hz)['counters']['extra_sends']
    assert stats['sends'] > 0
    assert stats['max_per_drain'] == 1
    assert stats['smallest_gap_s'] >= stats['minimum_interval_s']-1e-6


def test_bass_long_and_treble_short_align_on_same_click(replay_cache):
    replay = replay_cache.get('clicks-174', method='multiband')
    for target in replay['truth']:
        event = min(replay['events'], key=lambda e: abs(int(e['candidate_sample'])-target))
        assert abs(int(event['candidate_sample'])-target) <= 480
        assert {'bass', 'treble'} <= set(json.loads(event['bands']))


@pytest.mark.parametrize('fixture', ['silence', 'sweep', 'pink-noise'])
@pytest.mark.parametrize('route', ['normal', 'timestamped'])
def test_idle_colour_bytes_match_phase_two(replay_cache, tmp_path, fixture, route):
    import hashlib
    from pathlib import Path

    from replay_chain import parser

    root = Path(__file__).resolve().parents[1]
    pins = json.loads((root/'tests/fixtures/phase2-no-onset-colours.json').read_text())
    config = json.loads((root/'tests/fixtures/replay/default-config.json').read_text())
    config['configuration']['analysers'][0]['onset_delta_abs'] = 1e9
    config_path = tmp_path/'no-onsets.json'
    config_path.write_text(json.dumps(config))
    args = parser().parse_args(['--input', str(root/f'tests/fixtures/replay/{fixture}.wav'),
        '--config', str(config_path), '--route', route, '--out', str(tmp_path/'trace')])
    out = replay_cache.disk.run(args)
    counters = json.loads((out/'counters.json').read_text())
    assert counters['events']['all']['received'] == 0
    with (out/'sends.csv').open() as stream:
        rows = [[r[k] for k in pins['columns']] for r in csv.DictReader(stream)]
    expected = pins['traces'][f'{fixture}/{route}']
    assert len(rows) == expected['rows']
    raw = json.dumps(rows, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == expected['sha256']
