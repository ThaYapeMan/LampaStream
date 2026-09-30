#!/usr/bin/env python3
"""Read-only AirPlay diagnostic client. Never opens either production FIFO."""

from __future__ import annotations

import argparse
import json
import time
from urllib.request import urlopen

from lampastream.airplay_timing import CadenceCheck, percentile


def report(events, *, now, emit=print):
    cadence = CadenceCheck()
    processing = []
    all_windows = {}
    all_jitter = []
    faults = set()
    was_steady = False
    for event in events:
        kind = event["kind"]
        if kind == "reset" or (
            kind == "metadata"
            and event["code"] in {"pbeg", "phb0", "pres", "paus", "pfls", "pend", "aend"}
        ):
            cadence.reset()
            was_steady = False
        elif kind == "arrival":
            if cadence.previous is not None:
                all_jitter.append(
                    abs(event["monotonic"] - cadence.previous - cadence.previous_frames / 44100)
                    * 1000
                )
            cadence.observe(event["frames"], event["monotonic"])
            check = cadence.status(event["monotonic"])
            for window in check["windows"]:
                all_windows[window["start_monotonic"]] = window
            if check["state"] == "steady":
                was_steady = True
            elif was_steady and check["reason"]:
                faults.add(check["reason"])
        elif kind == "processing":
            processing.append(event["processing_ms"])
        if kind == "metadata":
            crosscheck = ""
            if event["code"] in {"phb0", "phbt"}:
                try:
                    play_ns = int(event["payload"].split("/")[-1])
                    crosscheck = (
                        f" · play time minus event {(play_ns - event['local_raw_ns']) / 1e6:.2f} ms"
                    )
                except (ValueError, KeyError):
                    pass
            emit(
                f"Metadata {event['code']}: {event['payload']} · "
                f"after arrival {event.get('since_arrival_ms')} ms{crosscheck}"
            )
    result = cadence.status(now)
    for window in all_windows.values():
        emit(
            f"Arrival window {window['start_monotonic']:.3f}: "
            f"{window['frames_per_second']} frames/s"
        )
    emit(
        f"Arrival jitter (ms, including warm-up): count={len(all_jitter)} "
        f"p50={percentile(all_jitter, 0.5)} p95={percentile(all_jitter, 0.95)} "
        f"max={max(all_jitter, default=None)}"
    )
    emit(
        f"Largest gap: {result['largest_gap_ms']:.2f} ms · "
        f"largest burst: {result['largest_burst_frames']} frames"
    )
    emit(
        f"Processing P (ms): count={len(processing)} p50={percentile(processing, 0.5)} "
        f"p95={percentile(processing, 0.95)} max={max(processing, default=None)}"
    )
    passed = result["state"] == "steady" and not faults
    for fault in sorted(faults):
        emit(f"Pacing fault during observation: {fault}")
    emit(
        f"PASS: steady real-time pacing within {result['tolerance_ms']} ms"
        if passed
        else (
            f"FAIL: not steady real-time pacing within {result['tolerance_ms']} ms "
            f"({result['reason'] or 'not enough playback'})"
        )
    )
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--url", default="http://127.0.0.1:8420/api/airplay-timing")
    parser.add_argument("--output", help="Save the received diagnostic events as JSON lines")
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("duration must be positive")
    sequence = 0
    events = []
    deadline = time.monotonic() + args.duration
    first = True
    output = open(args.output, "w") if args.output else None
    try:
        while True:
            with urlopen(f"{args.url}?after={sequence}", timeout=3) as response:
                data = json.load(response)
            if first:
                # Ignore history from before this observation interval.
                sequence = data["sequence"]
                first = False
            else:
                if data["dropped"]:
                    print("FAIL: diagnostic events were lost; shorten the polling interval")
                    return 1
                for event in data["events"]:
                    events.append(event)
                    if output:
                        output.write(json.dumps(event) + "\n")
                sequence = data["sequence"]
                pacing = data["pacing"]
                print(
                    f"Pacing: {pacing['state']} · latest window "
                    f"{pacing['windows'][-1] if pacing['windows'] else 'warming up'}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(1, remaining))
        return 0 if report(events, now=time.monotonic()) else 1
    except (OSError, ValueError) as exc:
        print(f"FAIL: diagnostic service unavailable: {exc}")
        return 1
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
