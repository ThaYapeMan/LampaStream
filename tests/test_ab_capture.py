"""Existing activation API orchestration, including guard and cleanup paths."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def capture_tool(tmp_path, monkeypatch, ab_status):
    spec = importlib.util.spec_from_file_location("ab_capture", ROOT / "scripts/ab-tools.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    for name, value in [
        ("AB_BASE", str(tmp_path / "bench")),
        ("AB_LMS_PLAYER", "Room"),
        ("AB_LMS_COUPLING", "lms"),
        ("AB_AIRPLAY_COUPLING", "airplay"),
        ("AB_TRACK_PATH", str(tmp_path / "track")),
    ]:
        monkeypatch.setenv(name, value)
    (tmp_path / "track").touch()
    creds = tmp_path / "creds"
    creds.touch()
    monkeypatch.setattr(tool, "check_receiver_idle", lambda _: None)
    monkeypatch.setattr(tool, "CREDS", creds)
    monkeypatch.setattr(tool.shutil, "which", lambda _: "/bin/test")
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    import asyncio

    monkeypatch.setattr(tool, "observe", lambda *a, **kw: asyncio.sleep(0))
    out = tmp_path / "run"
    out.mkdir()
    monkeypatch.setattr(tool.tempfile, "mkdtemp", lambda **_: str(out))
    state = dict(active="original", mismatch=False, events=[], out=out)

    def api(path, method="GET"):
        if path == "/couplings":
            return [dict(id=name, name=name + " room") for name in ["lms", "airplay"]]
        if path == "/status":
            return dict(
                active_coupling_id=state["active"],
                active_player_type="wrong"
                if state["mismatch"]
                else {"lms": "LMS", "airplay": "AirPlay"}.get(state["active"]),
            )
        assert method == "POST"
        state["active"] = None if path.endswith("/deactivate") else path.split("/")[2]
        state["events"].append(("activate", state["active"]))
        return dict(active_id=state["active"])

    monkeypatch.setattr(tool, "api", api)

    def cli(*args):
        state["events"].append(("cli", args))
        if args[0] == "titles":
            return "id:1 title:Track duration:381 url:file:///track.flac"
        if args[0] == "players":
            return "playerindex:0 name:Room playerid:aa:bb"
        return "mode:stop"

    monkeypatch.setattr(tool, "cli", cli)

    def run(*args, **kw):
        return SimpleNamespace(
            stdout=(
                "Address: 127.0.0.1"
                if args[0] == "atvremote"
                else json.dumps(dict(format=dict(duration=381), streams=[dict(codec_name="flac")]))
                if args[0] == "ffprobe"
                else "diagnostic/version"
            )
        )

    monkeypatch.setattr(tool, "run", run)

    def process(args, **kw):
        proc = Mock(returncode=0)
        proc.poll.return_value = 0 if args[0] == "atvremote" else None
        proc.wait.return_value = 0
        return proc

    monkeypatch.setattr(tool.subprocess, "Popen", process)

    def logger(label, *_, raw_detector=False):
        (out / f"{label}-manifest.json").write_text(json.dumps(
            dict(beat_accent_mode="onset", beat_accent_modes=["onset"])))
        (out / f"{label}-status.jsonl").write_text(json.dumps(ab_status()) + "\n")
        state["events"].append(("logger", label))
        state["events"].append(("raw_detector", raw_detector))
        return process(["logger"])

    monkeypatch.setattr(tool, "logger", logger)
    return tool, state


def test_activation_order_and_restore_recorded(capture_tool):
    tool, state = capture_tool
    tool.capture("track", "receiver", 0.001, raw_detector=True)
    assert state["events"].count(("raw_detector", True)) == 2
    assert [x for x in state["events"] if x[0] in ("activate", "logger")] == [
        ("activate", "lms"),
        ("logger", "lms"),
        ("activate", "airplay"),
        ("logger", "airplay"),
        ("activate", "original"),
    ]
    manifest = json.loads((state["out"] / "manifest.json").read_text())
    assert manifest["coupling_ids"] == dict(lms="lms", airplay="airplay")
    assert manifest["restore"] == dict(requested_id="original", success=True)


@pytest.mark.parametrize("interrupted", [False, True])
def test_restore_on_failure_and_ctrl_c(capture_tool, monkeypatch, interrupted):
    tool, state = capture_tool
    error = KeyboardInterrupt if interrupted else RuntimeError

    def fail(*_, raw_detector=False):
        raise error("logger stopped")

    monkeypatch.setattr(tool, "logger", fail)
    with pytest.raises(error):
        tool.capture("track", "receiver", 0.001)
    assert state["active"] == "original"
    manifest = json.loads((state["out"] / "manifest.json").read_text())
    assert manifest["restore"]["success"]
    assert ("cli", ("aa:bb", "play")) not in state["events"]


def test_guard_refuses_mismatch_before_logger(capture_tool):
    tool, state = capture_tool
    state["mismatch"] = True
    with pytest.raises(RuntimeError, match="Route guard refused"):
        tool.capture("track", "receiver", 0.001)
    assert state["active"] == "original"
    assert not any(x[0] == "logger" for x in state["events"])


def test_missing_coupling_variables_lists_choices(capture_tool, monkeypatch, capsys):
    tool, _ = capture_tool
    monkeypatch.delenv("AB_LMS_COUPLING")
    with pytest.raises(RuntimeError, match="AB_LMS_COUPLING and AB_AIRPLAY_COUPLING"):
        tool.capture_couplings()
    assert "lms  lms room" in capsys.readouterr().out


def test_inactive_original_is_restored(capture_tool, monkeypatch):
    tool, state = capture_tool
    state["active"] = None
    monkeypatch.setattr(tool, "logger", Mock(side_effect=RuntimeError("logger stopped")))
    with pytest.raises(RuntimeError, match="logger stopped"):
        tool.capture("track", "receiver", 0.001)
    assert state["active"] is None
    assert json.loads((state["out"] / "manifest.json").read_text())["restore"]["success"]


def test_restore_failure_is_recorded(capture_tool, monkeypatch):
    tool, state = capture_tool
    monkeypatch.setattr(tool, "restore_coupling", Mock(side_effect=RuntimeError("API unavailable")))
    with pytest.raises(RuntimeError, match="cleanup/restore failed"):
        tool.capture("track", "receiver", 0.001)
    result = json.loads((state["out"] / "manifest.json").read_text())["restore"]
    assert result == dict(requested_id="original", success=False, error="API unavailable")


def test_capture_base_owns_default_track_archive_and_reference(capture_tool, monkeypatch):
    tool, state = capture_tool
    base = tool.bench_base()
    base.mkdir()
    track = base / 'track.flac'
    track.touch()
    monkeypatch.delenv('AB_TRACK_PATH')
    monkeypatch.delenv('AB_REFERENCE_ROOT', raising=False)
    reference = base / 'own' / 'track' / 'beats.csv'
    reference.parent.mkdir(parents=True)
    reference.write_text('time_s\n1\n')
    for label in ('lms', 'airplay'):
        (state['out'] / f'{label}-beats.csv').write_text('audible_t,content_t\n1,1\n')
    tool.capture('track', 'receiver', .001)
    assert list(base.glob('ab-*.tar.gz'))
    manifest = json.loads((state['out'] / 'manifest.json').read_text())
    assert manifest['local_track'] == str(track)
    assert (state['out'] / 'reference-beats.csv').read_bytes() == reference.read_bytes()


def test_analysis_failure_keeps_archive_before_traceback(capture_tool, monkeypatch, capsys):
    import sys
    import tarfile

    tool, state = capture_tool

    def fail(*args, **kwargs):
        archives = list(tool.bench_base().glob("ab-*.tar.gz"))
        assert len(archives) == 1
        assert str(archives[0]) in capsys.readouterr().out
        with tarfile.open(archives[0]) as archive:
            assert {"manifest.json", "lms-status.jsonl", "airplay-status.jsonl"} <= set(
                archive.getnames())
            manifest = json.load(archive.extractfile("manifest.json"))
            assert manifest["restore"]["success"]
        raise KeyError("analysis fixture failure")

    monkeypatch.setattr(tool, "write_analysis", fail)
    monkeypatch.setattr(sys, "argv", ["ab-tools.py", "capture", "track", "receiver", ".001"])
    with pytest.raises(SystemExit) as error:
        tool.main()
    assert error.value.code == 1
    diagnostic = capsys.readouterr().err
    assert "Traceback (most recent call last)" in diagnostic
    assert 'raise KeyError("analysis fixture failure")' in diagnostic
    assert "KeyError: 'analysis fixture failure'" in diagnostic
    assert (state["out"] / "manifest.json").is_file()
