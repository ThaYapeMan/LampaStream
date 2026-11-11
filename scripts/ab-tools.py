#!/usr/bin/env python3
"""Owner-operated A/B measurements; temporary coupling selection is restored on exit."""

import argparse
import array
import asyncio
import bisect
import csv
import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

import websockets

CREDS = Path(os.environ.get("AB_AIRPLAY_CREDS", "/var/lib/lampastream/ab-tools/airplay.creds"))
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
    hosts = ["--scan-hosts", os.environ["AB_SCAN_HOSTS"]] if os.environ.get("AB_SCAN_HOSTS") else []
    return ["atvremote", "--storage-filename", str(CREDS), *hosts, "--id", receiver, *command]


def select_protocol_version(receiver, version, remote=None):
    if version not in ("auto", "1", "2"):
        raise ValueError("Protocol version must be auto, 1 or 2")
    # pyatv's CLI otherwise converts "1" to int, while this enum requires str.
    command = "change_setting=protocols.raop.protocol_version," + json.dumps(version)
    if remote is None:
        run(*sender(receiver, command), capture=True)
    else:
        remote(command)
    print(f"AirPlay protocol version selected for {receiver}: {version}", flush=True)


def report_protocol_version(log_path):
    found = re.findall(
        r"Using AirPlay version (?:AirPlayMajorVersion\.AirPlayV)?([12])",
        log_path.read_text(errors="replace"),
    )
    actual = found[-1] if found else None
    print(f"AirPlay protocol version used: {actual or 'not reported; see debug log'}", flush=True)
    return actual


async def observe(seconds, require_beats=None, require_level=False):
    seen, frames, peak, detected = 0, 0, 0, 0
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
            if message.get("type") == "event":
                detected += sum(event.get("kind") == "beat" and (
                    not event.get("predicted", False) or event.get("beat_source") == "grid")
                                for event in message.get("events", []))
            if message.get("type") == "frame":
                peak = max(peak, message.get("pcm_peak_s16") or 0)
                frames += 1
                seen += int(message.get("beat_events_per_second", 0) > 0)
    if not frames:
        raise RuntimeError("Preview returned no frames")
    if require_beats is True and not seen:
        raise RuntimeError("No beats detected during the AirPlay pulse")
    if require_beats is False and seen:
        raise RuntimeError("Beats still present after settling; aborting comparison")
    if require_level:
        print(f"Receiver ingress peak={peak} / 32768; detected beats={detected}", flush=True)
        if peak <= 3000 or not detected:
            raise SmokeFailure("Pulse needs peak >3000 and beats on the socket", 3)
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


BUSY_MESSAGE = "receiver busy with another sender (stop AirPlay on the other device first)"


def reject_busy(flags, model="", live_connection=None):
    # Shairport 4.3.7 can release principal_conn without clearing bit 11
    # (release_play_lock / classic cleanup). ANNOUNCE's play lock is authoritative;
    # it rejects a live owner with RTSP 453 without interrupting that sender.
    if not int(flags) & (1 << 11):
        return
    if "shairport" in model.lower():
        if live_connection is None:
            raise SmokeFailure(
                "Shairport busy flag cannot be verified remotely; run on the receiver host", 2)
        if not live_connection:
            return
    if int(flags) & (1 << 11):
        raise SmokeFailure(BUSY_MESSAGE, 4)


def receiver_connection(address, port):
    """Inspect local RTSP ownership before opening our disposable info connection.

    A bind without listen checks local address ownership, without contacting a
    receiver. For remote receivers no principal-connection claim can be made.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as local:
            local.bind((address, 0))
    except OSError:
        return None
    result = run("ss", "-Htn", "state", "established",
                 "(", "src", address, "and", "sport", "=", f":{port}", ")", capture=True)
    return bool(result.stdout.strip())


def check_receiver_idle(receiver):
    async def probe():
        from pyatv import scan
        from pyatv.const import Protocol
        from pyatv.support.http import decode_bplist_from_body, http_connect

        hosts = os.environ.get("AB_SCAN_HOSTS")
        devices = await scan(
            asyncio.get_running_loop(),
            identifier=receiver,
            hosts=hosts.split(",") if hosts else None,
            timeout=2,
        )
        if not devices:
            raise SmokeFailure("AirPlay receiver not found during busy check", 2)
        device = devices[0]
        service = device.get_service(Protocol.RAOP) or device.get_service(Protocol.AirPlay)
        live = await asyncio.to_thread(receiver_connection, str(device.address), service.port)
        connection = await http_connect(str(device.address), service.port)
        try:
            # A separate, short-lived control connection: never the classic stream.
            response = await connection.send_and_receive(
                "GET", "/info", protocol="RTSP/1.0", headers={"CSeq": "1"}
            )
            info = decode_bplist_from_body(response) if response.code == 200 else {}
            reject_busy(info.get("statusFlags", 0), info.get("model", ""), live)
        finally:
            connection.close()

    async def bounded():
        async with asyncio.timeout(5):
            await probe()

    asyncio.run(bounded())


def reject_busy_log(path):
    if re.search(
        r"(?:RTSP/1\.0 453|code[=: ]+453|failed.*play.lock)", path.read_text(errors="replace"), re.I
    ):
        raise SmokeFailure(BUSY_MESSAGE, 4)


async def observe_pcm(path, seconds):
    """Sole reader of an isolated test receiver, never of the deployed audio FIFO."""
    path = Path(path)
    if not stat.S_ISFIFO(path.stat().st_mode):
        raise ValueError("--pcm-pipe must name an isolated receiver FIFO")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    count = nonzero = peak = 0
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                data = b""
            samples = array.array("h", data[: len(data) // 2 * 2])
            count += len(samples)
            nonzero += sum(abs(value) > 8 for value in samples)  # exclude pipe dithering noise
            peak = max(peak, max((abs(value) for value in samples), default=0))
            await asyncio.sleep(0.005)
    finally:
        os.close(fd)
    print(f"Local receiver PCM: samples={count}, nonzero={nonzero}, peak={peak}", flush=True)
    return peak > 3000


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


def smoke(receiver, protocol_version="auto", pcm_pipe=None, debug_log=None):
    if not pcm_pipe:
        assert_route("AirPlay")
    check_receiver_idle(receiver)
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
                select_protocol_version(receiver, protocol_version, remote)
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
                    "volume=if(lt(mod(t\\,0.5)\\,0.1)\\,4.0094979\\,0):eval=frame",
                    str(pulse),
                )

                async def test():
                    monitor = asyncio.create_task(
                        observe_pcm(pcm_pipe, 15) if pcm_pipe else observe(15, require_level=True)
                    )
                    await asyncio.sleep(0.2)
                    process = subprocess.Popen(
                        sender(receiver, "--debug", "set_volume=100", f"stream_file={pulse}"),
                        stdout=debug,
                        stderr=debug,
                    )
                    try:
                        try:
                            result = await asyncio.to_thread(process.wait, 30)
                        except subprocess.TimeoutExpired:
                            raise SmokeFailure("AirPlay handshake/stream timed out", 2) from None
                        debug.flush()
                        report_protocol_version(log_path)
                        reject_busy_log(log_path)
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
            finally:
                debug.flush()
                if debug_log:
                    shutil.copyfile(log_path, debug_log)
    print(
        "Non-silent PCM detected"
        if pcm_pipe
        else "Beats detected: yes — owner must verify lights react"
    )


def logger(label, duration, out, *, raw_detector=False):
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
            *(["--raw-detector"] if raw_detector else []),
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


def bench_base():
    """Persistent capture, reference and track root."""
    return Path(os.environ.get("AB_BASE", "/var/lib/lampastream/ab"))


def capture(search, receiver, requested_duration, protocol_version="auto", *,
            raw_detector=False, anchor="content"):
    couplings = capture_couplings()
    original = api("/status").get("active_coupling_id")
    player_name = os.environ.get("AB_LMS_PLAYER")
    if not player_name:
        raise RuntimeError("AB_LMS_PLAYER is required (exact LMS room name)")
    track_path = Path(os.environ.get("AB_TRACK_PATH", str(bench_base() / "track.flac")))
    if not track_path.is_file():
        raise RuntimeError(f"Local FLAC missing: {track_path}")
    for command in ("atvremote", "tcpdump", "ffprobe", "systemctl", "journalctl"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing tool: {command}; run install-ab-tools.sh")
    if not CREDS.is_file():
        raise RuntimeError("AirPlay credential storage missing; run ab-airplay-smoke.sh first")
    check_receiver_idle(receiver)
    run("systemctl", "is-active", "--quiet", "lampastream")
    asyncio.run(observe(0.3))
    receiver_scan = run(*sender(receiver, "scan"), capture=True).stdout
    address_match = re.search(r"Address:\s+(\S+)", receiver_scan)
    if not address_match:
        raise RuntimeError("AirPlay receiver was not found during preflight")
    receiver_address = address_match.group(1)
    select_protocol_version(receiver, protocol_version)
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
    base = bench_base()
    base.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="ab-run-", dir=base))
    manifest = dict(
        track=song,
        local_track=str(track_path),
        duration=seconds,
        player=player,
        player_name=player_name,
        receiver_id=receiver,
        sender_protocol_version=protocol_version,
        runs={},
        coupling_ids=couplings,
        original_coupling_id=original,
        clock_coordinates=(
            "accent track seconds; missing anchors are empty; raw beat clocks are separate"
        ),
    )
    active = []
    armed = False
    try:
        for label in ("lms", "airplay"):
            if label == "airplay":
                check_receiver_idle(receiver)
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
                log = logger(label, seconds + 2, out, raw_detector=raw_detector)
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
                    sender_log = out / "airplay-sender.log"
                    with sender_log.open("w") as sender_debug:
                        stream = subprocess.Popen(
                            sender(receiver, "--debug", f"stream_file={track_path}"),
                            stdout=sender_debug,
                            stderr=sender_debug,
                        )
                    active.append(stream)
                    deadline = time.monotonic() + seconds
                    while stream.poll() is None and time.monotonic() < deadline:
                        if log.poll() is not None:
                            raise RuntimeError("Logger exited during AirPlay run")
                        time.sleep(0.2)
                    if stream.poll() not in (None, 0):
                        reject_busy_log(out / "airplay-sender.log")
                        raise RuntimeError("AirPlay sender failed")
                    stop(stream)
                    manifest["sender_protocol_version_used"] = report_protocol_version(sender_log)
                # Let the logger finish and flush its trailing interval.
                log.wait(timeout=seconds + 5 if label == "airplay" else 8)
                if log.returncode:
                    raise RuntimeError("Logger failed")
                stop(packet)
            manifest["runs"][label]["end"] = utc()
            manifest["runs"][label].update(
                json.loads((out / f"{label}-manifest.json").read_text()))
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
    write_analysis(out, track_path, song["title"], anchor=anchor)


def write_analysis(out, track_path, title=None, *, anchor="content"):
    """Nearest reference beats, 30-second median/MAD; never infer a beat grid."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or track_path.stem).lower()).strip("-")
    explicit = os.environ.get("AB_REFERENCE_BEATS")
    candidates = (
        [Path(explicit)]
        if explicit
        else [
            track_path.parent / "beats.csv",
            Path.cwd() / "own" / slug / "beats.csv",
            Path(os.environ.get("AB_REFERENCE_ROOT", str(bench_base())))
            / "own" / slug / "beats.csv",
            track_path.parent / "own" / slug / "beats.csv",
            HERE.parent / "tests" / "fixtures" / "own" / slug / "beats.csv",
            HERE.parent / "artifacts" / "acceptance" / "own" / slug / "beats.csv",
            *([HERE.parent / "tests" / "fixtures" / "ab-references" /
               "mau-p-jalbm" / "beats.csv"] if slug in {
                   "just-a-little-bit-more", "just-a-little-bit-more-extended",
                   "mau-p-just-a-little-bit-more-extended", "mau-p-jalbm"} else []),
        ]
    )
    reference = next((p for p in candidates if p.is_file()), None)
    lines = [
        "# A/B offsets",
        "",
        "Accent track seconds versus nearest reference beat. "
        "Offsets are not latency measurements.",
        "",
    ]
    if reference is None:
        lines += [
            "NOT EVALUATED: no reference beats.csv. Set AB_REFERENCE_BEATS "
            "or place it beside the track or in own/<slug>/."
        ]
    else:
        with reference.open() as stream:
            rows = list(csv.DictReader(stream))
        ref = sorted(float(r["time_s"]) for r in rows if math.isfinite(float(r["time_s"])))
        if not ref:
            raise RuntimeError("Reference beats.csv has no finite time_s values")
        lines += [
            f"Reference: {reference}",
            "",
            "| Bin (s) | LMS median / MAD (ms), n | AirPlay median / MAD (ms), n |",
            "|---|---|---|",
        ]
        shutil.copyfile(reference, out / "reference-beats.csv")
        intervals = [b-a for a, b in zip(ref, ref[1:], strict=False) if b > a]
        period_ms = statistics.median(intervals) * 1000 if intervals else None
        bins = {}
        verdicts = {}
        for label in ("lms", "airplay"):
            status_path = out / f"{label}-status.jsonl"
            statuses = ([json.loads(line) for line in status_path.read_text().splitlines()]
                        if status_path.exists() else [])
            points = [(r["t_wall"], r["track"]["position_s"], r.get("t_monotonic"))
                      for r in statuses if r.get("track")
                      and r["track"].get("playing")
                      and r["track"].get("position_s") is not None]
            rate = None
            if len(points) > 1:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                xm, ym = statistics.mean(xs), statistics.mean(ys)
                variance = sum((x-xm)**2 for x in xs)
                if variance:
                    rate = (sum((x-xm)*(y-ym) for x, y in zip(xs, ys, strict=True))
                            / variance - 1) * 1000
            fixed = next((p for p in points if p[1] >= 15), None)
            coordinate = ("fixed anchor (first post-15 s status, slope 1)"
                          if label == "lms" and anchor == "fixed" else
                          "content_t" if label == "lms" else "audible_t (RTP anchor)")
            lines.insert(-2, f"{label} table coordinate: {coordinate}; position_s rate vs wall: "
                         + (f"{rate:+.3f} ms/s" if rate is not None else "unavailable"))
            with (out / f"{label}-beats.csv").open() as stream:
                events = [r for r in csv.DictReader(stream) if r.get("source") != "bass_trigger"]
            # Older captures have only wall receipt times. Estimate the constant
            # clock offset once; receipt latency affects absolute phase, not slope.
            clock_offsets = [float(r["wall_t"]) - float(r["audible_monotonic"])
                             for r in events if r.get("wall_t") and r.get("audible_monotonic")]
            fixed_mono = (fixed[2] if fixed and fixed[2] is not None else
                          fixed[0] - statistics.median(clock_offsets)
                          if fixed and clock_offsets else None)
            if label == "lms" and anchor == "fixed" and fixed and fixed[2] is None:
                lines.insert(-2, "Fixed anchor uses an estimated wall/monotonic offset "
                             "from beat receipt times; absolute phase is approximate.")
            times = []
            for row in events:
                if label == "lms" and anchor == "fixed":
                    value = (fixed[1] + float(row["audible_monotonic"]) - fixed_mono
                             if fixed_mono is not None and row.get("audible_monotonic") else None)
                else:
                    value = row.get("content_t" if label == "lms" else "audible_t")
                if value is not None and value != "":
                    times.append(float(value))
            offsets = {}
            for t in times:
                if not math.isfinite(t) or t < ref[0] - 0.25 or t > ref[-1] + 0.25:
                    continue
                i = bisect.bisect_left(ref, t)
                near = min(ref[max(0, i - 1) : min(len(ref), i + 1)], key=lambda x: abs(x - t))
                offsets.setdefault(int(t // 30) * 30, []).append((t - near) * 1000)
            all_offsets = [v for values in offsets.values() for v in values]
            center = statistics.median(all_offsets) if all_offsets else 0.
            medians, mads = {}, {}
            for start, values in offsets.items():
                if period_ms:
                    values = [(v-center+period_ms/2) % period_ms-period_ms/2+center
                              for v in values]
                median = statistics.median(values)
                mad = statistics.median(abs(v - median) for v in values)
                bins.setdefault(start, {})[label] = f"{median:+.1f} / {mad:.1f}, {len(values)}"
                medians[start], mads[start] = median, mad
            ordered = sorted(medians)
            delays = [r["light_timing"]["status"]["applied_delay_ms"] for r in statuses
                      if r.get("light_timing") and r["light_timing"].get("status")
                      and r["light_timing"]["status"].get("session_anchor_at") is not None
                      and r["light_timing"]["status"].get("applied_delay_ms") is not None]
            stable = bool(delays) and all(abs(d-delays[0]) <= 2 for d in delays)
            no_step = all(abs(medians[b]-medians[a]) <= 10
                          for a, b in zip(ordered, ordered[1:], strict=False)
                          if b-a > 30)
            verdicts[label] = (bool(ordered) and no_step
                and all(abs(medians[k]-medians[ordered[0]]) <= 10 for k in ordered)
                and all(m <= 15 for m in mads.values())
                and (stable if label == "lms" else True))
            if label == "airplay":
                verdicts[label] = (bool(ordered) and ordered[0] == 0
                    and ordered[-1] >= int(ref[-1] // 30) * 30
                    and all(abs(medians[k]) <= 40 for k in ordered)
                    and all(b-a == 30 and abs(medians[b]-medians[a]) < 20
                            for a, b in zip(ordered, ordered[1:], strict=False)))
            lines.insert(-2, f"{label}: absolute offset {center:+.1f} ms (not judged); "
                         f"anchored applied delay constant ±2 ms: "
                         f"{stable if label == 'lms' else 'N/A'}.")
        for start, values in sorted(bins.items()):
            lines.append(
                f"| {start}–{start + 30} | {values.get('lms', '—')} "
                f"| {values.get('airplay', '—')} |"
            )
        lines += [
            "",
            *[
                f"{label}: {'PASS' if passed else 'FAIL / INCOMPLETE'} "
                + ("(populated bins within ±10 ms of first; MAD ≤15 ms; "
                   "no kickless-section step >10 ms; anchored applied delay ±2 ms)."
                   if label == "lms" else "(±40 ms; adjacent bins <20 ms).")
                for label, passed in verdicts.items()
            ],
            "",
            "Sparse beats, breaks, missing bins and nearest-beat phase ambiguity "
            "require inspection; no step across a kickless section must be confirmed "
            "from the bins on both sides (≤10 ms).",
        ]
    (out / "analysis.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    smoke_parser = sub.add_parser("smoke")
    smoke_parser.add_argument("receiver")
    smoke_parser.add_argument("--pcm-pipe", help="sole reader of an isolated local test receiver")
    smoke_parser.add_argument("--debug-log", help="retain complete sender debug log")
    smoke_parser.add_argument("--protocol-version", choices=("auto", "1", "2"), default="auto")
    cap = sub.add_parser("capture")
    cap.add_argument("search")
    cap.add_argument("receiver")
    cap.add_argument("--protocol-version", choices=("auto", "1", "2"), default="auto")
    cap.add_argument("duration", type=float, nargs="?")
    cap.add_argument("--raw-detector", action="store_true")
    cap.add_argument("--anchor", choices=("content", "fixed"), default="content")
    analysis = sub.add_parser("analyse")
    analysis.add_argument("out", type=Path)
    analysis.add_argument("track", type=Path)
    analysis.add_argument("--anchor", choices=("content", "fixed"), default="content")
    args = parser.parse_args()
    # SIGTERM must unwind the same cleanup as Ctrl-C.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.mode == "smoke":
            smoke(args.receiver, args.protocol_version, args.pcm_pipe, args.debug_log)
        elif args.mode == "analyse":
            if args.out.is_dir():
                write_analysis(args.out, args.track, anchor=args.anchor)
            else:
                with tempfile.TemporaryDirectory(prefix="ab-analyse-") as directory:
                    out = Path(directory)
                    with tarfile.open(args.out, "r:gz") as tar:
                        tar.extractall(out, filter="data")
                    write_analysis(out, args.track, anchor=args.anchor)
                    result = args.out.with_name(
                        args.out.name.removesuffix(".tar.gz") + "-analysis.md")
                    shutil.copyfile(out / "analysis.md", result)
                    print(result, flush=True)
        else:
            capture(args.search, args.receiver, args.duration, args.protocol_version,
                    raw_detector=args.raw_detector, anchor=args.anchor)
    except (Exception, KeyboardInterrupt) as error:
        traceback.print_exc()
        parser.exit(getattr(error, "exit_code", 1))


if __name__ == "__main__":
    main()
