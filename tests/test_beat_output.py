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
