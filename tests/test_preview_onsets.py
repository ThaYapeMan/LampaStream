"""Lossless event indicators across production renders and 20 Hz socket polls."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from replay_chain import Replay, decode, parser

from lampastream.player_manager import PlayerManager


def replay_preview(tmp_path, monkeypatch, route, delay=0, advance=.02):
    app_module = importlib.import_module('lampastream.app')
    root = Path(__file__).resolve().parents[1]
    args = parser().parse_args(["--diagnostic-onsets",
            '--input', str(root/'tests/fixtures/replay/clicks-120.wav'),
        '--config', str(root/'tests/fixtures/replay/default-config.json'),
        '--route', route, '--out', str(tmp_path)])
    args.delay_ms = delay
    replay = Replay(args)
    from dataclasses import replace
    replay.high = replace(replay.high, onset_lead_s=advance)
    replay.low = replace(replay.low, onset_lead_s=advance)
    frames = []
    pushes = []
    clock = [0.]
    poll = [.017]  # Deliberately out of phase with the render and event clocks.

    class Manager:
        last_onset = PlayerManager.last_onset
        last_pcm_onset = PlayerManager.last_pcm_onset
        last_onset_bass = PlayerManager.last_onset_bass
        last_onset_mid = PlayerManager.last_onset_mid
        last_onset_treble = PlayerManager.last_onset_treble
        accent_diagnostics = PlayerManager.accent_diagnostics
        last_colours = PlayerManager.last_colours
        preview_frame = PlayerManager.preview_frame
        last_loudness = (None, None)
        preview_spectrum = ([], None)

        def __getattr__(self, name):
            return None

    class Pause:
        def __await__(self):
            yield

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(player_manager=Manager(),
            storage=SimpleNamespace(get_player_latency=lambda _: None)))

        async def accept(self):
            pass

        async def close(self):
            pass

        async def send_json(self, payload):
            if payload['type'] == 'frame':
                frames.append(dict(json.loads(json.dumps(payload)), poll_time=clock[0]))

    monkeypatch.setattr(app_module, 'asyncio', SimpleNamespace(sleep=lambda _: Pause()))
    socket = Socket()
    coroutine = app_module.ws_preview(socket)
    observe = replay.observe_mixer

    def attach(engine):
        observe(engine)
        engine.preview_publish = lambda payload: pushes.append((replay.now, payload))
        socket.app.state.player_manager._active = SimpleNamespace(
            sync_engine=engine, hue_driver=replay.output)
        engine._preview_clock = lambda: clock[0]
        render = engine._render_scene
        send = replay.output.send
        captures = []

        def flush(until):
            while poll[0] < until:
                clock[0] = poll[0]
                coroutine.send(None)  # Advance the actual websocket producer one poll.
                poll[0] += .05

        def rendered(features, t):
            engine._preview_clock = lambda: clock[0]
            flush(replay.now)
            clock[0] = replay.now
            return render(features, t)

        def sent(scene, t):
            engine._preview_clock = lambda: clock[0]
            flush(replay.now)
            clock[0] = replay.now
            send(scene, t)
            from lampastream.audible_preview import render_metadata
            metadata = render_metadata(scene)
            deadline = t+metadata.playback_shift if route == 'timestamped' else t
            lifts = []
            for position, colour in zip(
                    metadata.positions, replay.output.last_colours, strict=True):
                before = metadata.baseline.color_at(position, t)
                lifts.append(max(0., colour.r-before.r, colour.g-before.g, colour.b-before.b))
            captures.append((deadline, len(captures), tuple(
                dict(zip(('r', 'g', 'b'), c.to_16bit(), strict=True))
                for c in replay.output.last_colours), metadata.features.onset_envelope, lifts))

        replay.captures = captures
        replay.output.send = sent
        engine._render_scene = rendered
        replay.flush_preview = flush

    replay.observe_mixer = attach
    try:
        pcm, rate, _ = decode(args.input, 0, None)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        replay.flush_preview(replay.now)
    finally:
        coroutine.close()
        replay.pipeline.stop()
    for name in ('onset', 'pcm_onset', 'onset_envelope'):
        active = [f.get(name, 0) > .5 if name == 'onset_envelope' else f[name] for f in frames]
        activations = sum(value and (i == 0 or not active[i-1])
                          for i, value in enumerate(active))
        assert activations == 19, (route, name, activations)
    assert all('onset_count_since_render' in f and 'accent_value' in f
               and 'channel_accent_lifts' in f for f in frames if f['onset'])
    starts = [f['poll_time'] for i, f in enumerate(frames) if f.get('onset_envelope', 0) > .5
              and (i == 0 or frames[i-1].get('onset_envelope', 0) <= .5)]
    events = sorted(replay.engine.event_records.values(), key=lambda r: r['event'].candidate_sample)
    targets = ([r['event'].play_monotonic for r in events] if route == 'timestamped' else
               [c[0] for i, c in enumerate(replay.captures) if c[3] > .5
                and (i == 0 or replay.captures[i-1][3] <= .5)])
    offsets = [(actual-target)*1000 for actual, target in zip(starts, targets, strict=True)]
    assert min(offsets) >= -1e-6 and max(offsets) <= 50+1e-6, offsets
    for frame in frames:
        if frame.get('onset_envelope', 0) <= .5:
            continue
        shown = max((capture for capture in replay.captures if capture[0] <= frame['poll_time']),
                    key=lambda c: (c[0], c[1]))
        assert frame['channel_colours'] == list(shown[2])
        assert frame['channel_accent_lifts'] == shown[4]
        if route == 'normal':
            assert frame['audible_monotonic'] == shown[0]
        else:
            assert frame['audible_monotonic'] == frame['poll_time']
    pushes = [(stamp, message) for stamp, message in pushes if message['type'] == 'event']
    identities = [tuple(event['id']) for _, message in pushes for event in message['events']]
    assert len(identities) == len(set(identities)) == 19
    assert set(identities) == set(replay.engine.event_records)
    residuals = []
    for sent_at, message in pushes:
        for event in message['events']:
            identity = tuple(event['id'])
            target = event['audible_monotonic']
            if route == 'timestamped':
                assert target == replay.engine.event_records[identity]['event'].play_monotonic
                assert target - sent_at >= .05
            else:
                assert abs(target - sent_at) <= .001
                capture = next(c for c in replay.captures if abs(c[0] - sent_at) < 1e-8)
                assert message['channel_colours'] == list(capture[2])
            residuals.append((sent_at - target) * 1000)
    assert all(abs((b['poll_time'] - a['poll_time']) - .05) < 1e-8
               for a, b in zip(frames, frames[1:], strict=False))
    print(f'event push {route}, delay={delay}, advance={advance}: 19/19 exactly once; '
          f'push minus audible {min(residuals):.3f}..{max(residuals):.3f} ms; '
          'periodic cadence unchanged')
    print(f'websocket 20 Hz {route}, delay={delay} ms, lamp advance={advance:.2f} s: '
          f'19/19; audible offsets {min(offsets):.3f}..{max(offsets):.3f} ms; '
          'post-accent colours consistent')
    return starts


@pytest.mark.parametrize('route,delay,advance', [
    ('normal', 0, .02), ('normal', 200, .02),
    ('timestamped', 0, .02), ('timestamped', 0, .10)])
def test_websocket_clicks_19_distinct_activations(tmp_path, monkeypatch, route, delay, advance):
    replay_preview(tmp_path, monkeypatch, route, delay, advance)


def test_lamp_advance_does_not_move_audible_preview(tmp_path, monkeypatch):
    early = replay_preview(tmp_path, monkeypatch, 'timestamped', advance=.02)
    earlier = replay_preview(tmp_path, monkeypatch, 'timestamped', advance=.10)
    assert early == earlier
    print('timestamped lamp advance 0.02 vs 0.10 s: identical 19 preview activation times')


def test_no_snapshot_flags_feed_preview_or_status():
    import re

    source = Path(__file__).resolve().parents[1]/'src/lampastream'
    matches = []
    for name in ('sync_engine.py', 'player_manager.py', 'app.py', 'api.py'):
        for number, line in enumerate((source/name).read_text().splitlines(), 1):
            if re.search(r'(?:self\._last_(?:pcm_)?onset\w*\s*=|["\'](?:pcm_)?onset\w*["\']\s*:)'
                         r'.*(?:latest\(\)\.onset|features\.onset\b|f\.onset\b|'
                         r'features\.onset_(?:bass|mid|treble)\b)', line):
                matches.append((name, number, line))
    assert not matches
    print('preview/status snapshot-onset grep: 0 matches')


def test_band_holds_and_raw_flags_cannot_refresh_preview():
    from dataclasses import replace

    from lampastream.accent import AccentLayer
    from lampastream.models import Profile
    from lampastream.sync_engine import SyncEngine
    from lampastream.types import AudioFeatures, OnsetEvent

    now = [1.]
    engine = SyncEngine(None, Profile(), analyser=SimpleNamespace())
    engine._preview_clock = lambda: now[0]
    engine._accent = AccentLayer()
    engine._accent_positions = ()
    event = OnsetEvent(('test', 'bass', 0), 'test', 0, 480, 1, 1, 1, 1,
                       frozenset({'bass'}), 'bass')
    view = AudioFeatures([], 0, 0, 0, 0, onset=False, onset_count_since_render=1,
                         onset_events=(event,))
    from lampastream.audible_preview import AudiblePreview
    engine._audible_preview = AudiblePreview(.08, .25, 'restart')
    engine._preview_timestamped = False
    engine._newest_onset = (None, 0.)
    engine._audible_preview.register(event, now[0], False)
    scene = engine._render_scene(view, now[0])
    assert not engine.last_onset
    engine._preview_sent(scene, now[0], SimpleNamespace(last_colours=[]))
    assert engine.last_onset and engine.last_pcm_onset and engine.last_onset_bass
    assert not engine.last_onset_mid and not engine.last_onset_treble
    now[0] += .049
    assert engine.last_onset_bass
    now[0] += .002
    assert not engine.last_onset_bass and not engine.last_pcm_onset
    engine._render_scene(replace(view, onset_count_since_render=0, onset_events=(),
                                onset=True, onset_bass=True, onset_mid=True,
                                onset_treble=True), now[0])
    assert not engine.last_onset and not engine.last_onset_bass
    assert not engine.last_onset_mid and not engine.last_onset_treble


def test_preview_fences_future_events_when_route_or_generation_resets():
    from lampastream.audible_preview import AudiblePreview
    from lampastream.types import OnsetEvent

    event = OnsetEvent(('test', 'all', 0), 'test', 0, 480, 1, 1, 1, 1,
                       frozenset({'all'}), 'all', play_monotonic=10.)
    preview = AudiblePreview(.08, .25, 'restart')
    preview.register(event, 9.9, True)
    assert preview.snapshot(9.99)['onset_envelope'] == 0
    preview.route(False)
    assert not preview.snapshot(10.)['onset']
    preview.register(event, 9.9, True)
    preview.reset()
    assert preview.snapshot(10.)['onset_envelope'] == 0


def test_timestamped_preview_envelope_and_accent_advance_without_another_send():
    import math

    from lampastream.audible_preview import AudiblePreview, PreviewScene
    from lampastream.models import Profile
    from lampastream.types import AudioFeatures, Colour, OnsetEvent, Position, UniformScene

    preview = AudiblePreview(.08, .25, 'restart')
    event = OnsetEvent(('test', 'all', 0), 'test', 0, 480, 1, 1, 1, 1,
                       frozenset({'all'}), 'all', play_monotonic=10.)
    preview.register(event, 9.98, True)
    scene = UniformScene(Colour(.1, .1, .1))
    features = AudioFeatures([], 0, 0, 0, 0, onset_envelope=1.)
    metadata = PreviewScene(scene, features, 9.98, .35, [.2], .02, scene,
                            (Position(0, 0, 0),), Profile(diagnostic_onsets=True))
    preview.sent(metadata, 9.98, [Colour(.3, .3, .3)], True)
    assert preview.snapshot(9.999)['onset_envelope'] == 0
    assert not preview.snapshot(9.999)['colours']
    peak = preview.snapshot(10.)
    assert peak['onset'] and peak['accent_value'] == pytest.approx(.35)
    assert peak['colours'] == (Colour(.3, .3, .3),)
    tail = preview.snapshot(10.33)
    assert not tail['onset']
    assert tail['onset_envelope'] == pytest.approx(math.exp(-1))
    assert tail['accent_value'] == pytest.approx(.35*math.exp(-1))


def test_event_push_coalesces_burst_and_retains_individual_clocks():
    from lampastream.audible_preview import AudiblePreview, PreviewScene
    from lampastream.models import Profile
    from lampastream.types import AudioFeatures, Colour, OnsetEvent, UniformScene

    messages = []
    preview = AudiblePreview(.08, .25, 'restart', messages.append)
    for i, stamp in enumerate((10., 10.004, 10.02)):
        event = OnsetEvent(('burst', 'all', i), 'burst', i, 480, 1, 1, 1, 1,
                           frozenset({'all'}), 'all', play_monotonic=stamp)
        preview.register(event, 9.9, True)
    scene = UniformScene(Colour(.3, .3, .3))
    metadata = PreviewScene(scene, AudioFeatures([], 0, 0, 0, 0), 10.02,
                            .35, [.2], 0., scene, (), Profile())
    preview.push(metadata, 9., [], True)
    preview.push(metadata, 9., [], True)
    messages = [message for message in messages if message['type'] == 'event']
    assert [message['event_count'] for message in messages] == [2, 1]
    stamps = [event['audible_monotonic'] for message in messages for event in message['events']]
    assert stamps == [10., 10.004, 10.02]
    assert messages[0]['hold_s'] == .08 and messages[0]['release_s'] == .25


def test_socket_push_and_ping_run_while_periodic_producer_sleeps(monkeypatch):
    import time

    from fastapi import WebSocketDisconnect

    app_module = importlib.import_module('lampastream.app')

    class Manager:
        last_loudness = (None, None)
        last_colours = []
        preview_frame = {}
        accent_diagnostics = {}
        preview_spectrum = ([], None)
        listener = None

        def subscribe_preview(self, listener):
            self.listener = listener
            return lambda: setattr(self, 'listener', None)

        def __getattr__(self, name):
            return None

    async def run():
        manager = Manager()
        frames = asyncio.Queue()
        incoming = asyncio.Queue()
        sleeping = asyncio.Event()
        release = asyncio.Event()

        async def sleep(_):
            sleeping.set()
            await release.wait()

        monkeypatch.setattr(app_module, 'asyncio', SimpleNamespace(
            get_running_loop=asyncio.get_running_loop, Queue=asyncio.Queue,
            create_task=asyncio.create_task, wait=asyncio.wait,
            FIRST_COMPLETED=asyncio.FIRST_COMPLETED, gather=asyncio.gather, sleep=sleep))

        class Socket:
            app = SimpleNamespace(state=SimpleNamespace(player_manager=manager,
                storage=SimpleNamespace(get_player_latency=lambda _: None)))

            async def accept(self):
                pass

            async def send_json(self, payload):
                await frames.put(payload)

            async def receive_json(self):
                item = await incoming.get()
                if item is None:
                    raise WebSocketDisconnect()
                return item

        task = asyncio.create_task(app_module.ws_preview(Socket()))
        await asyncio.wait_for(sleeping.wait(), 1)
        while not frames.empty():
            frames.get_nowait()
        payload = dict(type='event', audible_monotonic=time.monotonic()+1, events=[])
        await asyncio.to_thread(manager.listener, payload)
        assert await asyncio.wait_for(frames.get(), 1) == payload
        before = time.monotonic()
        await incoming.put(dict(type='ping', client_ms=123.))
        pong = await asyncio.wait_for(frames.get(), 1)
        assert pong['type'] == 'pong' and pong['client_ms'] == 123.
        assert before <= pong['server_monotonic'] <= time.monotonic()
        assert not release.is_set()
        await incoming.put(None)
        await asyncio.wait_for(task, 1)
        assert manager.listener is None
        # TestClient/server shutdown may cancel the endpoint before disconnect delivery.
        cancelled = asyncio.create_task(app_module.ws_preview(Socket()))
        await asyncio.sleep(0)
        cancelled.cancel()
        await cancelled
        assert manager.listener is None
        print('socket event push + clock pong bypass blocked 50 ms producer; subscriber cleaned up')

    asyncio.run(run())


def test_socket_coalesces_available_bursts_without_waiting_or_crossing_reset():
    from lampastream.audible_preview import coalesce_messages

    def message(stamp, colour):
        return dict(type='event', audible_monotonic=stamp, hold_s=.08, release_s=.25,
                    policy='restart', bands=['bass'], event_count=1,
                    events=[dict(audible_monotonic=stamp, channel_colours=[colour])])

    first, second, third = message(10., 'red'), message(10.004, 'blue'), message(10.02, 'green')
    result = coalesce_messages([first, second, third])
    assert [item['event_count'] for item in result] == [2, 1]
    assert [event['channel_colours'] for event in result[0]['events']] == [['red'], ['blue']]
    assert len(coalesce_messages([first, dict(type='preview_reset'), second])) == 3


@pytest.mark.parametrize('case', json.loads((Path(__file__).parent /
    'fixtures/preview01-accent-on.json').read_text())['cases'],
    ids=lambda case: f"{case['route']}-{case['delay_ms']}")
def test_accent_on_lamp_bytes_match_8f5385b(tmp_path, case):
    import hashlib

    fixtures = Path(__file__).parent/'fixtures/replay'
    args = parser().parse_args(["--diagnostic-onsets",
            '--input', str(fixtures/'clicks-120.wav'),
        '--config', str(fixtures/'default-config.json'), '--route', case['route'],
        '--delay-ms', str(case['delay_ms']), '--out', str(tmp_path)])
    replay = Replay(args)
    try:
        pcm, rate, fmt = decode(args.input, 0, None)
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        replay.save(fmt)
        actual = hashlib.sha256((tmp_path/'sends.csv').read_bytes()).hexdigest()
        assert actual == case['sends_sha256']
        print(f"active-accent sends.csv vs 8f5385b {case['route']} "
              f"delay={case['delay_ms']}: byte-identical ({actual})")
    finally:
        replay.pipeline.stop()
