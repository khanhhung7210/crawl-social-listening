from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    return normalize_text(keyword) in normalize_text(text)


def parse_compact_count(value: object) -> int | None:
    """Parse engagement counts like 113, 1,367, 1.2K, 10.7K, 1.5M, 1.229.143."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value) if value >= 0 else None

    raw = str(value).strip()
    if not raw:
        return None

    # Strip common wrappers from UI labels: "1.2K likes" → take leading compact token
    m = re.match(r"^\s*([\d.,]+)\s*([KkMmBb])?\b", raw)
    if not m:
        return None
    number_part = m.group(1)
    suffix = (m.group(2) or "").upper()

    # EU / VN thousand separators: 1.229.143 or 1,229,143
    if number_part.count(".") > 1:
        number_part = number_part.replace(".", "")
    elif number_part.count(",") > 1:
        number_part = number_part.replace(",", "")
    elif "," in number_part and "." in number_part:
        # 1,367.5 → drop decimal if present after comma-thousands
        if number_part.rfind(".") > number_part.rfind(","):
            number_part = number_part.replace(",", "")
        else:
            number_part = number_part.replace(".", "").replace(",", ".")
    elif "," in number_part:
        # 1,367 → thousands; 1,5 → decimal (rare for counts)
        parts = number_part.split(",")
        number_part = "".join(parts) if len(parts[-1]) == 3 else number_part.replace(",", ".")

    try:
        base = float(number_part)
    except ValueError:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if not digits:
            return None
        base = float(digits)

    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(round(base * mult))
