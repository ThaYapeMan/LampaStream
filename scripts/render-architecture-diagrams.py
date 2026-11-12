#!/usr/bin/env python3
"""Render the architecture diagrams under docs/diagrams/ from one source of truth.

Run from the repository root: ``python scripts/render-architecture-diagrams.py``.
The SVGs use explicit colours (no host CSS) so GitHub renders them as committed.
Box titles are 14 px, subtitles 12 px; keep subtitles to five words.
"""

import argparse
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
C = {
    "teal": ("#E1F5EE", "#0F6E56", "#085041", "#0F6E56"),
    "purple": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7"),
    "gray": ("#F1EFE8", "#5F5E5A", "#444441", "#5F5E5A"),
}
F = 'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif"'
HEAD = (
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
    'markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" '
    'stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" '
    'stroke-linejoin="round"/></marker></defs>'
)


def box(x, y, w, h, title, sub, ramp):
    fill, stroke, t1, t2 = C[ramp]
    out = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="0.75"/>'
    )
    if sub:
        out += (
            f'<text x="{x + w / 2}" y="{y + h / 2 - 9}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="14" font-weight="500" '
            f'fill="{t1}" {F}>{title}</text>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + 11}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="12" fill="{t2}" {F}>{sub}</text>'
        )
    else:
        out += (
            f'<text x="{x + w / 2}" y="{y + h / 2}" text-anchor="middle" '
            'dominant-baseline="central" '
            f'font-size="14" font-weight="500" '
            f'fill="{t1}" {F}>{title}</text>'
        )
    return out


def arrow(d, dash=False, color="#888780"):
    da = ' stroke-dasharray="5 4"' if dash else ""
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{da} '
        'marker-end="url(#arrow)"/>'
    )


def label(x, y, text, anchor="start"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="12" '
        f'fill="#5F5E5A" {F}>{text}</text>'
    )


def dashed(x, y, w, h, text):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" stroke="#B4B2A9" '
        f'stroke-width="0.75" stroke-dasharray="4 4"/>'
        f'<text x="{x + w / 2}" y="{y + 14}" text-anchor="middle" '
        'dominant-baseline="central" '
        f'font-size="12" fill="#5F5E5A" {F}>{text}</text>'
    )


def svg(h, title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{h}" viewBox="0 0 680 {h}" '
        f'role="img"><title>{title}</title><rect width="680" height="{h}" fill="#FFFFFF"/>'
        f"{HEAD}{body}</svg>"
    )


def end_to_end():
    b = box(40, 40, 120, 56, "VirtualPlayer", "LMS, AirPlay, …", "gray")
    b += box(190, 40, 140, 56, "Canonical PCM", "48 kHz stereo + clock", "teal")
    b += box(360, 40, 150, 56, "CanonicalAnalysis", "Pipeline, processors", "teal")
    b += box(540, 40, 100, 56, "Audio", "Features", "purple")
    b += arrow("M160 68 L188 68") + arrow("M330 68 L358 68") + arrow("M510 68 L538 68")
    b += box(540, 160, 100, 56, "Renderer", "Effects → Scene", "purple") + arrow("M590 96 L590 158")
    b += box(360, 160, 150, 56, "Scheduler", "audible time, lookahead", "purple") + arrow(
        "M540 188 L512 188"
    )
    b += box(190, 160, 140, 56, "Outputs", "by capability (Hue, …)", "gray") + arrow(
        "M360 188 L332 188"
    )
    b += box(40, 160, 120, 56, "Grid database", "priors, learned grids", "purple")
    b += arrow("M100 160 L100 120 L430 120 L430 98", dash=True, color="#7F77DD")
    b += label(340, 250, "Nothing after the canonical stage branches on source or output", "middle")
    return svg(280, "LampaStream end-to-end flow", b)


def beat_source_decision():
    b = box(250, 30, 180, 44, "1  AudioCanonicalizer", "", "teal") + arrow("M340 74 L340 100")
    b += box(250, 102, 180, 44, "2  Is the track known?", "", "gray")
    b += arrow("M250 124 L130 124 L130 186") + label(140, 150, "yes")
    b += arrow("M430 124 L520 124 L520 186") + label(500, 150, "no", "end")
    b += box(40, 188, 180, 56, "3  Learned grid", "from the grid database", "purple")
    b += box(430, 188, 180, 56, "3  Whole track ahead?", "capability, not source", "gray")
    b += arrow("M430 216 L340 216 L340 290") + label(350, 262, "yes (file)")
    b += arrow("M520 244 L520 290") + label(530, 268, "no (stream)")
    b += box(250, 292, 180, 56, "4  File grid", "whole file analysed", "purple")
    b += box(
        440, 292, 200, 56, "4  Live tracker + rolling grid", "on received audio, X s", "purple"
    )
    b += box(
        40,
        400,
        600,
        56,
        "Always: live analysis measures and corrects",
        "Contradiction check, watchdog, owner corrections",
        "teal",
    )
    b += arrow("M130 244 L130 398") + arrow("M340 348 L340 398") + arrow("M540 348 L540 398")
    return svg(500, "Beat source decision after the canonical stage", b)


def analysis_target():
    b = box(40, 60, 130, 56, "VirtualPlayer", "live stream PCM", "gray")
    b += box(40, 260, 130, 56, "Library file", "LMS download", "gray")
    b += box(210, 160, 140, 56, "AudioCanonicalizer", "48 kHz stereo, soxr", "teal")
    b += arrow("M170 88 L190 88 L190 188 L208 188")
    b += '<path d="M170 288 L190 288 L190 188" fill="none" stroke="#888780" stroke-width="1.5"/>'
    b += box(390, 160, 140, 56, "One attack detector", "per channel, shared", "teal") + arrow(
        "M350 188 L388 188"
    )
    b += box(390, 60, 140, 56, "Live analysis", "BeatDetector, tracker", "teal") + arrow(
        "M460 160 L460 118"
    )
    b += dashed(380, 240, 160, 96, "bounded subprocess")
    b += box(390, 268, 140, 56, "Grid analyser", "whole file or head", "teal") + arrow(
        "M460 216 L460 238"
    )
    b += box(570, 60, 70, 56, "Beat", "Fusion", "purple") + arrow("M530 88 L568 88")
    b += box(570, 268, 70, 56, "Grid", "database", "purple") + arrow("M530 296 L568 296")
    b += arrow("M605 268 L605 118", dash=True, color="#7F77DD")
    b += label(
        340,
        380,
        "One ingress, one detector; only the beat-position engine differs "
        "(live tracker / offline tracker)",
        "middle",
    )
    return svg(
        420,
        "Target analysis architecture: file and stream share the canonicalizer and the detector",
        b,
    )


DIAGRAMS = {
    "end-to-end.svg": end_to_end,
    "beat-source-decision.svg": beat_source_decision,
    "analysis-target.svg": analysis_target,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in DIAGRAMS.items():
        (args.output_dir / name).write_text(fn(), encoding="utf-8")
        print("wrote", args.output_dir / name)
