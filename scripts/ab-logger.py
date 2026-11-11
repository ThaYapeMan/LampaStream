#!/usr/bin/env python3
"""Log rendered accents in track seconds, with detector diagnostics on request."""

import argparse
import asyncio
import csv
import json
import math
import time
from pathlib import Path

import websockets

TEMPO_FIELDS = [
    "t_wall",
    "audible_t",
    "tempo_bpm",
    "tempo_alt_bpm",
    "confidence",
    "locked",
    "beats_per_s",
    "texture_per_s",
    "agc_gain",
    "trigger_ratio",
]
BEAT_FIELDS = [
    "audible_t",
    "content_t",
    "audible_monotonic",
    "detected_audible_t",
    "detected_audible_monotonic",
    "wall_t",
    "strength",
    "source",
    "predicted",
]


def beat_row(event, wall, source):
    if event.get("detected_audible_monotonic") is None:
        raise RuntimeError("Preview event lacks detection time; deploy the updated server")
    return dict(
        audible_t=event.get("detected_audible_t" if source == "bass_trigger" else "audible_t"),
        content_t=event.get("content_t"),
        audible_monotonic=event.get("audible_monotonic"),
        detected_audible_t=event.get("detected_audible_t"),
        detected_audible_monotonic=event["detected_audible_monotonic"],
        wall_t=wall,
        strength=event.get("strength"),
        source=source,
        predicted=bool(event.get("predicted")),
    )


def beat_rows(event, wall, mode, raw_detector):
    if event.get("kind") != "beat" or mode == "off":
        return
    identity = event.get("id", ())
    onset = len(identity) > 1 and identity[1] in {"bass", "mid", "treble", "full"}
    source = event.get("beat_source")
    if source not in {"grid", "tracker", "onset"}:
        source = "onset" if onset or mode == "onset" else "tracker"
    yield beat_row(event, wall, source)
    if (
        raw_detector
        and source != "grid"
        and not event.get("predicted")
        and not event.get("on_beat")
    ):
        yield beat_row(event, wall, "bass_trigger")


async def log(label, duration, out, url, ready=None, *, raw_detector=False):
    out.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(url, open_timeout=5) as socket:
        with (
            (out / f"{label}-tempo.csv").open("w") as tempo,
            (out / f"{label}-beats.csv").open("w") as beats,
            (out / f"{label}-status.jsonl").open("w") as status,
        ):
            tw, bw = csv.DictWriter(tempo, TEMPO_FIELDS), csv.DictWriter(beats, BEAT_FIELDS)
            tw.writeheader()
            bw.writeheader()
            if ready:
                ready.touch()
            mode = None
            deadline, next_row = time.monotonic() + duration, 0.0
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        socket.recv(), min(3.0, deadline - time.monotonic())
                    )
                except TimeoutError:
                    if time.monotonic() >= deadline:
                        break
                    raise RuntimeError("Preview socket stopped sending data") from None
                message, wall = json.loads(raw), time.time()
                if message.get("type") == "status":
                    # Preserve the actual anchor/trim/source used during capture.
                    status.write(json.dumps(dict(t_wall=wall, t_monotonic=time.monotonic(), **{
                        key: message.get(key) for key in (
                            "track", "light_timing", "lms_timing", "active_player_type",
                            "beat_accent_mode")
                    })) + "\n")
                    status.flush()
                    mode = message.get("beat_accent_mode")
                    if mode not in {"off", "onset", "tracker"}:
                        raise RuntimeError("Status lacks beat_accent_mode; deploy updated server")
                    manifest_path = out / f"{label}-manifest.json"
                    manifest = (json.loads(manifest_path.read_text())
                                if manifest_path.exists() else {"beat_accent_modes": []})
                    if mode not in manifest["beat_accent_modes"]:
                        manifest["beat_accent_modes"].append(mode)
                    manifest["beat_accent_mode"] = mode
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                if message.get("type") == "frame" and message.get("beat_source"):
                    manifest_path = out / f"{label}-manifest.json"
                    manifest = (json.loads(manifest_path.read_text())
                                if manifest_path.exists() else {"beat_accent_modes": []})
                    fields = ("beat_source", "grid_confidence", "grid_tempo", "grid_cache",
                              "grid_fetch_state", "grid_dropped_reason", "provisional")
                    states = manifest.setdefault("grid_states", [])
                    state = {key: message.get(key) for key in fields}
                    if not states or states[-1] != state:
                        states.append(state)
                        manifest.update(state)
                        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                if message.get("type") == "event":
                    for event in message.get("events", []):
                        bw.writerows(beat_rows(event, wall, mode, raw_detector))
                    beats.flush()
                if message.get("type") == "frame" and time.monotonic() >= next_row:
                    tw.writerow(
                        dict(
                            zip(
                                TEMPO_FIELDS,
                                [
                                    wall,
                                    message.get("audible_t"),
                                    message.get("tempo_bpm"),
                                    message.get("tempo_alt_bpm"),
                                    message.get("tempo_confidence"),
                                    message.get("tempo_locked"),
                                    message.get("beat_events_per_second"),
                                    message.get("texture_events_per_second"),
                                    message.get("agc_gain"),
                                    message.get("trigger_ratio"),
                                ],
                                strict=True,
                            )
                        )
                    )
                    tempo.flush()
                    next_row = time.monotonic() + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("duration", type=float)
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--url", default="ws://127.0.0.1:8420/ws/preview")
    parser.add_argument("--ready", type=Path)
    parser.add_argument(
        "--raw-detector",
        action="store_true",
        help="also record preview detector-origin beats as bass_trigger",
    )
    args = parser.parse_args()
    if (
        Path(args.label).name != args.label
        or not math.isfinite(args.duration)
        or args.duration <= 0
    ):
        parser.error("Use a simple label and a finite positive duration")
    try:
        asyncio.run(
            log(
                args.label,
                args.duration,
                args.out,
                args.url,
                args.ready,
                raw_detector=args.raw_detector,
            )
        )
    except (OSError, RuntimeError, websockets.WebSocketException) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
