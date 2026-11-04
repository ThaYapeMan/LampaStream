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
          'lms_followed_mono').split()
NAMES = ('Producer pacer rate', 'Arrival rate', 'Content rate',
         'Stamp clock vs reader clock', 'Pipeline mapping')


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
                  ('; insufficient data for ' + ', '.join(map(str, set(range(1, 6))-available))
                   if len(available) < 5 else ''))
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
        with Path(args.csv).open('w', newline='') as stream:
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
