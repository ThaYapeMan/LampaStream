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
    assert report.splitlines()[-1] == (
        'Deviates beyond ±30 ppm: ' + expected + '; insufficient data for 6')
    assert report.count('(SE ') == 5


def test_short_capture_is_not_reported_as_exact(tmp_path):
    path = tmp_path / 'empty.csv'
    path.write_text(','.join(probe.FIELDS)+'\n')
    assert 'insufficient data' in probe.analyse(path)


@pytest.mark.parametrize(('position_rate', 'delay_rate', 'residual_rate'), [
    (1., 0., 0.), (1.0005, .455, .5), (.9995, -.4, -.5),
])
def test_service_slopes_and_original_five_lines(tmp_path, position_rate, delay_rate, residual_rate):
    path = tmp_path / 'service.csv'
    rows = []
    for i in range(360):
        t = 1000+i
        rows.append(dict(t_mono=t, t_wall=t, abs_write_pos=i*48000,
                         ynpt_anchor_frame=i*48000, ynpt_play_mono_ns=t*1e9,
                         ynpt_rate=48000, ynpt_flags=0, ynpt_event_sequence=1,
                         content_frame=i*48000, content_flags=1, generation=1,
                         gap_seq=0, running=1, lampastream_audible_t=t,
                         **probe.service_sample(dict(type='status',
                             track=dict(position_s=i*position_rate),
                             applied_delay_ms=-70+i*delay_rate,
                             light_timing=dict(status=dict(session_offset_ms=12,
                                 median_residual_ms=80+i*residual_rate))), t)))

    def report(data):
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=probe.FIELDS)
            writer.writeheader()
            writer.writerows(data)
        return probe.analyse(path)

    result = report(rows)
    print(result)
    assert f'6. Service position: {(position_rate-1)*1e6:+.3f} ppm' in result
    assert f'applied_delay_ms: {delay_rate:+.6f} ms/s' in result
    assert f'median_residual_ms: {residual_rate:+.6f} ms/s' in result
    assert ('6. Service position' in result.splitlines()[-1]) == (position_rate != 1.)
    original = report([{k: v for k, v in row.items() if k not in {
        'service_t_mono', 'service_position_s',
        'applied_delay_ms', 'session_offset_ms', 'median_residual_ms'}} for row in rows])
    assert result.splitlines()[2:7] == original.splitlines()[2:7]


def test_service_missing_status_and_consumed_samples():
    sample = probe.service_sample({'type': 'status'}, 123.)
    assert sample['service_position_s'] is None
    assert sample['median_residual_ms'] is None
    assert sample['applied_delay_ms'] is None
    service = probe.ServiceStatus('unused')
    service.pending = sample
    assert service.take() == sample
    assert service.take() == {}  # no stale repeats at the SHM poll frequency


def test_service_sample_preserves_delivered_position_and_zero_values():
    sample = probe.service_sample(dict(track=dict(position_s=0.),
        applied_delay_ms=0., light_timing=dict(status=dict(
            session_offset_ms=-70., median_residual_ms=0.))), 12.)
    assert sample == dict(service_t_mono=12., service_position_s=0.,
                          applied_delay_ms=0.,
                          session_offset_ms=-70., median_residual_ms=0.)


@pytest.mark.serial
def test_service_websocket_sampling_and_shutdown(monkeypatch):
    from contextlib import nullcontext

    service = probe.ServiceStatus('ws://example/ws/preview')
    messages = iter([
        dict(type='event'),
        dict(type='status', track=dict(position_s=10.)),
        dict(type='status', track=dict(position_s=10.2)),
        dict(type='status', track=dict(position_s=11.)),
    ])
    stamps = iter([100., 100., 100.2, 101.])
    seen = []

    class Socket:
        def recv(self, timeout):
            assert timeout == .5
            try:
                return probe.json.dumps(next(messages))
            except StopIteration:
                service.stop.set()
                raise TimeoutError from None

    def sample(message, mono):
        seen.append((message['track']['position_s'], mono))
        return {'service_t_mono': mono}

    def connect(url, **kwargs):
        assert url == service.url
        assert kwargs == dict(open_timeout=2, close_timeout=1)
        return nullcontext(Socket())

    monkeypatch.setattr('websockets.sync.client.connect', connect)
    monkeypatch.setattr(probe.time, 'monotonic', lambda: next(stamps))
    monkeypatch.setattr(probe, 'service_sample', sample)
    with service:
        service.thread.join(timeout=2)
    assert not service.thread.is_alive()
    assert seen == [(10., 100.), (11., 101.)]
