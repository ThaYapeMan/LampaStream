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


@pytest.mark.parametrize('route', ['normal', 'timestamped'])
def test_websocket_clicks_19_distinct_activations(tmp_path, monkeypatch, route):
    app_module = importlib.import_module('lampastream.app')
    root = Path(__file__).resolve().parents[1]
    args = parser().parse_args(['--input', str(root/'tests/fixtures/replay/clicks-120.wav'),
        '--config', str(root/'tests/fixtures/replay/default-config.json'),
        '--route', route, '--out', str(tmp_path)])
    replay = Replay(args)
    frames = []
    clock = [0.]
    poll = [.017]  # Deliberately out of phase with the render and event clocks.

    class Manager:
        last_onset = PlayerManager.last_onset
        last_pcm_onset = PlayerManager.last_pcm_onset
        last_onset_bass = PlayerManager.last_onset_bass
        last_onset_mid = PlayerManager.last_onset_mid
        last_onset_treble = PlayerManager.last_onset_treble
        accent_diagnostics = PlayerManager.accent_diagnostics
        last_colours = []
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
                frames.append(json.loads(json.dumps(payload)))

    monkeypatch.setattr(app_module, 'asyncio', SimpleNamespace(sleep=lambda _: Pause()))
    socket = Socket()
    coroutine = app_module.ws_preview(socket)
    observe = replay.observe_mixer

    def attach(engine):
        observe(engine)
        socket.app.state.player_manager._active = SimpleNamespace(
            sync_engine=engine, hue_driver=None)
        engine._preview_clock = lambda: clock[0]
        render = engine._render_scene

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
    print(f'websocket 20 Hz {route}: 19/19 distinct onset, PCM and outline activations')


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
    engine._render_scene(view, now[0])
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
