"""Normalize text and numeric fields for Source B (no invented metrics)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_UI_NOISE_RE = re.compile(
    r"^\s*(see more|view replies|pages you follow|xem thêm|xem phản hồi)\s*$",
    re.I,
)


def normalize_text(value: Any) -> str:
    """NFC whitespace cleanup; strip obvious UI chrome labels."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if _UI_NOISE_RE.match(text):
        return ""
    return text


def normalize_count(value: Any) -> int | None:
    """Keep None when missing; do not coerce missing → 0."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value else None  # NaN guard
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def pick_text(*candidates: Any) -> str:
    for raw in candidates:
        text = normalize_text(raw)
        if text:
            return text
    return ""
