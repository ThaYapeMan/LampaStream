"""Measurement tools: wire records, exact timestamps, and sender failure cleanup."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lms_records_decode_after_token_boundaries():
    tool = load("ab-tools")
    songs = tool.records(
        "titles 0 5 id%3A42 title%3AJust%20A%20Little artist%3AMau%20P "
        "url%3Afile%3A%2F%2F%2Fmusic%2Ftrack.flac duration%3A381 id%3A43 title%3AOther",
        "id",
    )
    assert len(songs) == 2
    assert songs[0] == {
        "id": "42",
        "title": "Just A Little",
        "artist": "Mau P",
        "url": "file:///music/track.flac",
        "duration": "381",
    }
    assert (
        tool.sender("id with spaces", "stream_file=/tmp/test file.flac")[-1]
        == "stream_file=/tmp/test file.flac"
    )


def test_logger_keeps_exact_clock_and_unknown_track_time():
    logger = load("ab-logger")
    event = dict(
        detected_audible_t=3.125,
        detected_audible_monotonic=999.0,
        audible_t=7.0,
        audible_monotonic=1001.0,
        strength=0.7,
        predicted=False,
    )
    assert logger.beat_row(event, 1234)["audible_t"] == 3.125
    assert logger.beat_row(dict(event, detected_audible_t=None), 1234)["audible_t"] is None
    assert logger.beat_row(dict(event, predicted=True), 1234)["source"] == "tempo_clock"


def test_logger_csv_real_socket(tmp_path):
    import websockets

    logger = load("ab-logger")

    async def exercise():
        async def send(ws):
            await ws.send(json.dumps(dict(type="status", track={"observed_at": 100.},
                                          light_timing={"trim_ms": 60}, beat_accent_mode="onset")))
            await ws.send(
                json.dumps(
                    dict(
                        type="event",
                        events=[
                            dict(
                                kind="beat",
                                detected_audible_t=4.6875,
                                detected_audible_monotonic=200.0,
                                strength=0.8,
                                predicted=False,
                            )
                        ],
                    )
                )
            )
            for _ in range(20):
                await ws.send(
                    json.dumps(
                        dict(
                            type="frame",
                            audible_t=4.6875,
                            tempo_bpm=128,
                            tempo_confidence=0.9,
                            tempo_locked=True,
                        )
                    )
                )
                await asyncio.sleep(0.01)

        async with websockets.serve(send, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            await logger.log("test", 0.1, tmp_path, f"ws://127.0.0.1:{port}")

    asyncio.run(exercise())
    assert "4.6875" in (tmp_path / "test-beats.csv").read_text()
    assert "128" in (tmp_path / "test-tempo.csv").read_text()
    status = json.loads((tmp_path / "test-status.jsonl").read_text().splitlines()[0])
    assert status['track']['observed_at'] == 100.
    assert status['light_timing']['trim_ms'] == 60


def test_capture_stops_owned_processes_and_player_on_sender_failure(tmp_path, monkeypatch):
    tool = load("ab-tools")
    monkeypatch.setenv("AB_LMS_PLAYER", "Room")
    track = tmp_path / "track.flac"
    track.touch()
    monkeypatch.setenv("AB_TRACK_PATH", str(track))
    creds = tmp_path / "creds"
    creds.touch()
    monkeypatch.setattr(tool, "check_receiver_idle", lambda _: None)
    monkeypatch.setattr(tool, "CREDS", creds)
    monkeypatch.setattr(tool, "capture_couplings", lambda: {"lms": "lms", "airplay": "airplay"})
    monkeypatch.setattr(tool, "api", lambda *a: {"active_coupling_id": "original"})
    monkeypatch.setattr(tool, "activate", lambda _: None)
    monkeypatch.setattr(tool, "restore_coupling", lambda _: None)
    monkeypatch.setattr(tool, "check_receiver_idle", lambda _: None)
    monkeypatch.setattr(tool, "assert_route", lambda _: None)
    monkeypatch.setattr(tool.shutil, "which", lambda _: "/bin/test")
    monkeypatch.setattr(tool.tempfile, "mkdtemp", lambda **_: str(tmp_path))
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    monkeypatch.setattr(tool, "observe", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(
        tool,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout="Address: 127.0.0.1"
            if a[0] == "atvremote"
            else json.dumps({"format": {"duration": "381"}, "streams": [{"codec_name": "flac"}]})
        ),
    )
    calls = []

    def cli(*args):
        calls.append(args)
        if args[0] == "titles":
            return "id:1 title:Track duration:381 url:file:///track.flac"
        if args[0] == "players":
            return "playerindex:0 name:Room playerid:aa:bb"
        return "mode:stop"

    monkeypatch.setattr(tool, "cli", cli)
    processes = []

    def popen(args, **kwargs):
        process = Mock()
        process.poll.return_value = 1 if "atvremote" in args else None
        process.returncode = 0
        processes.append(process)
        return process

    monkeypatch.setattr(tool.subprocess, "Popen", popen)
    def logger(label, *_):
        (tmp_path / f"{label}-manifest.json").write_text(json.dumps(
            dict(beat_accent_mode="onset", beat_accent_modes=["onset"])))
        return popen(["logger"])
    monkeypatch.setattr(tool, "logger", logger)
    with pytest.raises(RuntimeError, match="AirPlay sender failed"):
        tool.capture("Track", "receiver", 0.001)
    assert calls[-1] == ("aa:bb", "stop")
    assert all(process.send_signal.called for process in processes[:-1])


def test_capture_requires_explicit_room_before_side_effects(monkeypatch):
    tool = load("ab-tools")
    monkeypatch.delenv("AB_LMS_PLAYER", raising=False)
    monkeypatch.setattr(tool, "capture_couplings", lambda: {})
    monkeypatch.setattr(tool, "api", lambda *a: {})
    with pytest.raises(RuntimeError, match="AB_LMS_PLAYER is required"):
        tool.capture("song", "receiver", None)


@pytest.mark.parametrize("sender_exit,beats,code", [(1, 0, 2), (0, 0, 3)])
def test_smoke_distinguishes_handshake_and_no_beats(
    tmp_path, monkeypatch, sender_exit, beats, code
):
    tool = load("ab-tools")
    monkeypatch.setattr(tool, "check_receiver_idle", lambda _: None)
    monkeypatch.setattr(tool, "assert_route", lambda _: None)
    monkeypatch.setattr(tool, "CREDS", tmp_path / "creds")
    monkeypatch.setattr(tool, "observe", lambda *_, **kw: asyncio.sleep(0, result=beats))
    diagnostics = Mock()
    monkeypatch.setattr(tool, "smoke_diagnostics", diagnostics)

    def run(args, **kwargs):
        return SimpleNamespace(
            stdout="Name: Receiver\nIdentifiers: receiver\n"
            "Protocol: AirPlay, Credentials: None, Pairing: NotNeeded\n",
            returncode=0,
        )

    monkeypatch.setattr(tool.subprocess, "run", run)
    process = Mock()
    process.wait.return_value = sender_exit
    process.poll.return_value = sender_exit
    spawn = Mock(return_value=process)
    monkeypatch.setattr(tool.subprocess, "Popen", spawn)
    with pytest.raises(tool.SmokeFailure) as error:
        tool.smoke("receiver")
    assert error.value.exit_code == code
    assert "--debug" in spawn.call_args.args[0]
    diagnostics.assert_called_once()


def test_smoke_diagnostics_includes_debug_and_local_journal(tmp_path, monkeypatch, capsys):
    tool = load("ab-tools")
    log = tmp_path / "debug.log"
    log.write_text("POST /pair-setup RTSP/1.0 -> failure")
    monkeypatch.setattr(tool.shutil, "which", lambda _: "/bin/test")

    def run(args, **kwargs):
        if args[0] == "journalctl":
            print("receiver journal diagnostic", file=kwargs["stdout"])
            assert args[-3:] == ["50", "--no-pager"] or "-n" in args
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(tool.subprocess, "run", run)
    tool.smoke_diagnostics(log)
    text = capsys.readouterr().err
    assert "POST /pair-setup" in text and "receiver journal diagnostic" in text


@pytest.mark.parametrize("version", ["auto", "1", "2"])
def test_sender_protocol_version_is_persisted_as_string(version, monkeypatch):
    tool = load("ab-tools")
    remote = Mock()
    tool.select_protocol_version("receiver", version, remote)
    remote.assert_called_once_with(
        "change_setting=protocols.raop.protocol_version," + json.dumps(version)
    )
    invoke = Mock()
    monkeypatch.setattr(tool, "run", invoke)
    tool.select_protocol_version("receiver", version)
    assert invoke.call_args.args == tuple(tool.sender("receiver", remote.call_args.args[0]))


def test_sender_reports_actual_version_from_debug(tmp_path, capsys):
    tool = load("ab-tools")
    path = tmp_path / "debug"
    path.write_text("DEBUG Using AirPlay version AirPlayMajorVersion.AirPlayV1\n")
    assert tool.report_protocol_version(path) == "1"
    assert "protocol version used: 1" in capsys.readouterr().out


def test_busy_status_and_play_lock_failures_use_exit_four(tmp_path):
    tool = load('ab-tools')
    tool.reject_busy(4)
    with pytest.raises(tool.SmokeFailure, match='receiver busy with another sender') as caught:
        tool.reject_busy(4 | (1 << 11))
    assert caught.value.exit_code == 4
    log = tmp_path/'sender.log'
    log.write_text('RTSP/1.0 453 Not Enough Bandwidth')
    with pytest.raises(tool.SmokeFailure) as caught:
        tool.reject_busy_log(log)
    assert caught.value.exit_code == 4


def test_shairport_stale_flag_needs_live_connection():
    tool = load('ab-tools')
    tool.reject_busy(1 << 11, 'Shairport Sync', False)
    with pytest.raises(tool.SmokeFailure) as error:
        tool.reject_busy(1 << 11, 'Shairport Sync', True)
    assert error.value.exit_code == 4
    with pytest.raises(tool.SmokeFailure) as error:
        tool.reject_busy(1 << 11, 'Shairport Sync', None)
    assert error.value.exit_code == 2


def test_capture_analysis_uses_reference_and_marks_missing_bins(tmp_path, monkeypatch):
    import csv

    tool = load('ab-tools')
    reference = tmp_path/'own'/'test-song'/'beats.csv'
    reference.parent.mkdir(parents=True)
    reference.write_text('beat,time_s\n' + ''.join(f'{i},{.5+i*.46875}\n' for i in range(260)))
    monkeypatch.setenv('AB_REFERENCE_ROOT', str(tmp_path))
    out = tmp_path/'out'
    out.mkdir()
    for label, offset in (('lms', .2), ('airplay', .006)):
        with (out/f'{label}-beats.csv').open('w') as stream:
            writer = csv.writer(stream)
            writer.writerow(['audible_t'])
            writer.writerows([[.5+i*.46875+offset] for i in range(260)])
    tool.write_analysis(out, tmp_path/'track.flac', 'Test Song')
    result = (out/'analysis.md').read_text()
    assert '+200.0 / 0.0' in result and '+6.0 / 0.0' in result
    assert 'lms: FAIL' in result and 'airplay: PASS' in result
    assert (out/'reference-beats.csv').read_bytes() == reference.read_bytes()
    monkeypatch.setenv('AB_REFERENCE_BEATS', str(tmp_path/'missing.csv'))
    tool.write_analysis(out, tmp_path/'track.flac')
    assert 'NOT EVALUATED' in (out/'analysis.md').read_text()


def test_smoke_generated_pulse_is_minus_six_dbfs(tmp_path):
    import array
    import math
    import shutil
    import subprocess
    import wave

    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg unavailable')
    # Use the actual command assembled by smoke, without a live sender.
    tool = load('ab-tools')
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(tool.smoke))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == 'run')
    args = [ast.literal_eval(n) for n in call.args[:-1]]
    pulse = tmp_path/'pulse.wav'
    subprocess.run([*args, str(pulse)], check=True)
    with wave.open(str(pulse)) as stream:
        samples = array.array('h', stream.readframes(stream.getnframes()))
    peak = max(abs(v) for v in samples)
    dbfs = 20*math.log10(peak/32768)
    assert dbfs == pytest.approx(-6, abs=.02)
    assert peak > 3000
    print(f'Generated smoke pulse: peak={peak}/32768, {dbfs:.4f} dBFS')


def test_busy_connection_probe_distinguishes_live_and_finished_session():
    import socket

    tool = load('ab-tools')
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        port = server.getsockname()[1]
        assert tool.receiver_connection('127.0.0.1', port) is False
        with socket.create_connection(('127.0.0.1', port)) as client:
            connection, _ = server.accept()
            try:
                assert client.fileno() >= 0
                assert tool.receiver_connection('127.0.0.1', port) is True
            finally:
                connection.close()
        assert tool.receiver_connection('127.0.0.1', port) is False


@pytest.mark.parametrize('peak,detected,passed', [(3000, True, False), (3001, False, False),
                                                (3001, True, True)])
def test_smoke_socket_requires_real_level_and_detection(monkeypatch, peak, detected, passed):
    import websockets

    tool = load('ab-tools')

    async def exercise():
        async def send(ws):
            await ws.send(json.dumps(dict(type='frame', pcm_peak_s16=peak,
                                          beat_events_per_second=2)))
            if detected:
                await ws.send(json.dumps(dict(type='event', events=[
                    dict(kind='beat', predicted=False)])))
            await asyncio.sleep(.2)
        async with websockets.serve(send, '127.0.0.1', 0) as server:
            monkeypatch.setattr(tool, 'URL', f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}')
            if passed:
                assert await tool.observe(.05, require_level=True)
            else:
                with pytest.raises(tool.SmokeFailure) as error:
                    await tool.observe(.05, require_level=True)
                assert error.value.exit_code == 3
    asyncio.run(exercise())


def test_deployed_mau_p_reference_is_last_lookup_candidate(tmp_path, monkeypatch):
    tool = load('ab-tools')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('AB_REFERENCE_BEATS', raising=False)
    monkeypatch.setenv('AB_REFERENCE_ROOT', str(tmp_path/'empty'))
    for label in ('lms', 'airplay'):
        (tmp_path/f'{label}-beats.csv').write_text('audible_t\n0.476\n0.952\n')
    tool.write_analysis(tmp_path, tmp_path/'track.flac', 'Just A Little Bit More (Extended)')
    result = (tmp_path/'analysis.md').read_text()
    assert 'mau-p-jalbm' in result and 'NOT EVALUATED' not in result
    assert (tmp_path/'reference-beats.csv').is_file()
    # An explicit path remains authoritative over the bundled last candidate.
    custom = tmp_path/'custom.csv'
    custom.write_text('time_s\n0.5\n0.96875\n')
    monkeypatch.setenv('AB_REFERENCE_BEATS', str(custom))
    tool.write_analysis(tmp_path, tmp_path/'track.flac', 'Just A Little Bit More (Extended)')
    assert 'custom.csv' in (tmp_path/'analysis.md').read_text()


def test_accent_bench_reference_hits_exclude_breaks_and_count_beats_once():
    bench = load('bench-beat-accents')
    times = [1.01, 1.02, 2.051, 210.01, 212., 272.]
    events = [SimpleNamespace(candidate_sample=round(t*48000)) for t in times]
    references = [0., 1., 2., 209.99, 210., 211., 212., 240.1, 272., 400.]
    result = bench.reference_hits(events, references, 381., .05)
    assert result['reference_beats'] == 6
    assert result['hits'] == 3  # 1, 212 and 272; break event cannot credit 209.99
    assert result['hit_rate'] == .5
    assert result['tolerance_s'] == .05
    empty = bench.reference_hits([], [], 381., .05)
    assert empty['hits'] == 0 and empty['hit_rate'] is None
