"""Conservative receiver configuration inspection; no service or FIFO access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DELIVERY_MARGIN_MS = 0
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


def timing_settings(text: str) -> dict[str, float]:
    """Reject duplicate, malformed and deprecated settings before any edit."""
    body = general_section(text)[1]
    if re.search(r"\baudio_backend_(?:latency_offset|buffer_desired_length)\s*=", body):
        raise ValueError("Deprecated AirPlay timing setting")
    result = {}
    for key in LEGACY_TIMING:
        matches = re.findall(r"\b" + key + r"\s*=\s*([-+]?\d+(?:\.\d+)?)\s*;", body)
        if len(matches) > 1 or body.count(key) != len(matches):
            raise ValueError("Ambiguous AirPlay timing setting: " + key)
        if matches:
            result[key] = float(matches[0])
    return result


LEGACY_TIMING = {
    "audio_backend_latency_offset_in_seconds": -0.5,
    "audio_backend_buffer_desired_length_in_seconds": 0.0,
    "audio_backend_buffer_interpolation_threshold_in_seconds": 0.0,
}


def disable_early_delivery(text: str) -> str:
    settings = timing_settings(text)
    for key, value in settings.items():
        if (
            key == "audio_backend_latency_offset_in_seconds"
            and value < 0
            or key != "audio_backend_latency_offset_in_seconds"
            and value == 0
        ):
            section = general_section(text)
            match = re.search(r"\b" + key + r"\s*=\s*[-+]?\d+(?:\.\d+)?\s*;", section[1])
            start, end = (section.start(1) + n for n in match.span())
            text = text[:start] + text[end:]
    return text


def delivery_margin(text: str, manifest: dict) -> int | None:
    """Only receiver defaults have a proven margin; arbitrary offsets do not."""
    try:
        if manifest.get("shairport_revision") != SHAIRPORT_REVISION:
            return None
        settings = timing_settings(text)
        if (settings.get("audio_backend_latency_offset_in_seconds", 0) != 0
                or any(key != "audio_backend_latency_offset_in_seconds"
                       for key in settings)):
            return None
        return 0
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
