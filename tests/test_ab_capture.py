"""Existing activation API orchestration, including guard and cleanup paths."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def capture_tool(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ab_capture", ROOT / "scripts/ab-tools.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    for name, value in [
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

    def logger(label, *_):
        state["events"].append(("logger", label))
        return process(["logger"])

    monkeypatch.setattr(tool, "logger", logger)
    return tool, state


def test_activation_order_and_restore_recorded(capture_tool):
    tool, state = capture_tool
    tool.capture("track", "receiver", 0.001)
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

    def fail(*_):
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
