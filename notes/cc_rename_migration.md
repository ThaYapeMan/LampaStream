`master` already contains the mechanical rename HueSync → LampaStream (paths, package, installer, units, docs, web bundle; backend 1244 passed, frontend 260 passed). Read `docs/LampaStream_rename_inventory.md` §3 if present, otherwise this file is the full specification. Your task is the one part that is not mechanical: **migrating an existing installation**, plus the deploy runbook. Do not touch anything else; do not "improve" the rename. Do not deploy anywhere.

## Why this must exist before the next deploy

The renamed installer installs to `/opt/lampastream`, config at `/etc/lampastream/config.json`, unit `lampastream.service`, user `lampastream`. On the LXC the old layout is live: `/opt/huesync`, `/etc/huesync/config.json`, `huesync.service`, user `huesync`. Without a migration the installer would start a second, empty instance next to the running one (port conflict, no config, no couplings). That must be impossible.

## Migration — inside the installer's existing "migrate persisted data" stage, once, idempotently, when the old layout is detected

1. Stop and disable `huesync.service`; install and verify the new unit and `49-lampastream-airplay.rules` before removing the old unit and rules.
2. Move `/etc/huesync/config.json` → `/etc/lampastream/config.json`, `chown lampastream:lampastream`; remove the old directory only after the new service has started successfully.
3. Do **not** move the existing venv (it contains absolute paths); build a fresh release under `/opt/lampastream/`; leave `/opt/huesync/` in place and print the manual cleanup command at the end.
4. Create the `lampastream` user/group; migrate ownership; remove `huesync` user/group last, only after a successful start.
5. `/run/lampastream` via the tmpfiles.d entry.
6. Stored display names in `config.json`: rewrite `player_name` / `display_name` / the advertised AirPlay name from `HueSync…` to `LampaStream…`; **never change `player_mac`** (a changed MAC makes LMS see a new player and breaks the follow configuration). Log every rewritten field with old and new value.
7. `--check` recognises both layouts during the transition and prints which one it found.

## Tests (extend `tests/test_installer.py` / `test_repository_installer.py`)

- Old layout present → new layout after one run; `huesync.service` disabled; old unit/rules removed only after the new one is verified.
- Second run is a no-op (idempotent).
- `player_mac` unchanged; display names rewritten; each rewrite logged.
- `--check` output for old, new, and mixed layouts.
- Fresh install (no old layout) unaffected.

## Deploy runbook — `docs/deployment-rename-cutover.md`

Exact commands for the LXC: `git pull`, `sudo ./scripts/install-lampastream.sh`, the migration log lines to expect, `sudo ./scripts/install-lampastream.sh --check`, Stop → Go in the UI (Hue stream re-handshake after any deploy), how to verify (`systemctl status lampastream`, the web UI header, the LMS player list showing "LampaStream LMS" with the **same** MAC), the manual cleanup of `/opt/huesync/`, and the optional `pct set 112 --hostname lampastream` on the Proxmox host. Also the rollback: `systemctl start huesync` still works until the old unit is removed — say at which step that stops being true.

## Report — no exceptions

Paste actual output of: `git status` (clean), `git log -1 --stat`, `git diff HEAD^ HEAD --stat`, full `pytest -q` (the new migration tests visibly included), `npm test` counts, `npm run build`, `git ls-remote origin master`. If a step fails, say so and do not claim done.
