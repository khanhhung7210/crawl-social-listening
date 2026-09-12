"""Facebook UI datetime label parsing — day-first EN must not become prior year."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_listening.crawl_freshness import attach_freshness_fields, load_freshness_policy
from social_listening.review_utils import parse_facebook_datetime_label

VN = ZoneInfo("Asia/Ho_Chi_Minh")
REF = datetime(2026, 9, 12, 11, 0, tzinfo=VN)


def test_day_first_english_with_weekday_and_year():
    """Regression: popcorn complaint label was misread as 2025-09-20."""
    parsed = parse_facebook_datetime_label(
        "Saturday 12 September 2026 at 10:09",
        reference=REF,
    )
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 9
    assert parsed.day == 12
    assert parsed.hour == 10
    assert parsed.minute == 9


def test_day_first_english_without_weekday():
    parsed = parse_facebook_datetime_label(
        "12 September 2026 at 10:09",
        reference=REF,
    )
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) == (
        2026,
        9,
        12,
        10,
        9,
    )


def test_month_first_english_still_works():
    parsed = parse_facebook_datetime_label(
        "September 12, 2026 at 10:09 AM",
        reference=REF,
    )
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) == (
        2026,
        9,
        12,
        10,
        9,
    )


def test_month_year_alone_does_not_invent_day_from_year_digits():
    """'September 2026' must not become day=20 via partial year match."""
    parsed = parse_facebook_datetime_label("September 2026", reference=REF)
    assert parsed is None


def test_vietnamese_absolute_still_works():
    parsed = parse_facebook_datetime_label("19 tháng 7 lúc 10:10", reference=REF)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) == (
        2026,
        7,
        19,
        10,
        10,
    )


def test_popcorn_complaint_is_fresh_coverage_not_stale():
    policy = load_freshness_policy("facebook")
    label = "Saturday 12 September 2026 at 10:09"
    local = parse_facebook_datetime_label(label, reference=REF)
    assert local is not None
    iso = local.replace(tzinfo=VN).astimezone(ZoneInfo("UTC")).isoformat()
    record = {
        "created_time": iso,
        "created_time_label": label,
        "message": "Galaxy Cinema bắp rang dở ói",
    }
    attach_freshness_fields(
        record,
        iso,
        policy,
        now=REF.astimezone(ZoneInfo("UTC")),
        newest_rank=1,
        in_final_limit=True,
    )
    assert record["freshness"] == "fresh"
    assert record["stale"] is False
    assert record["coverage"] is True
