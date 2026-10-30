# Draft upstream PR: establish classic RAOP without accidental HAP negotiation

Base: pyatv v0.18.0. Tested fork commit:
`917cef27e7df8b962557ff77201b49fc2a4b1a37`.
This is draft text; no upstream PR or message has been published.

## Problem and resulting behavior

A hybrid AirPlay 2 / RAOP receiver can advertise transient HAP authentication
while accepting unencrypted classic audio (`et=0,1`, no password/PIN). pyatv
selected transient credentials even for a forced v1 session. Its verification
procedure completed transient pair-setup, which switched shairport-sync's reader
to encrypted framing, but the v1 setup called `verify_credentials()` directly,
without installing the negotiated connection encryption. The following plaintext
ANNOUNCE therefore never reached the receiver's RTSP parser. Separate DACP IDs
came from separate RtspSession wrappers over the same TCP connection; GET /info
alone did not switch the connection to encrypted framing.

For open hybrid receivers, classic initialization now drops the inferred
transient credentials and omits /info and pairing on the stream connection.
Receivers advertising a PIN/password, encryption-only requirements or explicit
persistent credentials keep authentication. Required verification uses
`verify_connection` on the ANNOUNCE connection so returned HAP keys activate its
framing. Legacy null-auth receivers retain optional /info support, including
initial-volume discovery. AirPlay 2 setup is unchanged.

The L16 SDP also incorrectly included ALAC-only fmtp parameters. shairport-sync
4.3.7 treated their presence as ALAC, overriding L16, misdecoded the PCM and
aborted during teardown. Removing that contradictory line makes the receiver
select uncompressed audio and complete teardown normally.

The fork also contains the preceding transient-authentication fixes: correct
RTSP start lines for pair-setup, and only requesting PIN presentation when the
receiver's /info statusFlags explicitly require it. Busy-receiver checking is
implemented in LampaStream tooling, not as a pyatv policy change.

## Validation

- Unmodified shairport-sync 4.3.7, AirPlay 2 build, pipe and metadata, nqptp 1.2.4
  (SMI 10), on the sender host. Receiver runs as codex on port 17000.
- Reproduced the old ANNOUNCE timeout with two successful transient setup rounds,
  no parsed ANNOUNCE, and zero PCM samples.
- Forced v1 streams a ten-second pulse using the actual LampaStream smoke wrapper;
  the receiver parses ANNOUNCE/SETUP/RECORD/TEARDOWN, selects uncompressed PCM,
  and the sole pipe reader verifies samples above dithering noise. Sender exits 0.
- RAOP and AirPlay protocol suites: 201 passed, 5 skipped. Added regressions cover
  PIN/password/encryption-only requirements, same-connection verification,
  legacy info support and absence of ALAC fmtp in L16 SDP.
