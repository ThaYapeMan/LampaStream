# Target LXC deployment and validation

Status: **REQUIRES LXC VALIDATION**. Local source checks and stubbed native boundaries
cannot establish live deployment behavior.

## Before activation

```sh
git clone --recurse-submodules https://github.com/ThaYapeMan/LampaStream.git
cd LampaStream
sudo ./scripts/install-lampastream.sh
sudo ./scripts/install-lampastream.sh --check
```

The repository installer is the authoritative standard deployment path. It owns
packages, full native builds, frontend/wheel installation, schema migration and
services. Do not reproduce separate manual dependency or producer-patching steps.
`--check` is read-only verification of an existing Debian 13/trixie x86_64
installation with systemd running (`/run/systemd/system`). It does not install,
migrate or modify the host. For development-host checks, see [testing](testing.md).
The wheel pins `hue-entertainment==0.3.0`; the installer resolves that exact
version from wheel metadata. Verification checks both the installed LampaStream
requirement and client version, refusing a floating declaration or another version:

```text
Hue Entertainment client: hue-entertainment 0.3.0: PASS
```

HueDriver explicitly selects RGB. Its command adapter retains the original lamp
bytes for very low RGB values despite the upstream 0.3.0 encoding change; XY/VIVID
are not enabled by this update. No manual dependency installation is needed.

Record its commit/binary hashes and run it twice to verify target idempotency.

yeney-player paces LMS PCM internally. snd-dummy and `/dev/snd` passthrough are
no longer required. Existing host setups can keep them harmlessly. To remove them
when no other container/application needs them, stop LampaStream, remove the
`/dev/snd` bind mounts and audio-device cgroup allow entries from the container's
host configuration, remove the snd-dummy line from `/etc/modules` or the applicable
`/etc/modules-load.d/` file, and remove any snd-dummy options file under
`/etc/modprobe.d/`. Unload with `modprobe -r snd-dummy` only when unused, or reboot
the host during planned maintenance. Restart the container and LampaStream.
The guest installer does not change host configuration.

Select canonical PCM + V2/CAVA Core or the intentional external FIFO route in
LampaStream. Inspect `journalctl -u lampastream`.

Do not read a production audio FIFO from a diagnostic second consumer. For SHM,
inspect metadata or use isolated test fixtures. Unsupported canonical ABI is a
producer-upgrade error, never permission to use v0/header bytes as PCM.

## Required target evidence

- Full producer build/link with target g++/make/libFLAC dependencies.
- Live source continuity across restart, gap, overrun and SHM replacement.
- Native CAVA loading/execution, repeated close/reset and allocation/leak stress.
- Wheel build and clean installation in a fresh environment.
- CPU/backlog behavior under both engines and multiple processors.
- Source-consistent acceptance and visual comparison; record engine identities,
  sample intervals and configuration, including CAVA's 100 Hz execution cadence.

On a stuck worker, source ownership is retained. Do not force a new session on the
same source. Inspect `analysis_stopping`, release/fix the source condition, then retry
teardown. A service process exit has OS cleanup semantics; it is not evidence that
an in-process timed-out teardown successfully joined its worker.

Archive results with commit, producer revision, dependencies, hardware/container limits,
commands and raw artifacts. Old production benchmarks apply only to their original
context and do not certify this implementation.

## Disaster recovery

1. Install from Git on a clean supported target using `scripts/install-lampastream.sh`.
2. Transfer the sensitive portable backup securely; keep file permissions private.
3. Use **Backup and restore** in the UI, or stop LampaStream and use the installed
   `python -m lampastream.backup import` CLI, then restart the service.
4. Verify all entities, exact IDs, LMS/AirPlay settings, player latencies and references.
5. Activate a restored Coupling and verify the original Hue Bridge works without
   re-pairing. This depends on reachable, still-valid Bridge credentials.
6. Verify both source paths on the target; do not run the old and new installations
   simultaneously against the same virtual-player identity or Bridge session.

Local round-trip tests are not evidence of completed LXC disaster recovery. Record
live Hue/LMS/AirPlay recovery separately. See [configuration](configuration.md#backup-and-restore)
for safety backups, offline runtime exclusion, API errors and format versions.


The LMS VirtualPlayer is yeney-player from `third_party/yeney-core` pinned to
`9fba26f0bcc9a10def8063c5d269b2bbe62b687a` (ALAC remains `5d8c5db`), a virtual
player synced to the listening room (YeneY/Sonos or another LMS player), delivering
stereo float PCM through yeney-core SHM v1. `YeneyCoreShmStereoSource` names that
reader; `SqueezeliteShmStereoSource` remains a deprecated alias for one release.
Player-specific ingress owns timing knowledge. See the ROUTE-01
[architecture](architecture.md); rendering and scheduling are shared.

Installer output shows every step and subprocess result by default. Add `--quiet`
for layout, source commit and final summary only. Failures include full diagnostics
in both modes; `--verbose` remains an alias of the default.

Installer output (BATCH-01): full build, subprocess and passing check output is the default, including `--check`. Use `--quiet` for the short form; failures replay full diagnostics and exit non-zero in either mode. `--verbose` remains an alias for the default.

## Grid database service ownership

The standard installer gives `lampastream:lampastream` ownership of
`/var/lib/lampastream` (0750), `grids.db` (0640), `grids.db.lock` (0600),
`grids.db.restore-pending` (0640 when present), migration archives and restore
safety backups (0640). It fixes these immediately after grid migration.
Root-run grid maintenance or backup must not leave a root-owned lock in the
service-owned directory. The stable lock retains O_NOFOLLOW protection.

`sudo ./scripts/install-lampastream.sh --check` verifies the database and shared
lease as the service user and prints `Grid database access: PASS`. It does not
repair permissions. A root-owned 0600 lock produces `grid_fetch_state: failed`;
Now Playing shows “measured” instead of “grid”. The one-line repair for the
owner-reported lock defect is:

```sh
sudo chown lampastream:lampastream /var/lib/lampastream/grids.db.lock
```

Use the standard installer to reconcile the full set of directory, database,
sidecar and backup permissions. The check releases its shared lease immediately;
it never creates a missing lock or changes ownership.

BEAT-02 B upgrades grids.db from schema 1 to 2 during the standard installer.
The installer stops an active old service before persisted-schema cutover, retains
an online SQLite safety snapshot (`grids.db.pre-metadata-v2.*.sqlite`), then applies
the same service-user ownership policy and verifies access before release start.
Use 115 first and leave it disabled after the bench, then deploy the accepted
commit on 112. Runtime and uploaded backups accept only the exact current schema.
