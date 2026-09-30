"""Conservative receiver configuration inspection; no service or FIFO access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DELIVERY_MARGIN_MS = 500
SHAIRPORT_REVISION = "0b1c4391ffd398e7b145eb4b98416261380adeea"


def visible_config(text: str) -> str:
    return re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|\#[^\n]*',
        lambda m: m[0] if m[0].startswith('"') else " " * len(m[0]),
        text,
    )


def general_section(text: str):
    sections = list(re.finditer(r"\bgeneral\s*=\s*\{([^{}]*)\}", visible_config(text)))
    if len(sections) != 1:
        raise ValueError("Expected one simple general section")
    return sections[0]


def delivery_margin(text: str, manifest: dict) -> int | None:
    """A margin is known only when installed provenance and actual settings agree."""
    try:
        if (
            manifest.get("airplay_delivery_margin_ms") != DELIVERY_MARGIN_MS
            or manifest.get("shairport_revision") != SHAIRPORT_REVISION
        ):
            return None
        body = general_section(text)[1]
        for key, expected in (
            ("audio_backend_latency_offset_in_seconds", -DELIVERY_MARGIN_MS / 1000),
            ("audio_backend_buffer_desired_length_in_seconds", 0.0),
            ("audio_backend_buffer_interpolation_threshold_in_seconds", 0.0),
        ):
            settings = re.findall(r"\b" + key + r"\s*=\s*([-+]?\d+(?:\.\d+)?)\s*;", body)
            if len(settings) != 1 or body.count(key) != 1 or float(settings[0]) != expected:
                return None
        # The deprecated settings can change effective values before the new settings.
        # Refuse ambiguity rather than claiming a timing contract we have not checked.
        if re.search(r"\baudio_backend_(?:latency_offset|buffer_desired_length)\s*=", body):
            return None
        return DELIVERY_MARGIN_MS
    except (ValueError, TypeError):
        return None


def installed_delivery_margin(config: Path) -> int | None:
    try:
        manifest = json.loads((Path(sys.prefix).resolve().parent / "installation.json").read_text())
        return delivery_margin(config.read_text(), manifest)
    except (OSError, ValueError, TypeError):
        return None


def rename_receiver(text: str, name: str) -> str:
    section = general_section(text)
    settings = list(re.finditer(r'\bname\s*=\s*"(?:\\.|[^"\\])*"\s*;', section[1]))
    if len(settings) != 1:
        raise ValueError("Expected one receiver name in general")
    start, end = (section.start(1) + n for n in settings[0].span())
    return text[:start] + f"name = {json.dumps(name)};" + text[end:]
