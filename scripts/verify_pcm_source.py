#!/usr/bin/env python3
"""Verify SqueezeliteShmSource against a live squeezelite instance.

Polls read_new() for 5 seconds and prints per-poll stats + a summary.
Run on LXC 112 while music is actively playing through a LampaStream profile.

Usage:
    .venv/bin/python3 scripts/verify_pcm_source.py <mac>

    <mac> is the player_mac from the active profile, e.g. aa:bb:cc:dd:ee:ff
    Find it with:  ls /dev/shm/squeezelite-*
"""

import logging
import sys
import time
from collections import Counter

from lampastream.pcm_source import SqueezeliteShmSource

# ---------------------------------------------------------------------------
# Count torn-read discards via a custom log handler on lampastream.pcm_source.
# The torn-read path logs at DEBUG; enable that level only for this module.
# ---------------------------------------------------------------------------


class _TornReadCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.total = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "torn read" in record.getMessage().lower():
            self.total += 1


_pcm_log = logging.getLogger("lampastream.pcm_source")
_pcm_log.setLevel(logging.DEBUG)
_torn = _TornReadCounter()
_pcm_log.addHandler(_torn)

# Forward WARNING+ to the console so warnings are visible.
_console = logging.StreamHandler()
_console.setLevel(logging.WARNING)
_pcm_log.addHandler(_console)


# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    mac = sys.argv[1]
    path_hint = f"/dev/shm/squeezelite-{mac}"

    print(f"Opening {path_hint} ...")
    src = SqueezeliteShmSource()
    try:
        src.open(mac)
    except FileNotFoundError:
        print(f"\nERROR: {path_hint} not found.")
        print("  • Is squeezelite running with the -v flag?")
        print("  • Is the MAC correct? (ls /dev/shm/squeezelite-*)")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERROR opening shared memory: {exc}")
        sys.exit(1)

    print(f"Opened.  sample_rate={src.sample_rate} Hz  running={src.running}")
    print("Polling every 100 ms for 5 seconds — make sure music is playing.\n")

    header = f"{'#':>3}  {'samples':>7}  {'rate_hz':>8}  {'running':>8}  {'torn_total':>10}"
    print(header)
    print("-" * len(header))

    total_samples = 0
    rates: Counter[int] = Counter()
    POLLS = 50

    for i in range(POLLS):
        time.sleep(0.100)

        torn_before = _torn.total
        chunk = src.read_new()
        torn_this = _torn.total - torn_before

        rate = src.sample_rate
        running = src.running
        n = len(chunk)

        total_samples += n
        rates[rate] += 1

        flag = "  ← torn read discarded" if torn_this else ""
        print(f"{i+1:>3}  {n:>7}  {rate:>8}  {str(running):>8}  {_torn.total:>10}{flag}")

    src.close()

    # Summary
    print()
    print("=" * 55)
    print("Summary")
    print("=" * 55)
    print(f"  Total mono samples received : {total_samples:,}")
    print(f"  Torn reads discarded        : {_torn.total}")

    if len(rates) == 1:
        dominant_rate = rates.most_common(1)[0][0]
        print(f"  Sample rate                 : {dominant_rate} Hz  (consistent across all polls)")
    else:
        print(f"  Sample rate                 : INCONSISTENT — {dict(rates)}")
        dominant_rate = rates.most_common(1)[0][0]

    expected_per_poll = dominant_rate * 0.100  # mono frames per 100 ms at this rate
    actual_per_poll = total_samples / POLLS
    print(f"  Expected ~{expected_per_poll:.0f} mono samples/poll at {dominant_rate} Hz")
    pct = actual_per_poll / expected_per_poll * 100
    print(f"  Actual   ~{actual_per_poll:.0f} mono samples/poll  ({pct:.0f} %)")

    print()
    if total_samples == 0:
        print("VERDICT: No samples received.")
        print("         • Is music actively playing?")
        print("         • Was squeezelite started with -v (visualiser flag)?")
    elif actual_per_poll < expected_per_poll * 0.5:
        print("VERDICT: Sample count is unusually low — poll loop may be too slow,")
        print("         or squeezelite is exporting sporadically.")
    elif _torn.total > POLLS * 0.10:
        print("VERDICT: High torn-read rate — the writer is very active relative to")
        print("         the 100 ms poll interval; check for CPU contention on the LXC.")
    else:
        print("VERDICT: PCM tap looks healthy.")


if __name__ == "__main__":
    main()
