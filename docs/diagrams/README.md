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
