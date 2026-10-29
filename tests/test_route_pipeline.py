"""ROUTE-01 structural, clock and scene-sampling contracts; entirely offline."""
import ast
import inspect

from lampastream.audible_clock import AirPlayAudibleClock, LmsAudibleClock
from lampastream.scheduler import RenderRequest, Scheduler
from lampastream.sync_engine import SyncEngine
from lampastream.types import AudioFeatures, OutputCapabilities


def test_equal_clock_points():
    from types import SimpleNamespace
    probe = SimpleNamespace(current_delay_ms=lambda: 0)
    timing = SimpleNamespace(tap_source='early tap')
    a, b = LmsAudibleClock(probe), AirPlayAudibleClock(probe, timing, lookahead=0)
    features = AudioFeatures([], 0, 0, 0, 0, play_monotonic=10.)
    assert a.at(480, 0, features, 1.) == b.at(480, 0, features, 1.)


def test_scheduler_coalesces_every_event_identity_and_uses_transport_latency():
    from types import SimpleNamespace
    scheduler = Scheduler(OutputCapabilities(transport_latency_s=.02))
    events = (SimpleNamespace(id=('beat', 1)), SimpleNamespace(id=('texture', 2)))
    for index, event in enumerate(events):
        scheduler.add(RenderRequest(None, index, 10., .02, (event,)), 1.)
    assert scheduler.next_due() == 9.96
    assert scheduler.due(9.95) is None
    result = scheduler.due(9.96)
    assert result.sample == 1
    assert result.events == events
    assert scheduler.next_due() is None
    scheduler.add(RenderRequest(None, 0, 11.), 1.)
    scheduler.reset(2)
    assert scheduler.next_due() is None


def test_one_render_event_and_send_call_site():
    from lampastream.render_pipeline import RenderPipeline
    source = inspect.getsource(SyncEngine)+'\n'+inspect.getsource(RenderPipeline)
    tree = ast.parse(source)
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)]
    for name in ('_render_scene', '_event_view', '_preview_sent'):
        assert calls.count(name) == 1, name
    loop = inspect.getsource(SyncEngine.run)
    for forbidden in ('timestamped', 'tap_source', 'AirPlay', 'LMS', 'SceneSchedule',
                      '_delay_buffer', 'Hue', 'hue'):
        assert forbidden not in loop
    assert loop.count('output.send(') == 1


def test_boundary_samples_do_not_advance_precision_state():
    from copy import deepcopy

    from lampastream.output_boundary import BoundaryScene, QuantisationGuard
    from lampastream.types import Colour, Position, UniformScene
    guard = QuantisationGuard(OutputCapabilities())
    position = Position(0, 0, 0)
    scene = BoundaryScene(UniformScene(Colour(.1, .2, .3)), guard, (position,), 10., True)
    before = deepcopy((guard.baseline, guard.previous))
    expected = scene.color_at(position, 10.)
    for t in (11., 9., 100., -1., 10.):
        assert scene.color_at(position, t) == expected
    assert (guard.baseline, guard.previous) == before


def test_unsent_strong_event_survives_weaker_retrigger_inside_send_ceiling():
    import asyncio
    from dataclasses import replace

    import pytest

    from lampastream.audible_preview import render_metadata
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline
    from lampastream.trace_output import TraceChannel, TraceOutput
    from lampastream.types import OnsetEvent, Position

    profile = Profile(diagnostic_onsets=True, effect_type='solid')
    analyser = _make_canonical_pipeline(None, profile)
    analyser._publish(epoch_id='test', sample_start=0, sample_end=480,
        features=AudioFeatures([.2]*30, .2, .2, .2, .2, received_monotonic=0.),
        effective_spectrum_backend='v2', effective_processor_ids=('v2',))
    engine = SyncEngine(None, profile, analyser=analyser)
    output = TraceOutput([TraceChannel(0, Position(0, 0, 0))],
                         capabilities=OutputCapabilities(update_hz=25))
    now = [0.]
    captured = []
    send = output.send

    def observe(scene, t):
        captured.append((t, render_metadata(scene).features.onset_envelope))
        send(scene, t)
    output.send = observe
    first = OnsetEvent(('test', 'all', 240), 'test', 240, 480, 0, 1., 1., 1.,
                       frozenset({'all'}), 'all')
    remaining = [(0.005, first), (0.010, replace(first, id=('test', 'all', 480),
                                               candidate_sample=480, strength=.2))]

    async def tick(dt):
        now[0] += dt
        while remaining and remaining[0][0] <= now[0]+1e-10:
            _, event = remaining.pop(0)
            analyser._event_queue.append(event)
        if now[0] > .025:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.run(output, clock=lambda: now[0], sleep=tick))
        assert len(captured) == 2
        assert captured[1] == pytest.approx((.02, 1.))
        assert engine.event_counters['all']['received'] == 2
        assert engine.event_counters['all']['lost'] == 0
        assert len(engine._audible_preview.confirmed) == 2
    finally:
        analyser.stop()


import pytest  # noqa: E402


@pytest.mark.parametrize('fixture', ['clicks-120', 'beats/house', 'beats/techno',
                                     'beats/pad-texture'])
def test_equal_clocks_produce_byte_identical_sends(tmp_path, fixture):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'scripts/replay_chain.py'),
        '--input', str(root/f'tests/fixtures/replay/{fixture}.wav'),
        '--config', str(root/'tests/fixtures/replay/default-config.json'),
        '--route', 'equal', '--out', str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'lms/sends.csv').read_bytes() == (tmp_path/'airplay/sends.csv').read_bytes()
    print(f'{fixture}: {result.stdout.strip()}')


def test_new_clock_calibration_fences_obsolete_scheduled_work():
    from types import SimpleNamespace
    delay = [500]
    clock = LmsAudibleClock(SimpleNamespace(current_delay_ms=lambda: delay[0]))
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=1.)
    scheduler = Scheduler(OutputCapabilities())
    old = clock.at(0, 0, features, 1.)
    scheduler.reset(clock.generation)
    scheduler.add(RenderRequest(features, 0, old.audible), 1.)
    delay[0] = 0
    current = clock.at(0, 0, features, 1.1)
    scheduler.reset(clock.generation)
    assert scheduler.next_due() is None
    assert current.audible == 1.


def test_long_delay_queues_cadence_slots_without_pruning_the_next_due_frame():
    scheduler = Scheduler(OutputCapabilities(), interval=1/30)
    first = None
    maximum_depth = 0
    for i in range(4500):
        now = i/100
        scheduler.add(RenderRequest(i, i*480, now+40.), now, cadence=True)
        due = scheduler.due(now)
        if due is not None and first is None:
            first = now, due.features
        maximum_depth = max(maximum_depth, len(scheduler.queue))
    assert first == (40., 0)
    assert maximum_depth <= 1202
    assert scheduler.coalesced_continuous > 0
