#!/usr/bin/env python3
"""Read-only SHM v1 / native-clock rate diagnostic; no shared consumer cursor.

The independent reader owns only an ACCESS_READ mapping and local bookkeeping.
No PCM read(), readiness action, player preference or transport command is used.
The native pipeline maps content_frame to anchor_abs_frame with PlayerClock.at;
LmsAudibleClock.at supplies the final sample-coordinate mapping. Constant room
calibration is omitted (it cannot affect a slope). This is a parallel diagnostic
mapping, not inspection of the running service's adaptive calibration state.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lampastream.audible_clock import LmsAudibleClock  # noqa: E402
from lampastream.lms_follower import _cli_exchange  # noqa: E402
from lampastream.pcm_source import YeneyCoreShmStereoSource  # noqa: E402

FIELDS = ('t_mono t_wall abs_write_pos ynpt_anchor_frame ynpt_play_mono_ns ynpt_rate '
          'ynpt_flags ynpt_event_sequence content_frame content_flags generation gap_seq '
          'write_seq running lampastream_audible_t lms_own lms_followed lms_own_mono '
          'lms_followed_mono service_t_mono service_position_s applied_delay_ms '
          'session_offset_ms median_residual_ms service_observed_at').split()
NAMES = ('Producer pacer rate', 'Arrival rate', 'Content rate',
         'Stamp clock vs reader clock', 'Pipeline mapping', 'Service position')


def fit(points):
    """Centered ordinary least squares; standard error of slope (iid residuals)."""
    if len(points) < 3:
        return None
    x0, y0 = points[0]
    xs, ys = zip(*[(x-x0, y-y0) for x, y in points], strict=True)
    mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
    xx = sum((x-mx)**2 for x in xs)
    if not xx:
        return None
    slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys, strict=True))/xx
    residual = sum((y-my-slope*(x-mx))**2 for x, y in zip(xs, ys, strict=True))
    return slope, math.sqrt(residual/(len(xs)-2)/xx), len(xs)


def service_sample(message, mono):
    """Keep the A/B websocket's reported anchor verbatim, at receipt time."""
    track = message.get('track') or {}
    status = (message.get('light_timing') or {}).get('status') or {}
    return dict(service_t_mono=mono, service_position_s=track.get('position_s'),
                service_observed_at=track.get('observed_at'),
                applied_delay_ms=message.get('applied_delay_ms'),
                session_offset_ms=status.get('session_offset_ms'),
                median_residual_ms=status.get('median_residual_ms'))


class ServiceStatus:
    """Drain the same websocket as ab-logger without blocking SHM polling.

    Sample at most once per second. A disconnected service leaves empty CSV
    cells, never repeated stale values or fabricated zeroes.
    """

    def __init__(self, url):
        self.url = url
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.pending = {}
        self.thread = threading.Thread(target=self.run, daemon=True)

    def take(self):
        with self.lock:
            result, self.pending = self.pending, {}
        return result

    def run(self):
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect
        while not self.stop.is_set():
            try:
                with connect(self.url, open_timeout=2, close_timeout=1) as socket:
                    next_sample = 0.
                    while not self.stop.is_set():
                        try:
                            message = json.loads(socket.recv(timeout=.5))
                        except TimeoutError:
                            continue
                        mono = time.monotonic()
                        if message.get('type') == 'status' and mono >= next_sample:
                            with self.lock:
                                self.pending = service_sample(message, mono)
                            next_sample = mono + 1
            except (OSError, ValueError, WebSocketException) as exc:
                print(f'Service position: {exc}', file=sys.stderr)
                self.stop.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=5)


def analyse(path):
    with Path(path).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    groups = []
    previous = None
    for row in rows:
        key = tuple(row[k] for k in ('generation', 'gap_seq', 'ynpt_event_sequence',
                                     'ynpt_rate', 'content_flags', 'running'))
        if key != previous:
            groups.append([])
            previous = key
        groups[-1].append(row)
    output = ['Clock-rate report (first 15 s discarded per continuous segment; '
              'OLS standard errors assume independent residuals)']
    bad = set()
    available = set()
    for index, group in enumerate(groups, 1):
        start = float(group[0]['t_mono'])
        selected = [r for r in group if float(r['t_mono']) >= start+15
                    and r['running'] == '1']
        if not selected:
            continue
        rate = float(selected[0]['ynpt_rate'])
        output.append(f'Segment {index}: nominal {rate:g} Hz')
        specs = [('ynpt_play_mono_ns', 'ynpt_anchor_frame', 1e-9, rate),
                 ('t_mono', 'abs_write_pos', 1., rate),
                 ('t_mono', 'content_frame', 1., rate),
                 ('t_mono', 'ynpt_play_mono_ns', 1., 1e9),
                 ('t_mono', 'lampastream_audible_t', 1., 1.)]
        for number, (x, y, scale, nominal) in enumerate(specs, 1):
            points = [(float(r[x])*scale, float(r[y])) for r in selected if r[y]]
            if number == 1:
                points = list(dict.fromkeys(points))
            result = fit(points)
            if result is None:
                output.append(f'{number}. {NAMES[number-1]}: insufficient points')
                continue
            slope, error, n = result
            ppm, se = (slope/nominal-1)*1e6, error/nominal*1e6
            available.add(number)
            if abs(ppm) > 30:
                bad.add(number)
            output.append(f'{number}. {NAMES[number-1]}: {ppm:+.3f} ppm '
                          f'(SE {se:.3f} ppm; n={n}; slope={slope:.9g})')
        service = fit([(float(r['service_t_mono']), float(r['service_position_s']))
                       for r in selected if r.get('service_t_mono')
                       and r.get('service_position_s')])
        if service:
            slope, error, n = service
            ppm = (slope-1)*1e6
            available.add(6)
            if abs(ppm) > 30:
                bad.add(6)
            output.append(f'6. Service position: {ppm:+.3f} ppm '
                          f'(SE {error*1e6:.3f} ppm; n={n}; slope={slope:.9g})')
        else:
            output.append('6. Service position: insufficient points')
        for field in ('applied_delay_ms', 'median_residual_ms'):
            result = fit([(float(r['service_t_mono']), float(r[field]))
                          for r in selected if r.get('service_t_mono') and r.get(field)])
            if result:
                slope, error, n = result
                output.append(f'{field}: {slope:+.6f} ms/s (SE {error:.6f}; n={n})')
            else:
                output.append(f'{field}: insufficient points')
        edges = {}
        for field in ('lms_own', 'lms_followed'):
            points = []
            last = None
            for row in selected:
                if not row.get(field):
                    continue
                value = math.floor(float(row[field]))
                if last is not None and value != last:
                    points.append((float(row[field+'_mono']), float(row[field])))
                last = value
            edges[field] = points
            result = fit(points)
            if result:
                slope, error, n = result
                output.append(f'{field} edges: {(slope-1)*1e6:+.3f} ppm '
                              f'(SE {error*1e6:.3f} ppm; n={n})')
        # Regress each edge series at its own query timestamps; difference of
        # slopes avoids treating sequential CLI replies as simultaneous samples.
        own, followed = (fit(edges[k]) for k in ('lms_own', 'lms_followed'))
        if own and followed:
            output.append(f'LMS own-followed: {(own[0]-followed[0])*1000:+.6f} ms/s '
                          f'(SE {math.hypot(own[1], followed[1])*1000:.6f}; '
                          f'n={own[2]}/{followed[2]})')
    output.append('Deviates beyond ±30 ppm: ' +
                  (', '.join(f'{i}. {NAMES[i-1]}' for i in sorted(bad)) or 'none') +
                  ('; insufficient data for ' + ', '.join(map(str, set(range(1, 7))-available))
                   if len(available) < 6 else ''))
    return '\n'.join(output)


def capture(args):
    source = YeneyCoreShmStereoSource()
    clock = LmsAudibleClock()
    host = None
    if args.lms:
        config = json.loads(Path(args.config).read_text())
        player = next(p for p in config['virtual_players'] if p['player_mac'] == args.mac)
        host = player['lms_host']
        if not args.followed_mac:
            raise ValueError('--lms requires --followed-mac')
    source.open(args.mac)
    deadline = time.monotonic()+args.seconds
    next_poll = time.monotonic()
    next_lms = next_poll
    try:
        with (ServiceStatus(args.service_url) as service,
              Path(args.csv).open('w', newline='') as stream):
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            while time.monotonic() < deadline:
                if source._detect_shm_replacement():
                    source.close()
                    source.open(args.mac)
                ext = source._read_ext_coherent()
                mono, wall = time.monotonic(), time.time()
                if ext is not None and ext.timing is not None:
                    stamp = ext.timing
                    # content_frame is published at anchor_abs_frame. This is
                    # precisely the native ingress mapping, not content/rate.
                    features = SimpleNamespace(play_monotonic=stamp.at(stamp.anchor_abs_frame),
                                               received_monotonic=mono, timing_generation=None)
                    point = clock.at(stamp.content_frame, stamp.content_frame, features, mono)
                    row = dict(zip(FIELDS[:15], (
                        mono, wall, ext.abs_write_pos, stamp.anchor_abs_frame,
                        stamp.anchor_play_mono_ns, stamp.rate_milli_hz/1000,
                        stamp.event_flags, stamp.event_seq, stamp.content_frame,
                        stamp.content_flags, ext.generation, ext.gap_seq, ext.write_seq,
                        int(ext.legacy_header[2]), point.audible), strict=True))
                    if host and mono >= next_lms:
                        for field, mac in (('lms_own', args.mac),
                                           ('lms_followed', args.followed_mac)):
                            before = time.monotonic()
                            try:
                                reply = _cli_exchange(host, 9090, f'{mac} time ?\n')
                                row[field] = float(unquote(reply).split()[-1])
                                row[field+'_mono'] = (before+time.monotonic())/2
                            except (OSError, ValueError) as exc:
                                print(f'{field}: {exc}', file=sys.stderr)
                        next_lms = time.monotonic()+1
                    row.update(service.take())
                    writer.writerow(row)
                    stream.flush()
                next_poll += 1/args.hz
                time.sleep(max(0., next_poll-time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    print(analyse(args.csv))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analyse', metavar='CSV')
    parser.add_argument('--csv', default='clock-rate.csv')
    parser.add_argument('--mac')
    parser.add_argument('--seconds', type=float, default=360)
    parser.add_argument('--hz', type=float, default=100)
    parser.add_argument('--lms', action='store_true')
    parser.add_argument('--service-url', default='ws://127.0.0.1:8420/ws/preview',
                        help='same status websocket as ab-logger.py')
    parser.add_argument('--followed-mac')
    parser.add_argument('--config', default=os.environ.get('LAMPASTREAM_CONFIG',
                                                         '/etc/lampastream/config.json'))
    args = parser.parse_args()
    if args.analyse:
        print(analyse(args.analyse))
    elif not args.mac or args.hz < 20 or args.seconds <= 0:
        parser.error('capture requires --mac, --hz >= 20 and --seconds > 0')
    else:
        capture(args)


if __name__ == '__main__':
    main()
