"""LAT-05: proven core origins and visible per-play measurement state."""

import asyncio
import importlib.util
import io
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from lampastream.canonicalizer import DataResult
from lampastream.latency import AutoLatencyProbe, FollowPositionContext
from lampastream.models import PlayerLatency
from lampastream.pcm_source import YeneyCoreShmStereoSource

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'third_party/yeney-core'
PRIVATE = Path('/home/codex/src/private-fixtures/lights-01')
SEEKS = (0, .2, .464, .549, .744, .806, 1.013, 1.5, 60, 300)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def probe_for(origin, requested, *, known=True, transition=1, now=None, warning=None,
              probe_class=AutoLatencyProbe):
    now = now if now is not None else [100.]
    context = FollowPositionContext(True, True, True, 1, transition, now[0])
    follower = SimpleNamespace(_lampastream_mac='own', target_mac='room',
                               position_alignment=(1, requested), latency_context=lambda: context)
    extras = dict(origin_known=lambda: known, warning=warning) if (
        probe_class is AutoLatencyProbe) else {}
    probe = probe_class(PlayerLatency('room', strategy='auto'), follower, lambda *a: None,
                             clock=lambda: now[0],
                             position_clock=lambda: (origin + now[0]-100, now[0], origin),
                             **extras)
    probe.cache['room'] = 0
    probe._value = lambda mac, command: (
        (requested + now[0]-100-.012 if mac == 'own' else origin+now[0]-100-.112), now[0])
    return probe, now


async def anchor(probe, now):
    for _ in range(8):
        now[0] += 1
        await probe.tick()
    return probe.session_anchor_at is not None


def test_waiting_warning_exception_once_per_play_and_clear(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    warnings = []
    probe, now = probe_for(0, .806, known=False, warning=warnings.append)
    async def run():
        sleeps = 0
        async def advance(_):
            nonlocal sleeps
            sleeps += 1
            now[0] += 1
            if sleeps == 22:
                probe.stopping = True
        monkeypatch.setattr(asyncio, 'sleep', advance)
        await probe._run()
    asyncio.run(run())
    assert probe.reason == 'Stream origin unknown for this file'
    waiting = [r.message for r in caplog.records if 'latency probe waiting:' in r.message]
    assert len(waiting) == 2
    assert all('seek_s=0.806' in line for line in waiting)
    caught = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(caught) == 1 and probe.reason in caught[0].message
    assert warnings[-1] == probe.reason
    assert probe.status()['session_anchor_set'] is False
    probe.stopping = False
    probe.origin_known = lambda: True
    probe.follower.position_alignment = (1, 0)
    asyncio.run(anchor(probe, now))
    assert warnings[-1] is None
    assert probe.status()['session_anchor_set'] is True
    assert probe.status()['current_play'] == probe.status()['applied_delay_play'] == 1


def test_basis_always_has_sample_outcome_including_held_and_rejected(caplog):
    caplog.set_level(logging.INFO)
    probe, now = probe_for(.743, .806)
    assert asyncio.run(anchor(probe, now))
    for residual, room in ((.3, 12), (.31, 12), (.2, float('nan')), (6, 12)):
        now[0] += 1
        probe._pair()
        probe.accept(residual, now[0], room)
    records = [r.message for r in caplog.records if r.message.startswith('latency ')]
    for i, line in enumerate(records):
        if line.startswith('latency basis:'):
            assert records[i+1].startswith('latency sample:')
    assert any('held as a step candidate' in line for line in records)
    assert any('rejected' in line for line in records)


@pytest.fixture(scope='module')
def producers(tmp_path_factory):
    if not PRIVATE.is_dir():
        pytest.skip('Private LAT-05 fixtures unavailable')
    base = tmp_path_factory.mktemp('lat05-core')
    builds = {}
    for label, revision in (('before', '9fba26f'), ('after', '9d5aa42')):
        build = base / label
        build.mkdir()
        data = subprocess.check_output(['git', '-C', str(CORE), 'archive', revision])
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(build, filter='data')
        # ALAC is itself a pinned submodule, identical in both revisions.
        shutil.copytree(CORE/'third_party/alac', build/'third_party/alac', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git', '*.o', '*.a'))
        result = subprocess.run(['make', '-C', str(build), '-j2', 'yeney-player'],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout+result.stderr
        builds[label] = load('lat05_'+label, build/'tests/fake_lms.py')
    old = base/'baseline_latency.py'
    old.write_bytes(subprocess.check_output(
        ['git', 'show', 'f640132:src/lampastream/latency.py']))
    builds['before'].probe_class = load('lampastream.lat05_baseline', old).AutoLatencyProbe
    builds['after'].probe_class = AutoLatencyProbe
    return builds


@pytest.fixture(scope='module')
def wire(tmp_path_factory, producers):
    if not PRIVATE.is_dir():
        pytest.skip('Private LAT-05 fixtures unavailable')
    sys.path.insert(0, str(CORE/'tests'))
    module = load('lat05_mp4_wire', CORE/'tests/mp4_seek_test.py')
    if not (module.LMS/'slimserver.pl').is_file():
        pytest.skip('Real LMS cache unavailable')
    server = module.Loopback(tmp_path_factory.mktemp('lat05-lms'))
    try:
        server.start()
        yield module, server
    finally:
        server.close()
        sys.path.remove(str(CORE/'tests'))


def capture(wire, path, requested):
    module, server = wire
    module.cli(module.MAC+' playlist play '+quote('file://'+str(path), safe=''))
    codec, first = server.fetch(16*1024*1024)
    if requested:
        status = b'STMs'+bytes(3)+struct.pack('>IIIIHIIIIIHIIH', 1048576, 0, 0, len(first),
                                           65535, 1, 8192, 4096, 0, 0, 0, 0, 0, 0)
        server.send('STAT', status)
        module.cli(module.MAC+' time '+str(requested))
        codec, first = server.fetch(16*1024*1024)
    module.cli(module.MAC+' stop')
    return codec, first


def producer_origin(oracle, body, codec):
    mac = '02:7e:'+':'.join(f'{v:02x}' for v in os.getpid().to_bytes(4, 'big'))
    source = YeneyCoreShmStereoSource()
    source.use_player_clock = True
    shm = Path('/dev/shm/yeney-'+mac)
    try:
        with oracle.Session(app=True, sink='shm', mac=mac) as session:
            source.open(mac, require_v1=True)
            session.lms.send('audg', struct.pack('!IIBBII', 0, 0, 1, 0, 0, 0))
            session.lms.strm('s', session.source(body), fmt=codec.decode())
            until = time.monotonic()+5
            while time.monotonic() < until:
                frame = source.read()
                if isinstance(frame, DataResult) and source.content_origin_known is not None:
                    if source.content_origin_known:
                        assert source.position_clock is not None
                        return source.position_clock[2], True
                    return None, False
                time.sleep(.002)
            raise AssertionError('No native producer content timing')
    finally:
        source.close()
        shm.unlink(missing_ok=True)


@pytest.mark.serial
@pytest.mark.parametrize('name', [
    'armand-van-helden-u-dont-know-me-original-mix.m4a',
    'darius-syrossian-scarface-original-mix.m4a',
    'lou-rawls-two-years-of-torture.m4a',
])
def test_real_lms_m4a_origins_before_after(name, wire, producers):
    path = PRIVATE/name
    info = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'quiet', '-show_streams', '-of', 'json', str(path)]))['streams'][0]
    rate, duration = int(info['sample_rate']), float(info['duration'])
    # Read original private media in place; decoded oracle stays in memory.
    reference = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                       '-f', 's32le', '-acodec', 'pcm_s32le', '-'])
    module, _ = wire
    # The core decoder oracle corroborates SHM against FFmpeg's original PCM.
    build = producers['after'].ROOT
    result = subprocess.run(['make', '-C', str(build), '-j2', 'mp4-position-test'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout+result.stderr
    for requested in SEEKS:
        if requested >= duration:
            continue
        codec, body = capture(wire, path, requested)
        assert codec == b'l'
        raw = subprocess.check_output([str(build/'mp4-position-test')], input=body)
        known, start, count, failed = struct.unpack('<QQQQ', raw[:32])
        assert (known, count, failed) == (1, 4096, 0)
        assert reference[start*8:(start+count)*8] == raw[32:]
        expected = start/rate
        for label, oracle in producers.items():
            origin, known = producer_origin(oracle, body, codec)
            assert known
            assert origin == pytest.approx(0 if label == 'before' else expected, abs=1/rate)
            probe, now = probe_for(origin, requested, probe_class=oracle.probe_class)
            try:
                anchored = asyncio.run(anchor(probe, now))
            except ValueError as error:
                assert str(error) == 'Seek landing >500 ms: ambiguous absolute content origin'
                anchored = False
            assert anchored == (label == 'after' or requested <= .5)
            print(f'{name} {label} requested={requested:.3f} true_frame={start} '
                  f'origin={origin:.9f} known={known} anchor={anchored} '
                  f'landing_ms={(requested-expected)*1000:.6f}', flush=True)


@pytest.mark.serial
@pytest.mark.parametrize('requested', SEEKS)
def test_real_mau_p_flac_unchanged(requested, wire, producers):
    path = PRIVATE/'mau-p-just-a-little-bit-more-extended.flac'
    codec, body = capture(wire, path, requested)
    assert codec == b'f'
    build = producers['after'].ROOT
    result = subprocess.run(['make', '-C', str(build), '-j2', 'mp4-position-test'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout+result.stderr
    raw = subprocess.check_output([str(build/'mp4-position-test'), 'flac'], input=body)
    known, start, count, failed = struct.unpack('<QQQQ', raw[:32])
    assert (known, count, failed) == (1, 4096, 0)
    # FFmpeg decodes only the reference block at the source coordinate.
    reference = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
        '-af', f'atrim=start_sample={start}:end_sample={start+count}',
        '-f', 's32le', '-acodec', 'pcm_s32le', '-'])
    assert raw[32:] == reference
    for label, oracle in producers.items():
        origin, known = producer_origin(oracle, body, codec)
        assert known and origin == pytest.approx(start/44100, abs=1/44100)
        probe, now = probe_for(origin, requested, probe_class=oracle.probe_class)
        assert asyncio.run(anchor(probe, now))
        print(f'FLAC {label} requested={requested:.3f} true_frame={start} '
              f'origin={origin:.9f} anchor=True landing_ms={(requested-origin)*1000:.6f}',
              flush=True)


async def run_unanchored(probe, now, monkeypatch, seconds=22):
    ticks = 0
    async def advance(_):
        nonlocal ticks
        ticks += 1
        now[0] += 1
        if ticks == seconds:
            probe.stopping = True
    monkeypatch.setattr(asyncio, 'sleep', advance)
    await probe._run()


@pytest.mark.serial
@pytest.mark.parametrize('requested', SEEKS)
def test_fisher_aiff_core_pcmworker_zero_known_gap_retains_guard(
        requested, wire, producers, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    codec, body = capture(wire, PRIVATE/'fisher-losing-it-extended.aiff', requested)
    # The core recognises the finite AIFF container behind LMS's PCM codec.
    for label, oracle in producers.items():
        origin, known = producer_origin(oracle, body, codec)
        assert known and origin == 0
        warnings = []
        probe, now = probe_for(origin, requested, warning=warnings.append,
                               probe_class=oracle.probe_class)
        if requested <= .5:
            assert asyncio.run(anchor(probe, now))
        else:
            if label == 'before':
                with pytest.raises(ValueError, match='Seek landing >500 ms'):
                    asyncio.run(anchor(probe, now))
            else:
                asyncio.run(run_unanchored(probe, now, monkeypatch))
                assert probe.session_anchor_at is None
                reason = 'Seek landing >500 ms: ambiguous absolute content origin'
                assert probe.reason == reason and warnings[-1] == reason
                assert any('latency probe waiting:' in r.message and reason in r.message
                           for r in caplog.records)
        print(f'AIFF PcmWorker setSourceStart(0) gap {label} seek={requested:.3f} '
              f'origin={origin} anchor={probe.session_anchor_at is not None}', flush=True)


@pytest.mark.serial
@pytest.mark.parametrize('kind', ['unprovable-m4a', 'mp3'])
def test_unknown_real_producer_never_measures(kind, wire, producers, tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    if kind == 'unprovable-m4a':
        codec, data = capture(wire, PRIVATE/'darius-syrossian-scarface-original-mix.m4a', .806)
        body = bytearray(data)
        mdhd = body.index(b'mdhd')+4
        version = body[mdhd]
        struct.pack_into('>Q' if version else '>I', body, mdhd+(24 if version else 16),
                         0xffffffffffffffff if version else 0xffffffff)
        body = bytes(body)
    else:
        path = tmp_path/'mau-p.mp3'
        assert path.is_relative_to(Path('/tmp'))
        subprocess.run(['ffmpeg', '-v', 'error', '-i',
                        str(PRIVATE/'mau-p-just-a-little-bit-more-extended.flac'),
                        '-t', '8', '-c:a', 'libmp3lame', str(path)], check=True)
        body, codec = path.read_bytes(), b'm'
    origin, known = producer_origin(producers['after'], body, codec)
    assert origin is None and known is False
    warnings = []
    probe, now = probe_for(0, .806, known=known, warning=warnings.append)
    asyncio.run(run_unanchored(probe, now, monkeypatch))
    assert probe.session_anchor_at is None and not probe.samples
    reason = 'Stream origin unknown for this file'
    assert probe.reason == reason and warnings[-1] == reason
    assert any(r.levelno == logging.WARNING and reason in r.message for r in caplog.records)
    assert any('latency probe waiting:' in r.message and reason in r.message
               for r in caplog.records)
    print(f'{kind}: known=False anchor=False warning={warnings[-1]}', flush=True)


def test_saved_v1_calibration_is_measured_afresh():
    for basis, expected in [('lms-content-v1', 7), ('lms-content-v2', 130)]:
        config = PlayerLatency('room', strategy='auto', measured_delay_ms=123,
                               trim_ms=7, measurement_basis=basis)
        probe = AutoLatencyProbe(config, None, lambda *a: None, position_clock=lambda: None)
        assert probe.current_delay_ms() == expected


def test_api_reports_current_anchor_and_delay_owner(tmp_path):
    from unittest.mock import PropertyMock

    from fastapi.testclient import TestClient
    from test_api import _make_mock_manager

    from lampastream.app import app
    from lampastream.models import Profile
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    storage = Storage(tmp_path/'config.json')
    config = PlayerLatency('room', strategy='auto')
    storage.save_player_latency(config)
    manager = PlayerManager(storage)
    session = ActiveSession(Profile())
    probe, now = probe_for(.743, .806)
    session.probe, session.latency_mac = probe, 'room'
    manager._active = session
    adapter = _make_mock_manager()
    adapter.latency_status.side_effect = manager.latency_status
    type(adapter).latency_play_status = PropertyMock(
        side_effect=lambda: manager.latency_play_status)
    app.state.storage, app.state.player_manager = storage, adapter
    with TestClient(app) as client:
        for anchored in (False, True, False):
            if anchored:
                assert asyncio.run(anchor(probe, now))
            elif probe.session_anchor_at is not None:
                from dataclasses import replace
                probe.follower.latency_context = lambda: replace(
                    probe.context, transition=2, changed_at=now[0])
                probe.eligible(probe.follower.latency_context(), now[0])
            status = client.get('/api/status').json()
            row = client.get('/api/player-latencies').json()[0]['status']
            for result in (status, row):
                assert result['session_anchor_set'] is anchored
                assert result['current_play'] == probe.current_play
                assert result['applied_delay_play'] == probe.applied_delay_play
            print('API play state:', json.dumps(manager.latency_play_status), flush=True)


@pytest.mark.serial
@pytest.mark.parametrize('sequence', [
    'stop-new-track-2s', 'stop-new-track-30s', 'playlist-advance', 'skip-playing',
    'pause-resume', 'seek-within-track', 'first-play-after-start',
])
def test_m4a_transport_notifications_reanchor_with_real_producer(
        sequence, wire, producers, monkeypatch):
    from unittest.mock import Mock

    from lampastream import lms_follower
    from lampastream.lms_follower import LmsFollower

    requested = 60 if sequence == 'seek-within-track' else .806
    codec, body = capture(wire, PRIVATE/'darius-syrossian-scarface-original-mix.m4a', requested)
    origin, known = producer_origin(producers['after'], body, codec)
    assert known
    now = [100.]
    monkeypatch.setattr(lms_follower, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    follower = LmsFollower('127.0.0.1', 'room', 'own')
    follower._connected = True
    follower._get_current_url = Mock(return_value='fixture.m4a')
    def mirror():
        follower._mirrored_url = 'fixture.m4a'
        return 'fixture.m4a'
    follower._mirror_track = mirror
    follower._send_stop = lambda: setattr(follower, '_own_mode', 'stop')
    follower._send_pause = lambda value: setattr(
        follower, '_own_mode', 'pause' if value else 'play')
    def align(track, once=True):
        follower.position_alignment = (track, requested)
    follower.realign_own_player = align
    probe, _ = probe_for(origin, requested, now=now)
    probe.follower = follower

    async def newsong():
        await follower._handle_line('room playlist newsong fixture')
        await follower._handle_line('own playlist newsong fixture')
    async def run():
        await newsong()
        assert await anchor(probe, now)
        previous = probe.current_play
        if sequence.startswith('stop-new-track'):
            await follower._handle_line('room stop')
            await probe.tick()
            assert probe.session_anchor_at is None
            assert probe.applied_delay_play == previous
            now[0] += 30 if '30s' in sequence else 2
            await newsong()
        elif sequence in ('playlist-advance', 'skip-playing'):
            await newsong()
        elif sequence == 'pause-resume':
            await follower._handle_line('room pause 1')
            await probe.tick()
            assert probe.session_anchor_at is None
            assert probe.applied_delay_play == previous
            await follower._handle_line('room pause 0')
        elif sequence == 'seek-within-track':
            await follower._handle_line('room time 60')
        else:
            return
        await probe.tick()
        assert probe.session_anchor_at is None
        assert probe.current_play != previous
        assert probe.applied_delay_play == previous
        assert await anchor(probe, now)
        assert probe.current_play == probe.applied_delay_play
    asyncio.run(run())
    print(f'transport={sequence} origin={origin:.9f} anchor=True '
          f'current_play={probe.current_play} applied_delay_play={probe.applied_delay_play}',
          flush=True)


@pytest.mark.parametrize('clock_value', [None, (1., 90., 0.)])
def test_missing_or_stale_clock_keeps_distinct_reason(clock_value):
    probe, now = probe_for(0, 0)
    now[0] = 101.
    probe.position_clock = lambda: clock_value
    with pytest.raises(ValueError, match='No fresh absolute PCM content clock'):
        probe._pair()


def test_manager_warning_is_set_after_fifteen_seconds_and_cleared_on_anchor(tmp_path):
    from lampastream.models import Profile
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    manager = PlayerManager(Storage(tmp_path/'config.json'))
    manager.storage.save_player_latency(PlayerLatency('room', strategy='auto'))
    session = ActiveSession(Profile(player_mac='own'))
    template, now = probe_for(0, 0)
    session.follower = template.follower
    session.position_clock = template.position_clock
    session.origin_known = lambda: False
    manager._active = session
    async def run():
        await manager._apply_probe_for_master(session, 'room')
        probe = session.probe
        await probe.stop()
        probe.stopping = False
        probe.clock = lambda: now[0]
        probe.startup_at = probe.applied_at = now[0]
        probe.cache['room'] = 0
        probe._value = template._value
        probe.eligible(probe.follower.latency_context(), now[0])
        now[0] = 114.9
        probe.reason = 'Stream origin unknown for this file'
        probe.report_waiting()
        assert manager.latency_warning is None
        now[0] = 115.
        probe.report_waiting()
        assert manager.latency_warning == probe.reason
        probe.origin_known = lambda: True
        assert await anchor(probe, now)
        assert manager.latency_warning is None
        assert manager.storage.get_player_latency('room').measurement_basis == 'lms-content-v2'
    asyncio.run(run())
