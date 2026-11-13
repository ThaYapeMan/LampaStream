# Architecture diagrams

The single source of truth is `../../scripts/render-architecture-diagrams.py`.
Regenerate from the repository root with
`python scripts/render-architecture-diagrams.py`; never hand-edit an SVG.
Commit the script and its regenerated output together. To render elsewhere, use
`--output-dir /path/to/output`.

- `end-to-end.svg` shows sources, the canonical boundary, analysis, generic
  AudioFeatures, rendering, scheduling and capability-based outputs, with grid priors.
- `beat-source-decision.svg` shows capability-based selection of a learned grid,
  full-file grid or live tracker with a rolling grid, and ongoing live checks.
- `analysis-target.svg` shows the target shared AudioCanonicalizer and attack
  detector for live and grid analysis. GRID-01 send-back 5 and BEAT-02 part A
  implement this target where it is not yet present in code.

The style is 680 px wide, with 14 px titles and 12 px subtitles of at most five
words. Teal means canonical/analysis; purple means features/grid/render; grey
means sources and outputs. Dashed purple arrows mean prior/feedback. SVG colours
are explicit so the images render on GitHub without host CSS.

A ticket that changes a boundary regenerates the matching diagram and updates
its adjacent prose in README.md, docs/ANALYSIS_ARCHITECTURE.md and, where relevant,
docs/audio-pipeline.md. The existing ASCII internal analysis diagram is retained.

- `track-identity.svg` is the leading BEAT-02 decision tree. Metadata supplies
  an early hint; fingerprint and duration establish identity. Byte hashes only
  avoid re-analysis of identical file bytes. The simplified capability view
  remains available in `beat-source-decision.svg`.
- `stream-buffer.svg` describes the target stream buffer ownership: one track
  in RAM with identity, or a ten-minute sliding window without identity. Rolling
  and learned stream execution are not implemented by the storage cutover alone.

A learned metadata hint requires artist, title and duration within one second.
It remains provisional until audio fingerprint confirmation; unsupported accents
stay dark. A later fingerprint confirms or overrides that hint. The decision
is recorded separately from metadata identity. Anonymous streams use the sliding
window and rolling analysis, with no stored grids or provider lookups.
