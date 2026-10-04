# SHM v1 ABI

This ABI is now implemented by yeney-core's yeney-player, pinned at
`45779a4383929840a46a931fc1519b4778b64a72` in `third_party/yeney-core`.
The `/dev/shm/squeezelite-<mac>` name and legacy lock region remain ABI contracts.
Canonical PCM and external CAVA use the same internally paced producer; no ALSA
output device is required. The local C sources and patch are historical provenance
retained for the earlier seqlock audit tests; they are not built or deployed.

The repository installer builds yeney-player and records its SHA256 and core revision.
See [installation](../docs/installation.md) and [testing](../docs/testing.md).

## ABI layout

The supported target layout is little-endian, with the legacy pthread-lock/header
region preserved and a packed 40-byte extension after the PCM ring. C static
assertions and Python struct formats define the same offsets.

| Absolute byte offset | Field | Type / units |
|---:|---|---|
| 0–55 | Legacy lock region | Target ABI layout |
| 56 | buf_size | uint32, scalar int16 sample capacity |
| 60 | buf_index | uint32, scalar int16 write index |
| 64 | running | uint8; padding through 67 |
| 68 | rate | uint32, Hz |
| 72 | updated | int64 legacy timestamp; not continuity evidence |
| 80 | PCM ring | Interleaved signed int16 L/R, 32768 bytes |
| 32848 | magic | uint32 `0x48555345` |
| 32852 | abi_version | uint16, exactly 1 |
| 32854 | flags | uint16 reserved |
| 32856 | write_seq | uint32, odd while writing; even stable |
| 32860 | generation | uint64 producer lifetime ID |
| 32868 | abs_write_pos | uint64 exclusive **stereo-frame** position |
| 32876 | gap_seq | uint64 export-gap counter |
| 32884–32887 | padding | 4 bytes |

Default ring capacity is 16384 scalar samples = 8192 stereo frames = 32768 bytes;
total mapping size is 32888 bytes. One stereo frame advances abs_write_pos by 1 and
buf_index by 2 modulo scalar capacity. Do not double-add absolute positions or treat
the trailing extension bytes as PCM.

## Snapshot, initialization and gaps

The reader does not take the producer pthread lock. The producer's sequence protects
legacy metadata, extension metadata and PCM changes, including stop/silence transitions.
The reader verifies sequence and generation after copying PCM, rejecting torn snapshots.

Initialization may reuse an old segment. `vis_shm_v1_begin_init()` returns void and
forces an odd uint32 successor: even +1, odd +2, modulo 2^32. It runs before legacy
metadata writes. `vis_shm_v1_finish_init()` fills extension state and publishes even;
it returns -1 if secure generation creation fails. `getrandom` or `/dev/urandom`
supplies generation; there is no PID/time fallback. A failed initialization remains
unavailable. Sequence wrap is intentional: 0xffffffff → 1 during init → 2 at completion.

Skipped exports retain producer-local pending gap state when the SHM lock is unavailable.
The next successful write publishes a changed gap_seq. The reader invalidates once for
that observed change, establishes a new baseline, then accepts subsequent clean data.
Absolute position exposes full/multiple laps and overrun; regression, generation change,
rate/restart and gap changes invalidate before new PCM enters the old DSP epoch.

## Production consumer and remap

`SqueezeliteShmStereoSource(require_v1=True)` is the production canonical reader.
Wrong magic, v0 and unsupported versions cannot fall back to legacy PCM. An initial
unsupported producer causes an actionable activation error: rebuild/upgrade it.

Backing-object device/inode change closes the old mmap and establishes pending remap.
Absent or incompletely initialized replacements remain unavailable and are retried.
A rejected ABI belongs to that mapping only: a later inode replacement by valid v1
is detected, revalidated and remapped. The new generation/counters establish a fresh
baseline; StreamInvalidated precedes delivery of its PCM. An unsupported unchanged
mapping remains rejected. No v0/header-as-PCM fallback is permitted under require_v1.

The manager retains this source while any reader is retiring. Do not close/remap it
from a second management path while that worker is active.

## Diagnostics

```sh
xxd -s 32848 -l 40 /dev/shm/squeezelite-<mac>
```

At offset 0x8050, little-endian magic bytes are `45 53 55 48`; version bytes are
`01 00`. Wrong bytes commonly mean the stock/old executable is still running.
Check process executable, permissions, rate, generation, sequence and gap changes.
Do not use the legacy updated timestamp to prove continuity.

Local tests establish source logic and compiler outputs. Live producer-to-consumer
behavior, target ABI/toolchain compatibility and realtime pacing still require the
LXC validation procedure in [deployment-lxc.md](../docs/deployment-lxc.md).
