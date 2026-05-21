from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def normalize_created_at(value: object) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except Exception:
            return ""

    if isinstance(value, str) and value.strip():
        raw = value.strip()
        iso_candidate = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return ""


def parse_iso_datetime(value: object) -> datetime | None:
    normalized = normalize_created_at(value)
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_relative_time_label(label: str, reference: datetime) -> datetime | None:
    normalized = (label or "").strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    patterns = [
        (r"(\d+)\s*s", 1),
        (r"(\d+)\s*m", 60),
        (r"(\d+)\s*h", 3600),
        (r"(\d+)\s*d", 86400),
        (r"(\d+)\s*w", 7 * 86400),
        (r"(\d+)\s*giây trước", 1),
        (r"(\d+)\s*phút trước", 60),
        (r"(\d+)\s*giờ trước", 3600),
        (r"(\d+)\s*ngày trước", 86400),
        (r"(\d+)\s*tuần trước", 7 * 86400),
        (r"(\d+)\s*tháng trước", 30 * 86400),
        (r"(\d+)\s*năm trước", 365 * 86400),
        (r"(\d+)\s*second(?:s)?\s*ago", 1),
        (r"(\d+)\s*minute(?:s)?\s*ago", 60),
        (r"(\d+)\s*hour(?:s)?\s*ago", 3600),
        (r"(\d+)\s*day(?:s)?\s*ago", 86400),
        (r"(\d+)\s*week(?:s)?\s*ago", 7 * 86400),
        (r"(\d+)\s*month(?:s)?\s*ago", 30 * 86400),
        (r"(\d+)\s*year(?:s)?\s*ago", 365 * 86400),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return reference - timedelta(seconds=int(match.group(1)) * multiplier)
    return None


def resolve_comment_created_at(value: object, label: str, crawled_at: str) -> str:
    normalized = normalize_created_at(value)
    if normalized:
        return normalized
    reference = parse_iso_datetime(crawled_at) or datetime.now(timezone.utc)
    relative_dt = parse_relative_time_label(label, reference)
    if relative_dt is not None:
        return relative_dt.isoformat()
    return reference.isoformat()


def normalize_rating(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def compact_whitespace(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
