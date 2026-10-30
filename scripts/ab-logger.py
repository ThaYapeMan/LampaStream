#!/usr/bin/env python3
"""Log preview data; absent track time falls back to the room clock, never wall time."""

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
BEAT_FIELDS = ["audible_t", "wall_t", "strength", "source"]


def beat_row(event, wall):
    return dict(
        audible_t=(
            event.get("audible_t")
            if event.get("audible_t") is not None
            else event.get("audible_monotonic")
        ),
        wall_t=wall,
        strength=event.get("strength"),
        source=(
            "tempo_clock"
            if event.get("predicted")
            else "fused"
            if event.get("on_beat")
            else "bass_trigger"
        ),
    )


async def log(label, duration, out, url, ready=None):
    out.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(url, open_timeout=5) as socket:
        with (
            (out / f"{label}-tempo.csv").open("w") as tempo,
            (out / f"{label}-beats.csv").open("w") as beats,
        ):
            tw, bw = csv.DictWriter(tempo, TEMPO_FIELDS), csv.DictWriter(beats, BEAT_FIELDS)
            tw.writeheader()
            bw.writeheader()
            if ready:
                ready.touch()
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
                if message.get("type") == "event":
                    for event in message.get("events", []):
                        if event.get("kind") == "beat":
                            bw.writerow(beat_row(event, wall))
                    beats.flush()
                if message.get("type") == "frame" and time.monotonic() >= next_row:
                    tw.writerow(
                        dict(
                            zip(
                                TEMPO_FIELDS,
                                [
                                    wall,
                                    (
                                        message.get("audible_t")
                                        if message.get("audible_t") is not None
                                        else message.get("audible_monotonic")
                                    ),
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
    args = parser.parse_args()
    if (
        Path(args.label).name != args.label
        or not math.isfinite(args.duration)
        or args.duration <= 0
    ):
        parser.error("Use a simple label and a finite positive duration")
    try:
        asyncio.run(log(args.label, args.duration, args.out, args.url, args.ready))
    except (OSError, RuntimeError, websockets.WebSocketException) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
