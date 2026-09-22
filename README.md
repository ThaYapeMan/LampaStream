# LampaStream

> Formerly known as **HueSync**; renamed when the project outgrew Philips Hue.

Music-reactive Philips Hue Entertainment lighting from LMS, AirPlay 2 or Spotify Connect (backend Phase 1).
LampaStream analyzes live audio, produces generic audio features, and renders Effects
through a Hue Entertainment output driver. No microphone or precomputed BPM tags
are required.

## LampaStream domain model

LampaStream has two architectural levels: a **product/domain model** describing what
runs together, and an **audio-analysis subsystem** describing how audio becomes
features. The frozen canonical pipeline is a subsystem within the broader model.

### Six core entities

| Entity | Role |
|---|---|
| **VirtualPlayer** | The player/audio-source integration boundary. LMS/Squeezelite, AirPlay and Spotify Connect (backend only) are implemented. It holds source identity and connection settings, not Spectrum, Beat or Effects logic. |
| **Controller** | The physical lighting controller and its connection credentials. The current runtime output is Philips Hue Bridge; a Controller is separate from a Zone. |
| **Zone** | A logical group of lights controlled together, currently mapped to a Hue Entertainment Area on its Controller. Formerly **LightProvider**. |
| **Analyser** | Reusable analysis configuration: Spectrum engine selection, bands/cutoffs and onset algorithm/settings. It is source-independent. Formerly **AnalysisConfig**. |
| **EnergyProfile** | Selects high- and low-energy Effects and controls their blend thresholds and response smoothing. An empty low-energy selection uses the high-energy Effect. Formerly **Crossfader**. |
| **Effect** | A visual algorithm and its settings, consuming generic `AudioFeatures`. Current examples include `spectrum_rgb`, `wave` and `swirl`. |

Spectrum and Beat are independent processor families with separately configured
algorithms; families can coexist. This does not mean every family already has a
UI enable switch: Loudness and Chroma currently expose extension protocols only.
Effect settings also supply the current bass/mid feature boundaries to runtime
analysis; the six-entity model is a conceptual division, not a claim that every
analysis-related setting has already moved into Analyser.

### Coupling and runtime composition

**Coupling binds the configured entities into the session that actually runs.**
It stores four direct references: `player_id`, `analyser_id`, `zone_id` and
`energy_profile_id`. The Zone references its Controller through `controller_id`;
the EnergyProfile references its Effects through `high_energy_effect_id` and
`low_energy_effect_id`. Controller and Effect are therefore bound indirectly.

```text
LampaStream domain model
    ├── VirtualPlayer ───────────────────┐
    ├── Analyser ────────────────────────┤
    ├── Zone → Controller ───────────────┤
    └── EnergyProfile → Effect(s) ───────┤
                                        ▼
                                     Coupling
                                        ▼
                              Running LampaStream session
                                ├── player / ingress
                                ├── analysis
                                ├── energy blending
                                ├── effects
                                └── controller / zone output
```

The six core entities plus Coupling are persisted configuration objects. Activation
resolves their references and builds an internal runtime Profile; that Profile is
not an additional user-facing domain entity. Historical names above are migration
terminology, not current entity names. Current persisted collections use
`energy_profiles` and `effects`; historical data is converted once during installation,
with a backup and conflict checks. See [configuration](docs/configuration.md).

## Player-independent audio architecture

**LMS/Squeezelite, AirPlay and Spotify Connect are current integrations. None defines LampaStream's
architecture. The player-specific boundary ends at canonical audio ingress.**
Once audio has been canonicalised, downstream analysis and Effects do not need to
know which player supplied it.

### Player/source support in production code

“IMPLEMENTED” describes code presence, not completed target-LXC validation.

| Player / source | Status | Ingress | Uses canonical analysis | Notes |
|---|---|---|---|---|
| LMS / Squeezelite | IMPLEMENTED | Stereo shared memory from patched Squeezelite SHM v1 | Yes | Shared canonical PCM analysis. |
| AirPlay | IMPLEMENTED | shairport-sync → S16_LE stereo, 44.1 kHz named pipe → `AirPlayPipeStereoSource` | Yes, always | Same canonical pipeline factory and downstream Effects as LMS PCM. |
| Spotify | IMPLEMENTED (backend only) | go-librespot → S16_LE stereo, 44.1 kHz named pipe → `SpotifyPipeStereoSource` | Yes, always | Same canonical pipeline factory; creation UI and Now Playing wiring deferred to Phase 2. |
| Sonos (dedicated integration) | NOT PRESENT | — | — | Potential future adapter. A Sonos player exposed through a third-party LMS plugin can be followed through the LMS integration; this is not a native Sonos ingress. |
| Roon | NOT PRESENT | — | — | Potential future adapter; no production Roon player type or ingress. |

AirPlay and Spotify each use one managed global receiver, not an independent
receiver per configured VirtualPlayer: shairport-sync uses
`/run/lampastream/airplay.pcm`, and go-librespot uses
`/run/lampastream-spotify/spotify.pcm`. Each FIFO has exactly one reader.
LMS SHM continuity and receiver pipe framing/disconnect events belong to their
respective ingress adapters. All three routes retain stereo channels and use the
shared canonicalizer, including conversion to 48 kHz canonical PCM.

Spotify provisioning is owned by `scripts/install-lampastream.sh`, through
`scripts/setup-spotify.sh`; `scripts/uninstall-spotify.sh` removes only that receiver.
It pins [go-librespot v0.10.0](https://github.com/devgianlu/go-librespot/tree/v0.10.0)
(commit `57d7278d94a9233060c2a6238f5926ffd1e72de4`) and verifies the Linux x86_64
archive against its published SHA-256. It runs as the `lampastream` user, separately
from Python, and pairs through Zeroconf/Avahi only, with
`credentials.zeroconf.persist_credentials: false`. Its managed config is
`/etc/lampastream-spotify/config.yml`; `device_name` follows the active
VirtualPlayer's display name. Identical configuration does not restart the service.
`audio_backend: pipe`, `audio_output_pipe` and `audio_output_pipe_format: s16le`
select the FIFO contract. The pinned player fixes stereo at 44100 Hz; there is no
sample-rate setting. `external_volume: true` keeps analysis independent of the
Spotify volume control, and `audio_output_pipe_wait_for_reader: true` allows
pairing before a coupling opens its reader. The pipe writer is unpaced, so the
source bounds reads to 10 ms chunks and applies monotonic-clock backpressure.

Metadata uses read-only polling of `http://127.0.0.1:3678/status` every second
(`server.enabled/address/port`), with no additional dependency. The pinned
[REST specification](https://github.com/devgianlu/go-librespot/blob/v0.10.0/api-spec.yml)
returns 204 without a session; otherwise `track.name`, `track.artist_names`,
`track.position` and `track.duration` supply the snapshot (times in milliseconds).
`paused`, `stopped` and `buffering` control position interpolation. `track.uri`
and `track.album_name` exist upstream but the current TrackPosition contract has
no corresponding fields. The verified `/events` WebSocket provides `metadata`,
`seek`, `playing` and `paused` events in `{type, data}` messages; this integration deliberately polls REST.
API failures clear stale metadata and retry without stopping audio analysis.
Receiver installation, Spotify pairing/playback and Hue output on real hardware
remain user-run validation; local tests do not establish that deployment evidence.

### Internal analysis subsystem

```text
LMS / Squeezelite ─┐
AirPlay ───────────┤
Spotify Connect ──┤
future player ────┤
                  ▼
        player-specific ingress
                  ▼
             canonical PCM
                  ▼
     CanonicalAnalysisPipeline
                  ▼
        SharedAnalysisFrame
                  ▼
        AnalysisProcessor[]
          ├── SpectrumProcessor → SpectrumEngine → V2 / CAVA Core / future
          ├── BeatDetector      → BeatAlgorithm (onset implementation)
          ├── LoudnessAnalyzer  → K-weighted momentary / short-term LUFS
          └── ChromaAnalyzer    → extension protocol; future algorithm
                  ▼
         PublicationRecord
                  ▼
           AudioFeatures
                  ▼
               Effect
                  ▼
      Scene → controller / zone output
```

Canonicalization runs inside `CanonicalAnalysisPipeline`; the diagram shows the
logical audio boundary. The pipeline owns shared analysis, processor orchestration,
epoch/sample clocks, EOS/invalidation, publication and its worker lifecycle.
PlayerManager owns the physical source and session, retaining the source until
all readers terminate.

`SharedAnalysisFrame` carries canonical PCM, shared STFT magnitudes and sample
positions to the enabled processors. Processors may coexist; the current worker
dispatches them sequentially. `SpectrumProcessor` wraps a `SpectrumEngine`;
`BeatDetector` is independent of that engine. V2 and Beat reuse shared STFT work.
CAVA Core receives canonical stereo PCM and owns its own FFTs and conditioning.
K-weighted momentary/short-term Loudness runs alongside Spectrum and Beat;
Chroma remains a future extension. Loudness is displayed for comparison and does
not replace the existing Energy Profile blend input.

`PublicationRecord` binds features to their actual audio interval, epoch and
contributors. Delayed results remain in delivery-order publications; the live
`latest()` snapshot does not move backward in audio time. Effects consume generic
`AudioFeatures`, independently of the player or analysis implementation.
See [PCM/lifecycle/publication](docs/audio-pipeline.md) for the precise contract.

The analysis architecture is frozen: static registries/internal factories, with
no generic DSP DAG, dynamic plugin framework or node scheduler.

### Adding another player

A future player integration supplies decoded audio and source lifecycle/continuity
events through the canonical ingress contract. It owns its transport, framing,
channel layout and detection of gaps/restarts; uncertain continuity must invalidate
the old stream before new PCM enters its DSP epoch. The shared pipeline performs
canonicalization and downstream analysis.

Adding a player needs its adapter, player configuration/activation wiring and
integration tests. It does **not** require reimplementing Spectrum, Beat,
`PublicationRecord`, `AudioFeatures`, EnergyProfile, Effects or lighting output
when canonical PCM is supplied. Sonos, Roon and other players are potential
extensions behind this boundary, not promises of shipped support. Different
players may use different transports; no particular pipe, file or shared-memory
mechanism is required. Source-specific behavior must remain at ingress rather
than leaking into Effects. A deliberate derived-bars compatibility route remains
separate from this canonical contract.

## Spectrum engines

CAVA has two distinct integration paths:

```text
Canonical: VirtualPlayer / ingress → canonical PCM → SpectrumProcessor
                                                   → SpectrumEngine → CAVA Core
```

| Route | Selection | Analysis |
|---|---|---|
| LMS canonical PCM | `spectrum_backend=v2` or `cavacore` | Shared canonical pipeline: Spectrum + Beat; requires patched SHM v1 producer |
| AirPlay canonical PCM | `spectrum_backend=v2` or `cavacore` | Same shared canonical pipeline: Spectrum + Beat |

V2 uses the shared STFT. Embedded CAVA Core keeps upstream native DSP and its own
FFTs; LampaStream schedules 480-frame executions at 48 kHz (100 Hz).
LampaStream analysis no longer launches an external CAVA process. The external
CAVA binary remains available for independent stock consumers of squeezelite SHM;
its packaging and the producer ABI are unchanged.

An explicit embedded-engine request either activates that engine or fails; it never
silently selects V2. See [analyzers](docs/analyzers.md) and the
[frozen architecture](docs/ANALYSIS_ARCHITECTURE.md).

## Effects

Choose an Effect for each EnergyProfile layer; the same catalog works downstream
of LMS or AirPlay and either canonical Spectrum engine.

| Family | Current `effect_type` choices |
|---|---|
| Spectrum and energy | `spectrum_rgb`, `spectrum_rgb_spatial`, `mono_pulse` |
| Onset reactions | `pulses`, `flashes`, `splotches`, `fireworks` |
| Moving or steady color | `swirl`, `wave`, `solid` |
| Disabled layer | `none` |

See the [complete effects reference](docs/effects.md) for visual behavior, parameters,
feature inputs and current limitations. EnergyProfile blends high- and low-energy
Effects; spatial patterns use the Zone's light positions.

## Web UI

The web frontend in `web/` uses React and TypeScript, built with Vite, with
Tailwind CSS and Radix UI primitives in shadcn-style components. Vitest and
Testing Library cover unit/component tests; Playwright covers end-to-end tests.
See [package.json](web/package.json) for declared versions and
[testing](docs/testing.md#clean-ci-bootstrap) for the CI sequence.

Open **`http://<host>:8420`** after installation. The current UI provides:

- **Now Playing:** live color/bar/onset preview, blend and connection status.
- **Couplings:** configure entity bindings and activate/deactivate sessions.
- **Virtual Players / Zones:** configure LMS and AirPlay players, and select existing
  Controllers and Hue Entertainment Areas for Zones.
- **Analysers / Effects / Energy Profiles:** edit analysis settings, visual algorithms
  and high/low-energy blends.
- **Latency:** manage listening-player timing settings.
- **Backup and restore:** download or restore sensitive configuration with confirmation.

Controller creation/pairing is API-only. The Analyser page offers source, Spectrum
engine (V2/CAVA Core) and onset controls. Now Playing displays momentary loudness
beside Energy blend; Loudness has no configurable DSP settings. Chroma has no
shipped implementation or configuration UI. Use [API operations](docs/api.md) and
[configuration](docs/configuration.md) for these boundaries. There is no built-in
authentication; restrict UI/API access to a trusted network.

## Quick start

The repository installer is the authoritative standard deployment path.
Supported installer target: **Debian 13 / trixie, x86_64, with systemd**.

```sh
git clone https://github.com/ThaYapeMan/LampaStream.git
cd LampaStream
sudo ./scripts/install-lampastream.sh
```

The installer provisions dependencies, builds the patched Squeezelite producer and
AirPlay 2 receiver, builds the frontend/native wheel, migrates saved configuration,
verifies the installed artifacts, and starts the repository service. No manual
package installation, producer patching or JSON migration is part of that workflow.

Create/pair a Controller through the API, then open `http://<host>:8420` to configure
the Zone, player, Analyser, Effects/EnergyProfile and Coupling. Host audio-device passthrough remains an LXC
prerequisite for paced LMS playback; a guest script cannot provision host devices.
See [installation](docs/installation.md) and [LXC deployment](docs/deployment-lxc.md).
For read-only diagnosis, run `sudo ./scripts/install-lampastream.sh --check`.

## Validation status

**CODE-VERIFIED** means inspected code and reproducible local tests. It does not
mean the current binary has been deployed or timed on the target.

**REQUIRES LXC VALIDATION:** native CAVA/FFTW execution and leak stress, full target
Squeezelite link, live producer/SHM integration, clean wheel installation,
realtime backlog and visual V2/CAVA comparison. No such validation is claimed
by this documentation. Earlier benchmark/review documents are historical evidence
for their stated commits only.

## Documentation

- [Frozen architecture](docs/ANALYSIS_ARCHITECTURE.md)
- [PCM, lifecycle and publication](docs/audio-pipeline.md)
- [Analyzers and algorithms](docs/analyzers.md)
- [Configuration](docs/configuration.md) · [API operations](docs/api.md)
- [Installation](docs/installation.md) · [LXC deployment](docs/deployment-lxc.md)
- [Development](docs/development.md) · [Testing and acceptance](docs/testing.md)
- [Effects catalog](docs/effects.md) · [Effects and output boundaries](docs/EFFECT_ENGINE.md)
- [Squeezelite build and SHM ABI](squeezelite/README.md)

Historical prompts/specifications are labelled as historical or stored under
`docs/archive/`. They do not override these references. `docs/future/` contains
unimplemented proposals, not current capabilities.

## Backup and restore

Use **Backup and restore** in the UI to export all configured entities and player
latencies, including Hue Bridge `app_key` and `client_key`. Restoring preserves
pairing data, IDs and relationships; no configuration needs to be reconstructed.
Keep the JSON file secure: it contains controller credentials. LampaStream has no
built-in authentication; expose its UI/API only on a trusted network.

Restore accepts the current versioned backup format only. Deactivate the current
Coupling and complete teardown first. Import validates everything, saves an exact-byte
safety backup, and replaces configuration atomically. The application stays idle;
activate a restored Coupling when ready. No service restart is needed for UI/API restore.
CLI restore is offline and requires the service to be stopped.

See [configuration backup/restore](docs/configuration.md#backup-and-restore) for the
format, scope, API/CLI commands and failure policy, and [LXC recovery](docs/deployment-lxc.md#disaster-recovery).
