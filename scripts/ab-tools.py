#!/usr/bin/env python3
"""Owner-operated A/B measurements; temporary coupling selection is restored on exit."""

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

import websockets

CREDS = Path("/var/lib/lampastream/ab-tools/airplay.creds")
URL = os.environ.get("AB_PREVIEW_URL", "ws://127.0.0.1:8420/ws/preview")
HOST = "192.168.178.23"
HERE = Path(__file__).resolve().parent


def run(*args, capture=False, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)


def cli(*tokens):
    command = " ".join(quote(str(token), safe="") for token in tokens)
    with socket.create_connection((HOST, 9090), timeout=5) as connection:
        connection.settimeout(5)
        connection.sendall((command + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            block = connection.recv(65536)
            if not block:
                raise RuntimeError("LMS closed CLI connection")
            data += block
            if len(data) > 4 * 1024 * 1024:
                raise RuntimeError("Oversize LMS response")
    text = data.decode().strip()
    if text.endswith(" ?") or text == "?":
        raise RuntimeError(f"LMS rejected command: {command}")
    return text


def records(response, key):
    result = []
    for token in response.split():
        name, separator, value = unquote(token).partition(":")
        if name == key:
            result.append({})
        if separator and result:
            result[-1][name] = value
    return result


def api(path, method="GET"):
    request = Request(
        "http://127.0.0.1:8420/api" + path,
        method=method,
        data=b"{}" if method == "POST" else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def assert_route(expected):
    status = api("/status")
    if status.get("active_player_type") != expected:
        raise RuntimeError(
            f"Route guard refused: expected {expected}, got {status.get('active_player_type')}"
        )


def capture_couplings():
    selected = {
        label: os.environ.get(f"AB_{label.upper()}_COUPLING") for label in ("lms", "airplay")
    }
    available = api("/couplings")
    if not all(selected.values()):
        print("Available couplings:", flush=True)
        for coupling in available:
            print(f"  {coupling['id']}  {coupling['name']}", flush=True)
        raise RuntimeError("AB_LMS_COUPLING and AB_AIRPLAY_COUPLING are required")
    if any(identity not in {c["id"] for c in available} for identity in selected.values()):
        raise RuntimeError("A selected coupling ID does not exist")
    return selected


def activate(identity):
    api(f"/couplings/{quote(identity, safe='')}/activate", "POST")


def restore_coupling(identity):
    if identity is None:
        api("/couplings/deactivate", "POST")
    else:
        activate(identity)
    if api("/status").get("active_coupling_id") != identity:
        raise RuntimeError("Original coupling was not restored")


def sender(receiver, *command):
    return ["atvremote", "--storage-filename", str(CREDS), "--id", receiver, *command]


async def observe(seconds, require_beats=None):
    seen, frames = 0, 0
    async with websockets.connect(URL, open_timeout=5) as ws:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                message = json.loads(
                    await asyncio.wait_for(ws.recv(), min(3, deadline - time.monotonic()))
                )
            except TimeoutError:
                if time.monotonic() >= deadline:
                    break
                raise RuntimeError("Preview socket stopped sending data") from None
            if message.get("type") == "frame":
                frames += 1
                seen += int(message.get("beat_events_per_second", 0) > 0)
    if not frames:
        raise RuntimeError("Preview returned no frames")
    if require_beats is True and not seen:
        raise RuntimeError("No beats detected during the AirPlay pulse")
    if require_beats is False and seen:
        raise RuntimeError("Beats still present after settling; aborting comparison")
    return seen


def stop(process):
    if process is None:
        return
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


class SmokeFailure(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.exit_code = code


def smoke_diagnostics(log_path):
    print("=== pyatv debug log ===", file=sys.stderr)
    print(log_path.read_text(errors="replace"), file=sys.stderr)
    # A remote sender host may not have Shairport; only query a local unit.
    if shutil.which("journalctl") and shutil.which("systemctl"):
        unit = subprocess.run(["systemctl", "cat", "shairport-sync"], capture_output=True)
        if unit.returncode == 0:
            print("=== shairport-sync journal (last 50 lines) ===", file=sys.stderr)
            subprocess.run(
                ["journalctl", "-u", "shairport-sync", "-n", "50", "--no-pager"],
                stdout=sys.stderr,
                stderr=sys.stderr,
                check=False,
            )


def smoke(receiver):
    assert_route("AirPlay")
    os.umask(0o077)
    CREDS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    CREDS.parent.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="ab-smoke-") as work:
        log_path = Path(work) / "pyatv-debug.log"
        log_path.touch()
        with log_path.open("w") as debug:

            def remote(*command, show=False):
                result = subprocess.run(
                    sender(receiver, "--debug", *command),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=debug,
                )
                debug.write(result.stdout)
                debug.flush()
                if show:
                    print(result.stdout, flush=True)
                if result.returncode:
                    raise SmokeFailure("AirPlay discovery/pairing failed", 2)
                return result.stdout

            try:
                scan = remote("scan", show=True)
                if receiver.lower() not in scan.lower():
                    raise SmokeFailure(f"Receiver {receiver} was not found", 2)
                for line in scan.splitlines():
                    protocol = (
                        "airplay"
                        if "Protocol: AirPlay," in line
                        else "raop"
                        if "Protocol: RAOP," in line
                        else None
                    )
                    if (
                        protocol
                        and "Credentials: None" in line
                        and ("Pairing: Mandatory" in line or "Pairing: Optional" in line)
                    ):
                        # Inherit stdin for interactive PIN entry, retain full diagnostics.
                        result = subprocess.run(
                            sender(receiver, "--debug", "--protocol", protocol, "pair"),
                            stdout=None,
                            stderr=debug,
                        )
                        if result.returncode:
                            raise SmokeFailure("AirPlay pairing failed", 2)
                if CREDS.exists():
                    CREDS.chmod(0o600)
                pulse = Path(work) / "pulse.wav"
                run(
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=60:sample_rate=44100:duration=10",
                    "-af",
                    "volume=if(lt(mod(t\\,0.5)\\,0.1)\\,1\\,0):eval=frame",
                    str(pulse),
                )

                async def test():
                    monitor = asyncio.create_task(observe(10))
                    await asyncio.sleep(0.2)
                    process = subprocess.Popen(
                        sender(receiver, "--debug", f"stream_file={pulse}"),
                        stdout=debug,
                        stderr=debug,
                    )
                    try:
                        try:
                            result = await asyncio.to_thread(process.wait, 30)
                        except subprocess.TimeoutExpired:
                            raise SmokeFailure("AirPlay handshake/stream timed out", 2) from None
                        if result:
                            raise SmokeFailure(
                                f"AirPlay handshake/stream failed (exit {result})", 2
                            )
                        if not await monitor:
                            raise SmokeFailure("Stream ran but no beats detected on the socket", 3)
                    finally:
                        stop(process)
                        monitor.cancel()
                        await asyncio.gather(monitor, return_exceptions=True)

                asyncio.run(test())
            except BaseException:
                debug.flush()
                smoke_diagnostics(log_path)
                raise
    print("Beats detected: yes — owner must verify lights react")


def logger(label, duration, out):
    ready = out / f".{label}-ready"
    process = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "ab-logger.py"),
            label,
            str(duration),
            "--out",
            str(out),
            "--ready",
            str(ready),
        ]
    )
    deadline = time.monotonic() + 10
    while not ready.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            stop(process)
            raise RuntimeError("Logger failed to subscribe")
        time.sleep(0.05)
    return process


def utc():
    return datetime.now(UTC).isoformat()


def capture(search, receiver, requested_duration):
    couplings = capture_couplings()
    original = api("/status").get("active_coupling_id")
    player_name = os.environ.get("AB_LMS_PLAYER")
    if not player_name:
        raise RuntimeError("AB_LMS_PLAYER is required (exact LMS room name)")
    track_path = Path(os.environ.get("AB_TRACK_PATH", "/tmp/ab/track.flac"))
    if not track_path.is_file():
        raise RuntimeError(f"Local FLAC missing: {track_path}")
    for command in ("atvremote", "tcpdump", "ffprobe", "systemctl", "journalctl"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing tool: {command}; run install-ab-tools.sh")
    if not CREDS.is_file():
        raise RuntimeError("AirPlay credential storage missing; run ab-airplay-smoke.sh first")
    run("systemctl", "is-active", "--quiet", "lampastream")
    asyncio.run(observe(0.3))
    receiver_scan = run(*sender(receiver, "scan"), capture=True).stdout
    address_match = re.search(r"Address:\s+(\S+)", receiver_scan)
    if not address_match:
        raise RuntimeError("AirPlay receiver was not found during preflight")
    receiver_address = address_match.group(1)
    songs = records(cli("titles", 0, 5, f"search:{search}", "tags:adut"), "id")
    song = next(
        (
            song
            for song in songs
            if song.get("url", "").lower().endswith(".flac")
            or song.get("type", "").lower() == "flac"
        ),
        None,
    )
    if song is None:
        raise RuntimeError("No FLAC hit among the first five LMS search results")
    players = records(cli("players", 0, 99), "playerindex")
    matches = [player for player in players if player.get("name") == player_name]
    if len(matches) != 1 or "playerid" not in matches[0]:
        raise RuntimeError("AB_LMS_PLAYER must match exactly one LMS player")
    player = matches[0]["playerid"]
    print("LMS track:", json.dumps(song, ensure_ascii=False), flush=True)
    print(f"LMS player: {player_name} ({player})", flush=True)
    probe = json.loads(
        run(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name",
            "-of",
            "json",
            str(track_path),
            capture=True,
        ).stdout
    )
    duration = float(song["duration"])
    local_duration = float(probe["format"]["duration"])
    if not any(stream.get("codec_name") == "flac" for stream in probe["streams"]):
        raise RuntimeError("AB_TRACK_PATH must be FLAC")
    if not math.isfinite(duration) or duration <= 0 or abs(local_duration - duration) > 1:
        raise RuntimeError("Local FLAC and LMS duration differ by more than one second")
    seconds = requested_duration if requested_duration is not None else duration + 5
    if not math.isfinite(seconds) or seconds <= 0:
        raise RuntimeError("Duration must be finite and positive")
    base = Path("/tmp/ab")
    base.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="ab-run-", dir=base))
    manifest = dict(
        track=song,
        local_track=str(track_path),
        duration=seconds,
        player=player,
        player_name=player_name,
        receiver_id=receiver,
        runs={},
        coupling_ids=couplings,
        original_coupling_id=original,
        clock_coordinates=(
            "track seconds when available; otherwise raw AudibleClock monotonic seconds"
        ),
    )
    active = []
    armed = False
    try:
        for label in ("lms", "airplay"):
            activate(couplings[label])
            assert_route("LMS" if label == "lms" else "AirPlay")
            manifest["runs"][label] = {"start": utc()}
            if label == "lms":
                (out / "lms-status-before.txt").write_text(
                    cli(player, "status", "-", 1, "tags:adut")
                )
                packet_filter = ["host", HOST]
            else:
                # Include all receiver traffic: negotiated RAOP audio/timing/control
                # ports are dynamic, so a fixed 5000/7000 filter loses audio.
                packet_filter = ["host", receiver_address, "and", "(", "tcp", "or", "udp", ")"]
            with (out / f"{label}-tcpdump.log").open("w") as diagnostics:
                packet = subprocess.Popen(
                    [
                        "tcpdump",
                        "-U",
                        "-i",
                        "any",
                        "-w",
                        str(out / f"{label}.pcap"),
                        *packet_filter,
                    ],
                    stdout=diagnostics,
                    stderr=diagnostics,
                )
                active.append(packet)
                time.sleep(0.5)
                if packet.poll() is not None:
                    raise RuntimeError("tcpdump failed (run capture with sudo); see " + str(out))
                log = logger(label, seconds + 2, out)
                active.append(log)
                if label == "lms":
                    armed = True
                    cli(player, "playlistcontrol", "cmd:load", f"track_id:{song['id']}")
                    cli(player, "time", 0)
                    cli(player, "play")
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        if log.poll() is not None:
                            raise RuntimeError("Logger exited during LMS run")
                        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
                    cli(player, "stop")
                    (out / "lms-status-after.txt").write_text(
                        cli(player, "status", "-", 1, "tags:adut")
                    )
                else:
                    stream = subprocess.Popen(sender(receiver, f"stream_file={track_path}"))
                    active.append(stream)
                    deadline = time.monotonic() + seconds
                    while stream.poll() is None and time.monotonic() < deadline:
                        if log.poll() is not None:
                            raise RuntimeError("Logger exited during AirPlay run")
                        time.sleep(0.2)
                    if stream.poll() not in (None, 0):
                        raise RuntimeError("AirPlay sender failed")
                    stop(stream)
                # Let the logger finish and flush its trailing interval.
                log.wait(timeout=seconds + 5 if label == "airplay" else 8)
                if log.returncode:
                    raise RuntimeError("Logger failed")
                stop(packet)
            manifest["runs"][label]["end"] = utc()
            if label == "lms":
                print("Settling for 15 seconds", flush=True)
                time.sleep(15)
                asyncio.run(observe(2, require_beats=False))
        (out / "shairport-sync.log").write_text(
            run(
                "journalctl", "-u", "shairport-sync", "-n", "200", "--no-pager", capture=True
            ).stdout
        )
        (out / "lampastream-version.txt").write_text(
            run("git", "-C", "/opt/lampastream-src", "rev-parse", "HEAD", capture=True).stdout
        )
    except BaseException as error:
        manifest["error"] = str(error) or type(error).__name__
        raise
    finally:
        cleanup_errors = []
        for process in reversed(active):
            try:
                stop(process)
            except Exception as error:
                cleanup_errors.append(str(error))
        if armed:
            try:
                cli(player, "stop")
            except Exception as error:
                cleanup_errors.append(f"LMS stop: {error}")
        restore = dict(requested_id=original, success=False)
        try:
            restore_coupling(original)
            restore["success"] = True
        except Exception as error:
            restore["error"] = str(error)
            cleanup_errors.append(f"Coupling restore: {error}")
        manifest["restore"] = restore
        manifest["cleanup_errors"] = cleanup_errors
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if cleanup_errors:
            print("Cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
            if sys.exc_info()[0] is None:
                raise RuntimeError("Capture cleanup/restore failed; see " + str(out))
    archive = base / ("ab-" + datetime.now().strftime("%Y%m%d-%H%M") + ".tar.gz")
    if archive.exists():
        archive = base / (archive.name.removesuffix(".tar.gz") + "-" + out.name + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(out.iterdir()):
            if not path.name.startswith("."):
                tar.add(path, arcname=path.name)
    print(archive, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    smoke_parser = sub.add_parser("smoke")
    smoke_parser.add_argument("receiver")
    cap = sub.add_parser("capture")
    cap.add_argument("search")
    cap.add_argument("receiver")
    cap.add_argument("duration", type=float, nargs="?")
    args = parser.parse_args()
    # SIGTERM must unwind the same cleanup as Ctrl-C.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.mode == "smoke":
            smoke(args.receiver)
        else:
            capture(args.search, args.receiver, args.duration)
    except (Exception, KeyboardInterrupt) as error:
        parser.exit(getattr(error, "exit_code", 1), f"ERROR: {error or 'interrupted'}\n")


if __name__ == "__main__":
    main()
