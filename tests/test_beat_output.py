"""Beat shaping through actual offline render, scheduling and quantisation."""
import asyncio
import json
from pathlib import Path

import pytest
from replay_chain import Replay, decode, parser

from lampastream.accent import _linear

FIXTURES = Path(__file__).parent/'fixtures'


@pytest.mark.parametrize('room', ['two-channel.json', 'two-channel-fast.json'])
@pytest.mark.parametrize('mode,divisor,flashes', [('Phase', 1, 23), ('Alternate', 1, 12),
                                               ('Phase', 4, 6)])
def test_output_flashes_have_floor_gaps_and_divisor(tmp_path, room, mode, divisor, flashes):
    config = json.loads((FIXTURES/'replay/default-config.json').read_text())
    for effect in config['configuration']['effects']:
        effect.update(beat_mode=mode, beat_divisor=divisor)
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config))
    args = parser().parse_args(['--input', str(FIXTURES/'replay/beats/house.wav'),
        '--config', str(path), '--room', str(FIXTURES/'rooms'/room),
        '--render-hz', '60' if 'fast' in room else '30', '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    try:
        pcm, rate, _ = decode(args.input)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        assert replay.counters()['events']['all']['lost'] == 0
        assert len(replay.engine._beat_envelopes['beat']._triggers) == flashes
        gaps = [r for r in replay.renders if 1 < r['render_argument_s'] < 11
                and .40 <= r['render_argument_s'] % .5 <= .48]
        assert gaps
        for row in gaps:
            pre = max(_linear(row[f'pre_{c}']) for c in 'rgb')
            post = max(_linear(row[f'post_{c}']) for c in 'rgb')
            assert post <= .7*pre+1e-9
    finally:
        replay.pipeline.stop()


def test_timestamped_pulse_has_symmetric_attack_and_fall(tmp_path):
    config = json.loads((FIXTURES/'replay/default-config.json').read_text())
    for effect in config['configuration']['effects']:
        effect.update(beat_mode='Pulse', effect_type='solid')
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config))
    args = parser().parse_args(['--input', str(FIXTURES/'replay/beats/house.wav'),
        '--config', str(path), '--route', 'timestamped', '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    try:
        pcm, rate, _ = decode(args.input)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        first = next(data for data in replay.engine.event_records.values()
                     if data['event'].kind == 'beat')
        target = first['event_time']
        ratios = []
        for offset in (-.04, .04):
            rows = [r for r in replay.renders if abs(r['render_argument_s']-target-offset) < 1e-8]
            assert rows
            row = rows[-1]
            pre = max(_linear(row[f'pre_{c}']) for c in 'rgb')
            post = max(_linear(row[f'post_{c}']) for c in 'rgb')
            ratios.append(post/pre)
        assert ratios == pytest.approx([1.05, 1.05], abs=1e-8)
    finally:
        replay.pipeline.stop()


@pytest.mark.parametrize('name,latency', [('house', 30), ('techno', 26.9166666667),
    ('breakbeat', 23.7916666667), ('disco', 20), ('deep-house', 27.3020833333)])
def test_every_kick_has_an_attributed_lifted_send_within_latency_budget(tmp_path, name, latency):
    from measure_beats import measure

    result = measure(FIXTURES/f'replay/beats/{name}.wav', tmp_path/name)
    assert result['kick_hits'] == result['kicks'] == result['attributed_kicks']
    assert result['latency_median_ms'] == pytest.approx(latency, abs=1e-6)
    assert result['latency_median_ms'] <= 30+1e-7


@pytest.mark.parametrize('route', ['normal', 'timestamped'])
@pytest.mark.parametrize('room', ['two-channel.json', 'two-channel-fast.json'])
def test_actual_sent_colours_reach_floor_between_kicks(tmp_path, route, room):
    args = parser().parse_args(['--input', str(FIXTURES/'replay/beats/house.wav'),
        '--config', str(FIXTURES/'replay/default-config.json'), '--route', route,
        '--room', str(FIXTURES/'rooms'/room), '--render-hz',
        '60' if 'fast' in room else '30', '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    try:
        pcm, rate, _ = decode(args.input)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        renders = {(r['render_id'], r['channel_id']): r for r in replay.renders}
        ratios = []
        # Inspect the held quantised setpoint throughout the quiet window. A
        # deadline scheduler need not emit a fresh frame inside this 20 ms window.
        for beat in range(2, 22):
            for offset in (.43, .44, .45):
                audible = beat*.5+offset+(args.lead_s if route == 'timestamped' else 0.)
                deadline = audible-replay.output.capabilities.transport_latency_s
                for channel in {row['channel_id'] for row in replay.output.rows}:
                    send = max((row for row in replay.output.rows
                                if row['channel_id'] == channel
                                and row['virtual_time_s'] <= deadline+1e-10),
                               key=lambda row: row['virtual_time_s'])
                    row = renders[send['scene_id'], channel]
                    pre = max(_linear(row[f'pre_{c}']) for c in 'rgb')
                    if replay.output.capabilities.colour_depth_bits == 8:
                        sent = [send[c+'8']/255 for c in 'rgb']
                    else:
                        sent = [int(send[c]*65535)/65535 for c in 'rgb']
                    ratios.append(max(_linear(v) for v in sent)/pre)
        assert ratios
        assert max(ratios) <= .7
    finally:
        replay.pipeline.stop()
