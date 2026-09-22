# AirPlay 2 grouping: SETPEERS timing-peer forwarding

Solo playback to LampaStream works reliably, but adding its virtual receiver to
an AirPlay 2 group already playing on a real speaker can fail intermittently.

The supplied deployment investigation ruled out LXC network topology and MAC
instability: the target has one non-loopback interface, bridged directly onto the
LAN without NAT, and a stable, statically configured MAC address. There is no
multi-interface ambiguity between shairport-sync, Avahi and NQPTP. These are
findings from the user's deployment investigation, not new deployment checks.

## Upstream defect and local patch

In shairport-sync's `rtsp.c`, `handle_setpeers()` logs the request and replies
`200 OK`, but its timing-peer forwarding implementation is entirely commented
out. SETPEERS updates peer membership when a receiver joins or leaves an
already-playing group. A successful RTSP response therefore does not mean that
the supplied peer addresses reached NQPTP.

The investigation traced the disabled block to upstream commit `986f9587`
(2023-09-09, "Rebuild the locking mechanisms for safe interruption of an existing
play session"). It found the same block in our pinned commit
`0b1c4391ffd398e7b145eb4b98416261380adeea` and upstream master
`01078ad15d4da06dffba0c5f15ffeaf9146a2a2a`, checked on 2026-09-18.

[`shairport-sync-0001-setpeers.patch`](../scripts/patches/shairport-sync-0001-setpeers.patch)
reactivates that original implementation: it builds a `T` timing-list message,
puts the RTSP client's address first, appends the supplied peer addresses and
forwards the list to NQPTP. The supplied patch also reformats the block and adds
an explanatory comment; it introduces no new forwarding algorithm.

`scripts/setup-airplay.sh` resolves the patch path before changing directories
and applies it immediately after the pinned shairport-sync checkout, before
`autoreconf`. A forward application check permits the initial application; a
reverse check recognises an already-patched tree. If neither check succeeds,
installation stops with an error. A future pin update requires checking the
patch again, not bypassing this guard. Neither upstream pin is changed.

The SETUP path's `set_client_as_ptp_clock()` behaviour is unchanged. Its use of
only the immediate client's IP remains a separate investigation candidate if
the SETPEERS patch does not fully resolve grouping.

## Verification still required on the target

Patch applicability and installer checks do not establish build compatibility or
successful multi-speaker synchronisation. No shairport-sync `configure` or
`make` is run in the development sandbox; the required development packages are
provisioned by the installer on the Debian 13 LXC target.

On that target, update the checkout containing this change and run:

```sh
sudo ./scripts/install-lampastream.sh
```

Then start playback on another real AirPlay 2 speaker and use iOS Control Center
to add LampaStream to that **already-playing group**. Confirm that the join works
and synchronisation holds, and inspect:

```sh
journalctl -u shairport-sync
```

Look for `Connection %d: SETPEERS` (with the connection number substituted).
It is logged at `debug(3)`, so `general.log_verbosity = 3` in shairport-sync's
configuration may be necessary, followed by a receiver restart. This log line
already existed before the patch: it proves receipt of SETPEERS, not by itself
successful peer forwarding or grouping. The real-speaker test is essential.
