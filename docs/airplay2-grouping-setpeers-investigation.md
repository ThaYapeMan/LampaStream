# AirPlay 2 grouping investigation: SETPEERS is a no-op in shairport-sync

## Symptom

LampaStream's AirPlay 2 virtual player does not always successfully join a group with other, real AirPlay 2 speakers. Solo playback to LampaStream works reliably; grouping/coupling with a separate physical speaker is intermittent.

## Ruled out

- **LXC network topology**: the container has a single NIC (`eth0`), bridged directly onto the real LAN (`192.168.178.0/24`, `vmbr1`), no NAT. Multicast/ PTP have no NAT or routing boundary to cross — functionally indistinguishable from a physical device on the network.
- **MAC address instability**: `BC:24:11:F0:46:75` is set statically in the Proxmox container config (`net0`) and has never changed — this container has never been cloned, migrated or restored from backup. AirPlay 2's MAC-derived device identity is therefore stable across restarts.
- **Multi-interface ambiguity**: only one non-loopback interface exists, so shairport-sync/Avahi/NQPTP have nothing to disagree about.

## Root cause: confirmed in the pinned source, not inferred from issue reports

Both LampaStream's pinned `shairport-sync` commit (`0b1c4391ffd398e7b145eb4b98416261380adeea`, checked out and read directly, not just searched) and the current upstream `master` (`01078ad15d4da06dffba0c5f15ffeaf9146a2a2a`, 2026-09-18) contain the exact same defect in `rtsp.c`:

- **`SETUP`** (starting a fresh AirPlay 2 session) builds a complete `timing_list_message` from iOS's `timingPeerInfo.Addresses` (every device in the group), but the line that sends it to NQPTP is commented out. Instead, `set_client_as_ptp_clock(conn)` runs, which sends NQPTP only the single RTSP client's IP — never the other group members.
- **`SETPEERS`** (the RTSP command iOS sends specifically when a device is *added to or removed from an already-playing group* — the exact "coupling with another loose AirPlay speaker" scenario) is a complete no-op upstream: the whole peer-forwarding implementation is commented out inside `handle_setpeers()`, which does nothing but reply `200 OK`.

`git log -L` on the disabling line traces it to commit `986f9587` (2023-09-09, "Rebuild the locking mechanisms for safe interruption of an existing play session"). It has been in this state, unfixed, for 3+ years, confirmed still present on upstream `master` as of 2026-09-18.

**Consequence**: NQPTP on the LampaStream side never learns the IP addresses of other real speakers in a group. It can only synchronize against whichever single IP happened to be registered as "the client" for the current RTSP session (usually the phone). Whether that's sufficient for correct grouping depends on transient session state — hence the intermittent, "not always" symptom, and it matches community reports (mikebrady/shairport-sync#1622) that joining an *already-playing* group is specifically more failure-prone than starting one fresh.

## Fix applied

A patch re-enabling the original (previously-written, never-finished) `handle_setpeers()` implementation, restoring peer-list forwarding to NQPTP. The patch is a minimal un-comment of code the upstream author already wrote and shipped compiling; it changes no logic beyond removing the disabling comment markers. Applied via `git apply` in `scripts/setup-airplay.sh` immediately after the pinned `shairport-sync` checkout, with an explicit `git apply --check` guard so a future commit-pin bump that no longer matches the patch fails the build loudly instead of silently dropping the fix.

Patch file: `scripts/patches/shairport-sync-0001-setpeers.patch`.

## What is NOT yet proven

This patch was written and verified for syntactic/structural correctness against the exact pinned source tree (types, variable names and helper functions all already exist and are used elsewhere in the same file). It has **not** been build-tested or verified against a real multi-speaker AirPlay 2 group yet — that requires a real build on the target LXC (`sudo ./scripts/install-lampastream.sh`) and a manual test: join LampaStream into a group that is already playing on another real AirPlay 2 speaker (the specific scenario that was failing), and confirm in `journalctl -u shairport-sync` that the `SETPEERS` debug line fires and that grouping now holds.

If this does not fully resolve the issue, the `SETUP`-path limitation (single client IP only, not full `timingPeerInfo`) is a second, smaller candidate worth revisiting — it was left as-is in this patch since `SETPEERS` is the mechanism that specifically governs joining a group already in progress.