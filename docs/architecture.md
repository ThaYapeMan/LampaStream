# Player-independent audio architecture

Architecture decision, 2026-10-28 (ROUTE-01). This is the target contract;
implementation and measurement evidence are recorded in the code map and baseline.

### VirtualPlayers

A VirtualPlayer is the player/audio-source integration boundary. The LMS
VirtualPlayer is yeney-player, built from `third_party/yeney-core`: it joins LMS
as a virtual player synced with the listening room (a YeneY/Sonos room or another
LMS player), decodes the stream, and delivers stereo float PCM through yeney-core
SHM v1. The AirPlay VirtualPlayer is the managed shairport-sync receiver with its
early tap. Each VirtualPlayer delivers exactly two things: canonical PCM with
sample positions and epochs, and an AudibleClock mapping sample position to the
monotonic time that sample is heard, with its lookahead.

LampaStream must know which kind of player it synchronises lights to: YeneY/Sonos,
Squeezebox and AirPlay report audible time differently. That player-specific
knowledge lives in exactly one per-source AudibleClock in the player layer:
yeney-core play position plus the measured offset to the synced room, stored
per-player latency and YeneY's reported pipeline delay, or AirPlay tap play times.
Player-specific ingress owns transport and continuity; canonical ingress is the
boundary beyond which player identity is unavailable.

### Analyser

One source-independent analyser turns canonical PCM into generic AudioFeatures
and timestamped onset, beat and tempo events. After the canonical stage nothing
may know whether audio came from LMS or AirPlay: analysis, rendering, preview and
scheduling have no source- or route-specific code paths.

### Renderer

One renderer turns features at an audible time into a Scene: event view, effects,
layer mixing, accent/beat shaping, envelopes, preview snapshot and output boundary.
One scheduler decides when to send from audible time, lookahead and output
capabilities. Stateful components advance only on the render clock; sampling a
Scene at any time is pure. Transition completion is monotonic.

### Outputs

Hue Entertainment is the output today; WLED, LIFX, Nanoleaf and Art-Net/DMX can
follow. Each output declares OutputCapabilities: update rate, colour depth,
transport latency and minimum visible hold. It receives scenes; nothing upstream
knows its brand. Brand constants belong only in the driver.

```text
VirtualPlayer (canonical PCM + audible clock)
  -> one source-independent Analyser -> generic AudioFeatures
  -> one Renderer (event view, effect, mixer, accent, envelopes,
                   preview snapshot, output boundary)
  -> one scheduler -> output driver (via OutputCapabilities)
```

Every change is measured offline with the replay harness before deployment.
The render-loop grep tests enforce source independence; the output-agnostic test
enforces capability-based outputs. Equal-clock replay must produce byte-identical
sends for the same PCM.

### How to add a source

Implement a VirtualPlayer's player-specific ingress and AudibleClock, including
sample positions, epochs, continuity and lookahead. Select the clock from player
kind when creating the session. Reuse canonical ingress, the analyser, renderer,
preview and scheduler; validate with offline replay.

### How to add an output

Implement the output driver and declare its OutputCapabilities. Keep protocol and
brand constants inside the driver, reuse the renderer and scheduler, and measure
it offline before deployment.

See the [code map](code-map.md) and [testing contract](testing.md).
