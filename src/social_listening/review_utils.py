from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def _vn_tz() -> ZoneInfo:
    return ZoneInfo("Asia/Ho_Chi_Minh")


def __getattr__(name: str):
    if name == "VN_TZ":
        return _vn_tz()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

_RELATIVE_ONLY_RE = re.compile(r"(?i)^\d+[smhdw]$")


def is_relative_only_time_label(value: object) -> bool:
    text = str(value or "").strip().casefold().replace(" ", "")
    return bool(_RELATIVE_ONLY_RE.fullmatch(text))


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
    normalized = re.sub(
        r"^(thời gian chỉnh sửa|edited(?:\s+on)?|chỉnh sửa)\s*:?\s*",
        "",
        normalized,
    )
    # Maps VI uses "một tháng trước"; EN uses "a month ago"
    normalized = re.sub(r"\b(một|mot|an|a)\b", "1", normalized)
    # Longer units first so "2 tháng" is not eaten by compact "2 m"/"2 h"
    patterns = [
        (r"(\d+)\s*năm trước", 365 * 86400),
        (r"(\d+)\s*tháng trước", 30 * 86400),
        (r"(\d+)\s*tuần trước", 7 * 86400),
        (r"(\d+)\s*ngày trước", 86400),
        (r"(\d+)\s*giờ trước", 3600),
        (r"(\d+)\s*phút trước", 60),
        (r"(\d+)\s*giây trước", 1),
        (r"(\d+)\s*years?\s*ago", 365 * 86400),
        (r"(\d+)\s*months?\s*ago", 30 * 86400),
        (r"(\d+)\s*weeks?\s*ago", 7 * 86400),
        (r"(\d+)\s*days?\s*ago", 86400),
        (r"(\d+)\s*hours?\s*ago", 3600),
        (r"(\d+)\s*minutes?\s*ago", 60),
        (r"(\d+)\s*seconds?\s*ago", 1),
        (r"(\d+)\s*w\b", 7 * 86400),
        (r"(\d+)\s*d\b", 86400),
        (r"(\d+)\s*h\b", 3600),
        (r"(\d+)\s*m\b", 60),
        (r"(\d+)\s*s\b", 1),
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


# Google Maps DOM often leaks chrome (menu, search, drag handles) into text nodes.
_MAPS_UI_JUNK_RE = re.compile(
    r"(?i)drag to change|click to remove|"
    r"messages\s+activity\s+profile"
)
_MAPS_CHROME_MENU_RE = re.compile(
    r"(?i)(?:drag to change|click to remove).{0,40}(?:back|search|close|restaurants|hotels)"
)
_MAPS_ICON_RE = re.compile(r"[\ue000-\uf8ff]")
_MAPS_AUTHOR_PREFIX_RE = re.compile(
    r"(?i)^(?:local\s+guide\s*[·•]?\s*)?(?:\d[\d,]*\s+reviews?\s*[·•]?\s*)?"
    r"(?:\d[\d,]*\s+photos?\s*)?"
)
_MAPS_TIME_SPLIT_RE = re.compile(
    r"(?i)(?:(?:\d+|a|an)\s*(?:second|minute|hour|day|week|month|year)s?\s*ago|"
    r"(?:\d+|một)\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm)\s*trước)\s*"
)
_MAPS_TAIL_RE = re.compile(
    r"(?i)\s*(?:…\s*)?more(?:\d[:\d+]*)?(?:\s*[+\d]*)?(?:\s*like)?(?:\s*\d*)?(?:\s*share)?.*$"
)


def is_google_maps_ui_junk(value: object) -> bool:
    text = compact_whitespace(value)
    if not text:
        return True
    if _MAPS_UI_JUNK_RE.search(text) or _MAPS_CHROME_MENU_RE.search(text):
        return True
    if " - Google Maps |" in text and (
        "Drag to change" in text or "click to remove" in text.lower() or "Search" in text
    ):
        return True
    # Mostly icons / chrome with almost no letters
    letters = sum(1 for ch in text if ch.isalpha())
    return letters < 12 and len(text) > 40


def clean_google_maps_place_title(value: object) -> str:
    title = compact_whitespace(value)
    title = re.sub(r"(?i)\s*-\s*Google Maps\s*$", "", title).strip()
    if is_google_maps_ui_junk(title):
        return ""
    return title


def clean_google_maps_author(value: object) -> str:
    author = _MAPS_ICON_RE.sub("", compact_whitespace(value))
    author = re.split(r"(?i)local\s+guide", author, maxsplit=1)[0]
    author = re.split(r"(?i)\d+\s+reviews?", author, maxsplit=1)[0]
    return compact_whitespace(author)


def clean_google_maps_review_text(value: object) -> str:
    """Strip Maps chrome / duplicated card text so Hot News shows the real review."""
    text = _MAPS_ICON_RE.sub(" ", compact_whitespace(value))
    if not text or is_google_maps_ui_junk(text):
        return ""

    # Prefer the body after the relative-time label.
    parts = _MAPS_TIME_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2 and len(parts[1].strip()) >= 12:
        text = parts[1].strip()
    else:
        text = _MAPS_AUTHOR_PREFIX_RE.sub("", text).strip()

    text = _MAPS_TAIL_RE.sub("", text).strip()
    # Drop duplicated second copy of the same review card.
    for sep in (" Like ", " Share ", "Like", " Share"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()

    text = re.sub(r"(?i)\s*(translated by google|đã dịch bằng google)\s*", " ", text)
    text = re.sub(r"(?i)\s*(see original|xem bản gốc)\s*", " ", text)
    text = compact_whitespace(text)
    if is_google_maps_ui_junk(text) or len(text) < 12:
        return ""
    return text


_EN_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_EN_MONTH_ALT = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_EN_WEEKDAY_ALT = (
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|"
    r"sat(?:urday)?|sun(?:day)?"
)


def _facebook_en_clock(hour: int, minute: int, ampm: str) -> tuple[int, int]:
    ampm = (ampm or "").upper()
    if ampm == "PM" and hour < 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour, minute


def _facebook_local_naive(
    *,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    vn: ZoneInfo,
    ref: datetime,
    year_explicit: bool,
) -> datetime | None:
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=vn)
    except ValueError:
        return None
    # Only roll back implied year when FB omits it and clock would be in the future.
    if not year_explicit and dt > ref + timedelta(hours=2):
        dt = dt.replace(year=year - 1)
    return dt.replace(tzinfo=None)


def parse_facebook_datetime_label(value: object, *, reference: datetime | None = None) -> datetime | None:
    """Parse Facebook UI timestamps like ``19 tháng 7 lúc 10:10`` or ``8 giờ trước``."""
    text = compact_whitespace(value)
    if not text:
        return None

    vn = _vn_tz()
    ref = reference or datetime.now(vn)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=vn)
    else:
        ref = ref.astimezone(vn)

    relative = parse_relative_time_label(text, ref.astimezone(timezone.utc))
    if relative is not None:
        return relative.astimezone(vn).replace(tzinfo=None)

    # 19 tháng 7 lúc 10:10  |  19 thg 7, 2025 lúc 10:10
    m = re.search(
        r"(?i)(\d{1,2})\s*(?:tháng|thg)\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?"
        r"(?:\s+lúc\s+(\d{1,2}):(\d{2}))?",
        text,
    )
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year_explicit = bool(m.group(3))
        year = int(m.group(3)) if year_explicit else ref.year
        hour = int(m.group(4) or 0)
        minute = int(m.group(5) or 0)
        parsed = _facebook_local_naive(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            vn=vn,
            ref=ref,
            year_explicit=year_explicit,
        )
        if parsed is not None:
            return parsed

    # Day-first EN: "Saturday 12 September 2026 at 10:09" / "12 September 2026 at 10:09"
    # Must run before month-first — otherwise "September 2026" eats day=20 from the year.
    m = re.search(
        rf"(?i)(?:(?:{_EN_WEEKDAY_ALT})\s+)?(\d{{1,2}})\s+({_EN_MONTH_ALT})"
        r"(?:\s*,?\s*(\d{4}))?(?:\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
        text,
    )
    if m:
        month = _EN_MONTHS.get(m.group(2).casefold(), 0)
        if month:
            day = int(m.group(1))
            year_explicit = bool(m.group(3))
            year = int(m.group(3)) if year_explicit else ref.year
            hour, minute = _facebook_en_clock(int(m.group(4) or 0), int(m.group(5) or 0), m.group(6) or "")
            parsed = _facebook_local_naive(
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                vn=vn,
                ref=ref,
                year_explicit=year_explicit,
            )
            if parsed is not None:
                return parsed

    # Month-first EN: "July 19 at 10:10 AM" / "September 12, 2026 at 10:09 AM"
    # (?!\d) stops "September 2026" from matching day=20 out of the year.
    m = re.search(
        rf"(?i)({_EN_MONTH_ALT})\s+(\d{{1,2}})(?!\d)(?:,?\s+(\d{{4}}))?"
        r"(?:\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
        text,
    )
    if m:
        month = _EN_MONTHS.get(m.group(1).casefold(), 0)
        if month:
            day = int(m.group(2))
            year_explicit = bool(m.group(3))
            year = int(m.group(3)) if year_explicit else ref.year
            hour, minute = _facebook_en_clock(int(m.group(4) or 0), int(m.group(5) or 0), m.group(6) or "")
            parsed = _facebook_local_naive(
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                vn=vn,
                ref=ref,
                year_explicit=year_explicit,
            )
            if parsed is not None:
                return parsed

    return None


def parse_media_date_label(value: object, *, reference: datetime | None = None) -> datetime | None:
    """Parse common social UI labels (FB/YouTube/IG/Threads): relative + absolute."""
    text = compact_whitespace(value)
    if not text:
        return None

    fb = parse_facebook_datetime_label(text, reference=reference)
    if fb is not None:
        return fb

    vn = _vn_tz()
    ref = reference or datetime.now(vn)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=vn)
    else:
        ref = ref.astimezone(vn)

    for fmt in (
        "%b %d, %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=vn).replace(tzinfo=None)
        except ValueError:
            continue
    return None
