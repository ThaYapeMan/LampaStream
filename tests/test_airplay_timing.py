"""AirPlay timing uses only the production reader's diagnostic tap."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pipeline_factory import make_pipeline

from lampastream.airplay_config import SHAIRPORT_REVISION, delivery_margin, rename_receiver
from lampastream.airplay_timing import (
    AirPlayAutoLatencyProbe,
    CadenceCheck,
    ProcessingWindow,
    TimingDiagnostics,
)
from lampastream.app import app
from lampastream.canonicalizer import (
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    DecodedSourceFrame,
)
from lampastream.models import PlayerLatency
from lampastream.pcm_source import AirPlayPipeStereoSource
from lampastream.player_manager import ActiveSession, PlayerManager
from lampastream.storage import Storage
from lampastream.track_position import AirPlayTrackPositionSource


@pytest.fixture
def anyio_backend():
    return "asyncio"


ROOT = Path(__file__).resolve().parents[1]


def steady(diagnostics, clock, *, p=125, seconds=4):
    for i in range(seconds * 100 + 1):
        clock[0] = 10 + i / 100
        diagnostics.arrival(441, clock[0])
        diagnostics.processing(clock[0] - p / 1000, clock[0], clock[0])


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fault", ["steady", "burst", "stall", "rate", "jitter"])
def test_pacing_and_probe_summary(fault, capsys):
    cadence = CadenceCheck()
    events = []
    for i in range(401):
        stamp = 10 + i / 100
        frames = 441
        if fault == "rate":
            frames = 300
        if fault == "jitter":
            stamp += 0.035 if i % 2 else 0
        cadence.observe(frames, stamp)
        events.append(dict(kind="arrival", frames=frames, monotonic=stamp))
    if fault == "burst":
        cadence.observe(44100, 14.01)
        events.append(dict(kind="arrival", frames=44100, monotonic=14.01))
    now = 14.2 if fault == "stall" else events[-1]["monotonic"]
    assert (cadence.status(now)["state"] == "steady") == (fault == "steady")
    passed = load_script("airplay-timing-probe.py").report(events, now=now)
    assert passed == (fault == "steady")
    assert (
        "PASS: steady real-time pacing within 20 ms" if passed else "FAIL:"
    ) in capsys.readouterr().out


def test_estimator_median_precision_outlier_and_bound():
    window = ProcessingWindow()
    for i, value in enumerate([100, 101, 102, 103, 104, 105, 106, 107]):
        assert window.accept(value, i)
    assert len(window.samples) == 7
    assert window.median() == 104
    assert window.precision() == 3
    for value in [float("nan"), float("inf"), -1, 900]:
        assert not window.accept(value, 20)
    assert window.median() == 104
    assert not window.accept(900, 21)
    assert window.accept(900, 22)
    assert window.median() == 900


def test_processing_excludes_output_hold_and_lifecycle():
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    diagnostics.arrival(441, 10)
    clock[0] = 10.425
    diagnostics.processing(10, 10.125, 10.425)
    snapshot = diagnostics.snapshot()
    assert snapshot["median_processing_ms"] == pytest.approx(125)
    assert snapshot["events"][-1]["delay_hold_ms"] == pytest.approx(300)
    clock[0] += 0.01
    diagnostics.metadata("paus", "")
    assert not diagnostics.snapshot()["active"]
    assert diagnostics.snapshot()["sample_count"] == 0
    assert diagnostics.snapshot()["events"][-1]["since_arrival_ms"] is not None
    diagnostics.metadata("mdst", "")
    diagnostics.metadata("mden", "")
    diagnostics.metadata("pres", "")
    assert diagnostics.snapshot()["active"]
    diagnostics.ended()
    assert not diagnostics.snapshot()["active"]


def test_auto_arithmetic_trim_step_limit_and_persistence():
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    config = PlayerLatency(player_mac="aa", strategy="auto", fixed_delay_ms=200, trim_ms=-20)
    persist = Mock()
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 500, persist, clock=lambda: clock[0])
    assert probe.current_delay_ms() == 200
    steady(diagnostics, clock)
    assert probe.current_delay_ms() == 355
    assert probe.status()["source"] == "airplay"
    persist.assert_called_once()
    probe.config = replace(config, trim_ms=1000)
    clock[0] += 0.01
    diagnostics.arrival(441, clock[0])
    diagnostics.processing(clock[0] - 0.125, clock[0], clock[0])
    assert probe.current_delay_ms() == 405
    assert probe.current_delay_ms() == 405  # no fresh sample, no further step
    assert probe.status()["samples"][0]["processing_ms"] == pytest.approx(125)
    probe.config = replace(config, trim_ms=-1000)
    clock[0] += 0.01
    diagnostics.arrival(441, clock[0])
    diagnostics.processing(clock[0] - 0.125, clock[0], clock[0])
    assert probe.current_delay_ms() == 355


@pytest.mark.anyio
async def test_persist_stop_restart_and_fallback():
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    config = PlayerLatency(
        player_mac="aa", strategy="auto", fixed_delay_ms=123, measured_delay_ms=375, trim_ms=10
    )
    persist = Mock()
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 500, persist, clock=lambda: clock[0])
    assert probe.current_delay_ms() == 385
    steady(diagnostics, clock)
    assert probe.current_delay_ms() == 385
    await probe.stop()
    assert persist.call_args.args[0] == 375
    clock[0] += 0.2
    assert probe.current_delay_ms() == 123
    assert probe.status()["reason"] == "Audio delivery stalled"
    steady(diagnostics, clock)
    probe.margin = None
    assert probe.current_delay_ms() == 123
    assert "not verified" in probe.status()["reason"]


def test_timestamp_survives_resampling_and_analysis():
    canonicalizer = AudioCanonicalizer()
    pipeline = make_pipeline(
        source=Mock(),
        backend="v2",
        onset_method="combined",
        onset_delta=0.05,
        onset_alpha=0.8,
        superflux_mu=1.5,
        superflux_lag=2,
        bass_hz=250,
        mid_hz=3000,
    )
    frames = []
    try:
        for i in range(30):
            decoded = DecodedSourceFrame(
                np.zeros((441, 2), np.float32),
                44100,
                2,
                "airplay:test",
                None,
                False,
                None,
                10 + i / 100,
            )
            for result in canonicalizer.push(DataResult(decoded)):
                if isinstance(result, CanonicalData):
                    frames.append(result.frame)
                    pipeline.feed(result.frame)
        assert frames
        assert frames[0].received_monotonic == 10
        record = pipeline.drain_publications()[-1]
        assert record is not None
        assert record.features.received_monotonic is not None
        assert 10 <= record.features.received_monotonic <= 10.29
    finally:
        pipeline.stop()


@pytest.mark.parametrize("pattern", ["steady", "burst", "stall"])
def test_fake_pipe_tap(pattern, tmp_path):
    """One real FIFO reader, deterministic writer clock; probe consumes its tap."""
    fifo = tmp_path / "audio"
    os.mkfifo(fifo)
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    source = AirPlayPipeStereoSource(fifo, timing=diagnostics)
    source.open()
    writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    try:
        for i in range(401):
            clock[0] = 10 + i / 100
            os.write(writer, bytes(441 * 4))
            # Reader timestamp is captured at the real production boundary.
            from unittest.mock import patch

            with patch("lampastream.pcm_source.time.monotonic", return_value=clock[0]):
                frame = source.read().frame
            assert frame.received_monotonic == clock[0]
        if pattern == "burst":
            for _ in range(12):
                os.write(writer, bytes(441 * 4))
                with patch("lampastream.pcm_source.time.monotonic", return_value=clock[0]):
                    source.read()
        if pattern == "stall":
            clock[0] += 0.2
        snapshot = diagnostics.snapshot()
        result = load_script("airplay-timing-probe.py").report(
            snapshot["events"], now=clock[0], emit=lambda _: None
        )
        assert result == (pattern == "steady")
    finally:
        os.close(writer)
        source.close()


def test_diagnostics_read_only_api_and_bounded_events(tmp_path):
    diagnostics = TimingDiagnostics(clock=lambda: 10)
    for _ in range(4500):
        diagnostics.arrival(441, 10)
    app.state.storage = Storage(tmp_path / "config.json")
    app.state.player_manager = Mock(airplay_timing=diagnostics)
    client = TestClient(app)
    response = client.get("/api/airplay-timing?after=1")
    assert response.status_code == 200
    assert response.json()["dropped"]
    assert len(response.json()["events"]) == 4096
    assert client.post("/api/airplay-timing", json={"samples": []}).status_code == 405
    assert client.get("/api/airplay-timing?after=-1").status_code == 422


@pytest.mark.parametrize("offset", ["", "audio_backend_latency_offset_in_seconds = 0.2;",
    "audio_backend_latency_offset_in_seconds = -0.5; "
    "audio_backend_buffer_desired_length_in_seconds = 0.0; "
    "audio_backend_buffer_interpolation_threshold_in_seconds = 0.0;"])
def test_installer_timing_edit_preserves_and_verifies(tmp_path, offset):
    config = tmp_path / "receiver.conf"
    original = (
        f'general = {{ name = "Custom"; {offset} custom = "keep"; }}\npipe = {{ name = "fifo"; }}\n'
    )
    config.write_text(original)
    config.chmod(0o640)
    updater = (
        (ROOT / "scripts/setup-airplay.sh")
        .read_text()
        .split("<< 'PY_VOLUME'\n")[1]
        .split("\nPY_VOLUME")[0]
    )
    subprocess.run([sys.executable, "-", str(config)], input=updater, text=True, check=True)
    updated = config.read_text()
    assert 'custom = "keep";' in updated
    assert 'pipe = { name = "fifo"; }' in updated
    manifest = dict(airplay_delivery_margin_ms=0, airplay_timing_policy="receiver-defaults",
                    shairport_revision=SHAIRPORT_REVISION)
    assert delivery_margin(updated, manifest) == (None if "0.2" in offset else 0)
    if "0.2" in offset:
        assert offset in updated
    else:
        assert "audio_backend_latency_offset_in_seconds" not in updated
        assert "audio_backend_buffer" not in updated
    verifier = load_script('verify-install.py')
    verifier.verify_airplay(manifest, updated)
    with pytest.raises(AssertionError, match='timing contract'):
        verifier.verify_airplay({}, updated)
    assert delivery_margin(updated, {}) is None

    stamp = config.stat().st_mtime_ns
    subprocess.run([sys.executable, "-", str(config)], input=updater, text=True, check=True)
    assert config.stat().st_mtime_ns == stamp
    assert config.stat().st_mode & 0o777 == 0o640
    assert 'custom = "keep";' in rename_receiver(updated, 'New "name"')


@pytest.mark.parametrize(
    "setting",
    [
        'audio_backend_latency_offset_in_seconds = "oops";',
        (
            "audio_backend_latency_offset_in_seconds = 0.2; "
            "audio_backend_latency_offset_in_seconds = 0.3;"
        ),
        "audio_backend_latency_offset = 42;",
    ],
)
def test_installer_refuses_ambiguous_timing_without_write(tmp_path, setting):
    config = tmp_path / "receiver.conf"
    original = 'general = { name = "Custom"; ' + setting + " }"
    config.write_text(original)
    updater = (
        (ROOT / "scripts/setup-airplay.sh")
        .read_text()
        .split("<< 'PY_VOLUME'\n")[1]
        .split("\nPY_VOLUME")[0]
    )
    result = subprocess.run(
        [sys.executable, "-", str(config)], input=updater, text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "Cannot safely update AirPlay timing" in result.stderr
    assert config.read_text() == original


def test_manifest_records_margin_and_pin(tmp_path):
    binary = tmp_path / "player"
    binary.write_bytes(b"player")
    load_script("write-install-manifest.py").write_manifest(
        "commit", "short", tmp_path, "13e606f452d9a2ae729f9590ec4ea696ab4dbcde", binary
    )
    import json

    manifest = json.loads((tmp_path / "installation.json").read_text())
    assert manifest["airplay_delivery_margin_ms"] == 0
    assert manifest["airplay_timing_policy"] == "receiver-defaults"
    assert manifest["shairport_revision"] == SHAIRPORT_REVISION
    assert (
        "timing_settings(receiver_config)"
        in (ROOT / "scripts/verify-install.py").read_text()
    )


@pytest.mark.anyio
async def test_manager_airplay_auto_refresh_preserves_measurements(tmp_path, monkeypatch):
    from lampastream.models import Profile, VirtualPlayerType

    storage = Storage(tmp_path / "config.json")
    manager = PlayerManager(storage)
    config = PlayerLatency(player_mac="aa", strategy="auto")
    storage.save_player_latency(config)
    session = ActiveSession(Profile(player_mac="aa"), player_type=VirtualPlayerType.AIRPLAY)
    manager._active = session
    monkeypatch.setattr("lampastream.player_manager.installed_delivery_margin", lambda _: 500)
    await manager.refresh_probe()
    probe = session.probe
    assert isinstance(probe, AirPlayAutoLatencyProbe)
    assert manager.timing_player_mac == "aa"
    storage.save_player_latency(replace(config, trim_ms=-20))
    await manager.refresh_probe()
    assert session.probe is probe
    assert probe.config.trim_ms == -20
    assert manager.latency_status(config)["source"] == "airplay"


def test_metadata_uses_existing_reader():
    diagnostics = TimingDiagnostics()
    source = AirPlayTrackPositionSource(timing=diagnostics)
    source._item("ssnc", "phbt", "42/100000")
    event = diagnostics.snapshot()["events"][-1]
    assert event["code"] == "phbt"
    assert isinstance(event["local_raw_ns"], int)


def test_measurement_overhead_bounded():
    diagnostics = TimingDiagnostics()
    config = PlayerLatency(player_mac='aa', strategy='auto')
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 500, Mock())
    start = time.perf_counter()
    for _ in range(1000):
        now = time.monotonic()
        diagnostics.arrival(441, now)
        diagnostics.processing(now, now, now)
        probe.current_delay_ms()
    # Generous real-time budget: diagnostic work below 1 ms per 10 ms chunk.
    assert (time.perf_counter() - start) / 1000 < 0.001


@pytest.mark.anyio
async def test_scene_timestamp_reaches_hue_dispatch(monkeypatch):
    import asyncio

    from lampastream.models import Profile
    from lampastream.sync_engine import SyncEngine
    from lampastream.types import AudioFeatures

    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    diagnostics.arrival(441, clock[0])
    clock[0] = 10.125
    features = AudioFeatures(
        bars=[0.1] * 30,
        bass=0.1,
        mid=0.1,
        centroid=0.1,
        full=0.1,
        onset=False,
        onset_strength=0,
        received_monotonic=10,
    )
    analyser = Mock()
    analyser.latest.return_value = features
    engine = SyncEngine(None, Profile(), analyser=analyser, timing=diagnostics)
    output = Mock()
    # Make the first tick sufficient: no intentional delay; stop at the sleep.
    monkeypatch.setattr("lampastream.sync_engine.time.monotonic", lambda: clock[0])

    async def finish(_):
        raise asyncio.CancelledError

    monkeypatch.setattr("lampastream.sync_engine.asyncio.sleep", finish)
    with pytest.raises(asyncio.CancelledError):
        await engine.run(output)
    output.send.assert_called_once()
    assert diagnostics.snapshot()["median_processing_ms"] == pytest.approx(125)


def test_probe_client_reads_only_diagnostic_http(monkeypatch, capsys):
    import io
    import json

    probe = load_script("airplay-timing-probe.py")
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    previous = [0]
    urls = []

    def response(url, timeout):
        urls.append(url)
        assert timeout == 3
        while previous[0] / 100 + 10 <= clock[0]:
            diagnostics.arrival(441, previous[0] / 100 + 10)
            previous[0] += 1
        after = int(url.split("after=")[-1])
        return io.BytesIO(json.dumps(diagnostics.snapshot(after)).encode())

    monkeypatch.setattr(probe, "urlopen", response)
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(sys, "argv", ["probe", "--duration", "5"])
    assert probe.main() == 0
    assert len(urls) == 6
    assert all("/api/airplay-timing?after=" in url for url in urls)
    assert "PASS: steady real-time pacing within 20 ms" in capsys.readouterr().out


@pytest.mark.parametrize(('trim', 'expected'), [(-1000, 0), (0, 375), (1000, 1375)])
def test_airplay_delay_clamps_at_zero(trim, expected):
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    config = PlayerLatency(player_mac='aa', strategy='auto', trim_ms=trim)
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 500, Mock(), clock=lambda: clock[0])
    steady(diagnostics, clock)
    assert probe.current_delay_ms() == expected


def test_processing_longer_than_margin_is_visible_fallback():
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    config = PlayerLatency(player_mac='aa', strategy='auto', fixed_delay_ms=200)
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 500, Mock(), clock=lambda: clock[0])
    steady(diagnostics, clock, p=650)
    assert probe.current_delay_ms() == 200
    assert probe.status()['reason'] == 'Processing takes longer than early delivery'


def test_receiver_rename_preserves_settings_with_file_only_permission(tmp_path):
    from unittest.mock import patch

    directory = tmp_path / 'receiver'
    directory.mkdir()
    config = directory / 'shairport-sync.conf'
    original = '''general = {
  name = "Old";
  custom = "keep";
  audio_backend_latency_offset_in_seconds = -0.5;
  audio_backend_buffer_desired_length_in_seconds = 0.0;
  audio_backend_buffer_interpolation_threshold_in_seconds = 0.0;
}
pipe = { name = "fifo"; }
'''
    config.write_text(original)
    directory.chmod(0o555)
    try:
        manager = PlayerManager(Storage(tmp_path / 'config.json'))
        manager._SHAIRPORT_CONF = config
        with patch('lampastream.player_manager.subprocess.run'):
            assert manager._configure_shairport_name('New')
        assert config.read_text() == original.replace('"Old"', '"New"')
    finally:
        directory.chmod(0o755)


@pytest.mark.parametrize('trim, delay, lag', [(-1000, 0, 125), (0, 0, 125), (10, 10, 135)])
def test_receiver_defaults_report_lag_without_old_measured_delay(trim, delay, lag):
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    config = PlayerLatency(player_mac='aa', strategy='auto', measured_delay_ms=375, trim_ms=trim)
    probe = AirPlayAutoLatencyProbe(config, diagnostics, 0, Mock(), clock=lambda: clock[0])
    assert probe.current_delay_ms() == max(0, trim)
    steady(diagnostics, clock)
    assert probe.current_delay_ms() == delay
    assert probe.status()['state'] == 'lagging'
    assert probe.status()['lag_ms'] == lag
    assert probe.status()['strategy'] == 'auto'


@pytest.mark.anyio
@pytest.mark.parametrize('offset', [-0.5, -0.1])
async def test_stalled_playback_removes_offset_and_restarts_exactly_once(
        tmp_path, monkeypatch, offset):
    from lampastream.models import Profile, VirtualPlayer, VirtualPlayerType

    clock = [10.0]
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    manager.airplay_timing = TimingDiagnostics(clock=lambda: clock[0])
    manager._SHAIRPORT_CONF = tmp_path / 'receiver.conf'
    manager._SHAIRPORT_CONF.write_text(
        f'general = {{ name = "Receiver"; audio_backend_latency_offset_in_seconds = {offset}; '
        'audio_backend_buffer_desired_length_in_seconds = 0.0; custom = "keep"; }')
    manager.storage.save_virtual_player(VirtualPlayer(id='ap', type=VirtualPlayerType.AIRPLAY,
                                                     player_mac='aa'))
    config = PlayerLatency(player_mac='aa', strategy='auto')
    manager.storage.save_player_latency(config)
    session = ActiveSession(Profile(player_mac='aa'), player_type=VirtualPlayerType.AIRPLAY)
    session.latency_mac = 'aa'
    session.probe = AirPlayAutoLatencyProbe(config, manager.airplay_timing, None, Mock())
    manager._active = session
    restart = Mock()
    monkeypatch.setattr('lampastream.player_manager.subprocess.run', restart)
    manager.airplay_timing.metadata('pbeg', '')
    manager.airplay_timing.ended()  # EOF must not hide the sender's playback evidence.
    clock[0] = 13
    await manager._protect_airplay_delivery(session)
    restart.assert_not_called()
    clock[0] = 13.01
    await manager._protect_airplay_delivery(session)
    restart.assert_called_once_with(['systemctl', 'restart', 'shairport-sync'],
                                   check=True, timeout=10, capture_output=True)
    assert 'latency_offset' not in manager._SHAIRPORT_CONF.read_text()
    assert 'buffer_desired' not in manager._SHAIRPORT_CONF.read_text()
    assert 'custom = "keep"' in manager._SHAIRPORT_CONF.read_text()
    assert session.probe.margin == 0
    assert manager.latency_status(config)['safety_message'] == (
        'Early delivery was too much for this sender and has been switched off')
    for _ in range(5):
        manager.airplay_timing.metadata('pbeg', '')
        clock[0] += 4
        await manager._protect_airplay_delivery(session)
    restart.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize('evidence', ['idle', 'paused', 'flowing', 'defaults', 'ambiguous'])
async def test_safeguard_does_not_restart_without_stalled_early_playback(
        tmp_path, monkeypatch, evidence):
    from lampastream.models import Profile

    clock = [10.0]
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    manager.airplay_timing = TimingDiagnostics(clock=lambda: clock[0])
    manager._SHAIRPORT_CONF = tmp_path / 'receiver.conf'
    setting = 'audio_backend_latency_offset_in_seconds = -0.5;'
    if evidence == 'defaults':
        setting = ''
    elif evidence == 'ambiguous':
        setting += setting
    original = f'general = {{ name = "Receiver"; {setting} }}'
    manager._SHAIRPORT_CONF.write_text(original)
    restart = Mock()
    monkeypatch.setattr('lampastream.player_manager.subprocess.run', restart)
    if evidence != 'idle':
        manager.airplay_timing.metadata('pbeg', '')
    if evidence == 'paused':
        manager.airplay_timing.metadata('paus', '')
    clock[0] = 14
    if evidence == 'flowing':
        manager.airplay_timing.arrival(441, 13.9)
    await manager._protect_airplay_delivery(ActiveSession(Profile()))
    restart.assert_not_called()
    assert manager._SHAIRPORT_CONF.read_text() == original


def test_receiver_restart_discards_previous_fifo_audio(tmp_path):
    fifo = tmp_path / 'audio'
    os.mkfifo(fifo)
    source = AirPlayPipeStereoSource(fifo)
    source.open()
    writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(writer, bytes(441 * 4))
        source.discard_pending()
        assert not isinstance(source.read(), DataResult)
        os.write(writer, np.ones(882, np.int16).tobytes())
        assert isinstance(source.read(), DataResult)
    finally:
        os.close(writer)
        source.close()


@pytest.mark.anyio
async def test_failed_safety_restart_reports_failure_and_never_loops(tmp_path, monkeypatch):
    from lampastream.models import Profile

    clock = [10.0]
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    manager.airplay_timing = TimingDiagnostics(clock=lambda: clock[0])
    manager._SHAIRPORT_CONF = tmp_path / 'receiver.conf'
    manager._SHAIRPORT_CONF.write_text(
        'general = { name = "Receiver"; audio_backend_latency_offset_in_seconds = -0.5; }')
    restart = Mock(side_effect=subprocess.CalledProcessError(1, 'systemctl'))
    monkeypatch.setattr('lampastream.player_manager.subprocess.run', restart)
    manager.airplay_timing.metadata('pbeg', '')
    clock[0] = 14
    for _ in range(4):
        await manager._protect_airplay_delivery(ActiveSession(Profile()))
    restart.assert_called_once()
    assert manager.latency_warning == 'Early delivery recovery failed; check the receiver logs'


@pytest.mark.parametrize('buffer', ['0.3', '1.5'])
def test_installer_preserves_different_operator_buffer_values(tmp_path, buffer):
    config = tmp_path / 'receiver.conf'
    original = (f'general = {{ name = "Custom"; audio_backend_latency_offset_in_seconds = -0.2; '
                f'audio_backend_buffer_desired_length_in_seconds = {buffer}; '
                f'audio_backend_buffer_interpolation_threshold_in_seconds = {buffer}; }}')
    config.write_text(original)
    updater = ((ROOT / 'scripts/setup-airplay.sh').read_text()
               .split("<< 'PY_VOLUME'\n")[1].split('\nPY_VOLUME')[0])
    subprocess.run([sys.executable, '-', str(config)], input=updater, text=True, check=True)
    updated = config.read_text()
    assert 'audio_backend_latency_offset_in_seconds = -0.2;' in updated
    assert f'audio_backend_buffer_desired_length_in_seconds = {buffer};' in updated
    assert f'audio_backend_buffer_interpolation_threshold_in_seconds = {buffer};' in updated
    manifest = dict(airplay_delivery_margin_ms=0, airplay_timing_policy='receiver-defaults',
                    shairport_revision=SHAIRPORT_REVISION)
    load_script('verify-install.py').verify_airplay(manifest, updated)
    assert delivery_margin(updated, manifest) is None


def test_safety_playback_evidence_ignores_paused_progress_and_old_heartbeats():
    clock = [10.0]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    diagnostics.metadata('phbt', '42/100000')
    clock[0] = 14
    assert diagnostics.snapshot()['stalled_for_s'] == 4
    diagnostics.metadata('paus', '')
    diagnostics.metadata('prgr', '0/10/20')
    diagnostics.metadata('phbt', '52/200000')
    clock[0] = 20
    assert diagnostics.snapshot()['stalled_for_s'] == 0
    diagnostics.metadata('pres', '')
    clock[0] = 22
    assert diagnostics.snapshot()['stalled_for_s'] == 2
    diagnostics.metadata('pbeg', '')
    assert diagnostics.snapshot()['stalled_for_s'] == 0


def test_same_name_activation_restarts_and_refuses_restart_failure(tmp_path, monkeypatch):
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    manager._SHAIRPORT_CONF = tmp_path / 'receiver.conf'
    original = 'general = { name = "Receiver"; custom = "keep"; }'
    manager._SHAIRPORT_CONF.write_text(original)
    restart = Mock(side_effect=subprocess.CalledProcessError(1, 'systemctl'))
    monkeypatch.setattr('lampastream.player_manager.subprocess.run', restart)
    assert not manager._configure_shairport_name('Receiver')
    restart.assert_not_called()
    with pytest.raises(RuntimeError, match='restart failed'):
        manager._configure_shairport_name('Receiver', force_restart=True)
    restart.assert_called_once()
    assert manager._SHAIRPORT_CONF.read_text() == original
