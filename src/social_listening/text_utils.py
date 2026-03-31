from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    return normalize_text(keyword) in normalize_text(text)
