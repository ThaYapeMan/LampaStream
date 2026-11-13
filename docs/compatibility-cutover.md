# Current-schema cutover inventory

This document records the explicit migration boundary, not runtime alias support.
Classification: A current required feature; B historical documentation; C one-time
migration; D removed active compatibility debt; E intentional legacy feature.

| Location / concept | Class | Action / current contract |
|---|---|---|
| Models: historical Coupling reference names | C/D | Removed from from_dict; migration renames with conflict checks |
| Storage: historical EnergyProfile collection | C/D | Current `energy_profiles`; migration converts once |
| Storage: historical Effect collection | C/D | Current `effects`; migration converts once |
| Storage: old player/zone/analyser collection names | C/D | Only migration recognizes them |
| Models: historical Effect/color-mode names | C/D | No silent fallback; migration renames or fails |
| Models: old EnergyProfile blend/effect reference fields | C/D | Migration only |
| Models: old VirtualPlayer name | C/D | Migration retains it as display_name; conflicts fail |
| Models: Profile old names and unknown-key filtering | D | Removed; Profile is a current internal runtime copy |
| API: retired entity-name routes | D | Removed; current request schemas forbid unknown fields |
| WebSocket status / manager active_color_mode | D | Current field/property is effect_type / active_effect; frontend rebuilt |
| ColorMode / COLOUR_MODES two-effect selector | D | Unused enum/selector removed; current Effects registry remains |
| PublicationRecord.effective_engine_id | D/A | Name removed; required identity retained as effective_spectrum_backend |
| CAP._engine / CAP._onset_pipeline forwarding | D | Removed; owners are SpectrumProcessor and BeatDetector state |
| BeatDetector private forwarding properties | D | Removed; tests inspect coherent state directly |
| CAP unused pending-onset compatibility list | D | Removed; live interval/history publication behavior unchanged |
| V2/CAVA whole-pipeline compatibility wrappers | D | Removed; tests/production use CanonicalAnalysisPipeline |
| Unused old mono PcmAudioPipeline | D | Removed with tests solely for that superseded implementation |
| Unused mono AirPlayPipeSource | D | Removed; stereo production adapter and regressions retained |
| PcmSource / SqueezeliteShmSource / PcmStft / HPSS tap | E | Required by supported external CAVA/FIFO feature |
| SpectrumProcessor._engine | A | Real algorithm ownership, not an alias |
| SpectrumEngine.feed/flush and SharedAnalysis projection | A | Current common engine contract, including synchronous CAVA use |
| Profile / BridgeConfig / HueOutputConfig | A | Current runtime/output adapters with production callers |
| ColourModeEffect / AudioFeatures onset snapshots | A | Actual Effects/lighting path, not historical deserialization |
| Acceptance CSV effective_backend/effective_engine columns | A | Existing exported diagnostic format; values read current record identity |
| Historical offline comparison scripts and archived prompts | B | Evidence/tools for stated historical algorithms, not runtime architecture |

The 18 removed debt groups above do not remove the intentional external-FIFO mode.
Its separate producer keeps the upstream SHM layout expected by external CAVA;
canonical LMS requires the v1 producer. The installer builds both from one upstream
pin. No DSP, SHM v1, processor lifecycle or publication policy was redesigned.

## Migration safety

Schema version 5 is required by current runtime. Migration validates all known fields,
IDs and nonempty references before rewrite, backs up exact original bytes, and uses
atomic replacement. Equal aliases can be normalized; unequal aliases fail. Unknown
collections/fields and unsupported pre-entity data are not silently dropped. Runtime
must be stopped; the installer holds an exclusive installation lock. Repeated current
migration is a no-op. See [installation](installation.md#migration) for backup paths.

## Verification boundary

Local checks include migration failure/idempotency fixtures, current-schema rejection,
installer command/metadata tests, frontend build/tests, pinned producer patch/objects/
full link with extracted Debian libraries, and wheel/native smoke execution. These do
not prove a fresh booted Debian LXC install, service permissions, host ALSA passthrough,
AirPlay timing, or realtime behavior. Those remain target acceptance tasks.


## Grid cache cutover

Grid persistence has its own SQLite `user_version=1`, independent of configuration
schema 5. The installer stops the runtime, then runs
`python -I -B -m lampastream.grid.migration /var/lib/lampastream/grids /var/lib/lampastream/grids.db`.
It archives exact JSON bytes in `grids.pre-sqlite.<digest>.tar`, imports into a
separate database, checks that the input did not change, and atomically publishes
it. Repeating a completed cutover is a schema-checked no-op. Malformed input leaves
the original JSON and backup intact, without publishing a database.

Analyser/schema version 4 adds canonical audio fingerprints and the section/bar
metadata fields. Older analyser grids remain superseded and are re-analysed on
next access. Historical JSON remains archival and is never a runtime fallback.
The daily `lampastream-grids-maintenance.timer` checks whether a weekly vacuum is
due. LRU evicts current grid entries and their aliases; superseded grids and
provider records are retained. SQLite online backup is available through
`python -m lampastream.grid.database backup --destination /secure/grids.db`.
The Backup UI now exports a ZIP containing both current configuration and the
SQLite snapshot, and accepts either a full ZIP or a current-schema configuration
JSON. Full CLI export/import uses `python -m lampastream.backup_archive`; import
requires the existing offline configuration lease. Whole-file grid restore uses
the stable `grids.db.lock`; a durable `config.json.restore-pending.json` journal
resolves interruptions before Storage reads configuration. No historical entity
schema conversion or audio persistence is added to runtime.


`last_used` is an opaque increasing LRU sequence, not a listening timestamp.
Restore coordination uses a private `grids.db.restore-pending` marker alongside
the stable lock. Maintenance cannot modify a pending snapshot before recovery;
an orphan marker after journal cleanup is completed on the next Storage read.
Neither operational file is included in the portable archive or grid records.
