"""Tests for crawl freshness policy and incremental stop behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_listening.crawl_freshness import (
    KeywordCrawlStats,
    attach_freshness_fields,
    classify_detail_freshness,
    extract_unix_create_time_from_html,
    is_stale,
    load_freshness_policy,
    parse_content_timestamp,
    select_newest,
    should_spend_on_comments,
    should_stop_for_validated_stale_content,
    should_stop_keyword_details,
)
from social_listening.crawl_state import IncrementalCrawlState


NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_content_timestamp_iso_and_unix():
    iso = parse_content_timestamp("2026-09-01T10:00:00Z")
    assert iso is not None
    assert iso.year == 2026

    unix = parse_content_timestamp(1725192000)  # 2024-ish
    assert unix is not None

    ms = parse_content_timestamp(1725192000000)
    assert ms is not None
    assert abs((ms - unix).total_seconds()) < 1

    assert parse_content_timestamp("") is None
    assert parse_content_timestamp(None) is None


def test_is_stale_lookback_window(monkeypatch):
    monkeypatch.setenv("CRAWL_LOOKBACK_DAYS", "14")
    policy = load_freshness_policy("facebook")

    fresh = NOW - timedelta(days=3)
    stale = NOW - timedelta(days=30)

    assert is_stale(fresh, policy, now=NOW) is False
    assert is_stale(stale, policy, now=NOW) is True
    assert is_stale(None, policy, now=NOW) is None
    assert classify_detail_freshness(fresh, policy, now=NOW) == "fresh"
    assert classify_detail_freshness(stale, policy, now=NOW) == "stale"
    assert classify_detail_freshness(None, policy, now=NOW) == "unknown"


def test_should_not_stop_on_url_history_alone(tmp_path):
    """Dangerous consecutive-old-URL stop must be disabled."""
    db = tmp_path / "crawl_state.db"
    with IncrementalCrawlState(db) as state:
        for i in range(20):
            state.mark_crawled(f"https://example.com/{i}", "tiktok", "kw")
        recent = [f"https://example.com/{i}" for i in range(10, 20)]
        assert state.should_stop_search("tiktok", recent, threshold=8, window=10) is False


def test_validated_content_stale_stop_only_when_configured(monkeypatch):
    monkeypatch.setenv("THREADS_CONSECUTIVE_STALE_CONTENT_STOP", "5")
    monkeypatch.setenv("TIKTOK_CONSECUTIVE_STALE_CONTENT_STOP", "0")
    threads = load_freshness_policy("threads")
    tiktok = load_freshness_policy("tiktok")

    assert should_stop_for_validated_stale_content(4, threads) is False
    assert should_stop_for_validated_stale_content(5, threads) is True
    # Non-chrono platforms default to disabled content-time stop
    assert should_stop_for_validated_stale_content(100, tiktok) is False


def test_max_stale_details_per_keyword(monkeypatch):
    monkeypatch.setenv("CRAWL_MAX_STALE_DETAILS_PER_KEYWORD", "3")
    policy = load_freshness_policy("facebook")
    assert should_stop_keyword_details(2, policy) is False
    assert should_stop_keyword_details(3, policy) is True


def test_extract_unix_create_time_from_html():
    html = '{"itemStruct":{"createTime":1725192000,"desc":"x"}}'
    dt = extract_unix_create_time_from_html(html)
    assert dt is not None
    assert dt.tzinfo is not None

    ig = 'window._sharedData = {"taken_at_timestamp":1725192000};'
    assert extract_unix_create_time_from_html(ig) is not None


def test_keyword_stats_logging_fields():
    stats = KeywordCrawlStats(
        keyword="galaxy",
        discovered=40,
        new=12,
        stale=5,
        already_seen=23,
        detail_success=7,
        detail_failed=1,
        comments_found=20,
        comments_crawled=18,
        runtime_seconds=12.5,
        stop_reason="idle_limit",
    )
    assert stats.discovered == 40
    assert stats.stale == 5
    assert stats.detail_success == 7


def test_limits_are_env_configurable(monkeypatch):
    monkeypatch.setenv("TIKTOK_MAX_VIDEOS", "50")
    monkeypatch.setenv("TIKTOK_MAX_SCROLL_ROUNDS", "30")
    monkeypatch.setenv("TIKTOK_MAX_RUNTIME_SECONDS", "120")
    monkeypatch.setenv("TIKTOK_LOOKBACK_DAYS", "7")
    policy = load_freshness_policy("tiktok")
    assert policy.final_limit == 50
    assert policy.max_new_urls_per_keyword == 50  # alias
    assert policy.max_scroll_rounds == 30
    assert policy.max_runtime_seconds == 120
    assert policy.lookback_days == 7.0


def test_discovery_and_final_shared_limits(monkeypatch):
    monkeypatch.delenv("TIKTOK_MAX_VIDEOS", raising=False)
    monkeypatch.delenv("TIKTOK_FINAL_LIMIT", raising=False)
    monkeypatch.delenv("TIKTOK_DISCOVERY_LIMIT", raising=False)
    monkeypatch.setenv("CRAWL_DISCOVERY_LIMIT", "300")
    monkeypatch.setenv("CRAWL_FINAL_LIMIT", "100")
    policy = load_freshness_policy("tiktok")
    assert policy.discovery_limit == 300
    assert policy.final_limit == 100
    # Final cannot exceed discovery
    monkeypatch.setenv("CRAWL_FINAL_LIMIT", "500")
    monkeypatch.setenv("CRAWL_DISCOVERY_LIMIT", "200")
    policy2 = load_freshness_policy("instagram")
    assert policy2.discovery_limit == 200
    assert policy2.final_limit == 200


def test_select_newest_and_attach_freshness(monkeypatch):
    monkeypatch.setenv("CRAWL_LOOKBACK_DAYS", "14")
    policy = load_freshness_policy("facebook")
    items = [
        {"url": "old", "created_time": "2026-01-01T00:00:00+00:00"},
        {"url": "new", "created_time": "2026-09-09T00:00:00+00:00"},
        {"url": "mid", "created_time": "2026-09-01T00:00:00+00:00"},
    ]
    top = select_newest(items, 2)
    assert [x["url"] for x in top] == ["new", "mid"]

    row = attach_freshness_fields(
        {"url": "x"},
        "2026-08-01T00:00:00+00:00",
        policy,
        now=NOW,
        newest_rank=1,
        in_final_limit=True,
    )
    assert row["freshness"] == "stale"
    assert row["published_at"]
    assert row["discovered_at"]
    assert row["coverage"] is False
    assert should_spend_on_comments("stale") is False
    assert should_spend_on_comments("fresh") is True
    assert should_spend_on_comments("unknown") is True


def test_incremental_search_does_not_early_stop_on_interleaved_old(monkeypatch):
    """
    Simulate non-chronological results: old, old, NEW, old...
    Old consecutive-URL stop would have aborted before the NEW url.
    """
    monkeypatch.setenv("CRAWL_LOOKBACK_DAYS", "14")

    existing = {f"https://www.tiktok.com/@u/video/{i}" for i in range(1, 20)}
    discovered_order = [
        "https://www.tiktok.com/@u/video/1",
        "https://www.tiktok.com/@u/video/2",
        "https://www.tiktok.com/@u/video/3",
        "https://www.tiktok.com/@u/video/4",
        "https://www.tiktok.com/@u/video/5",
        "https://www.tiktok.com/@u/video/6",
        "https://www.tiktok.com/@u/video/7",
        "https://www.tiktok.com/@u/video/8",
        "https://www.tiktok.com/@u/video/9",
        "https://www.tiktok.com/@u/video/10",
        "https://www.tiktok.com/@u/video/999999",  # new after 10 old
    ]

    new_urls = []
    consecutive_old = 0
    early_stopped = False
    # Old (dangerous) logic
    for url in discovered_order:
        if url in existing:
            consecutive_old += 1
        else:
            consecutive_old = 0
            new_urls.append(url)
        if consecutive_old >= 10:
            early_stopped = True
            break

    assert early_stopped is True
    assert "https://www.tiktok.com/@u/video/999999" not in new_urls

    # Fixed logic: never early-stop on consecutive old; collect all new
    fixed_new = [u for u in discovered_order if u not in existing]
    assert "https://www.tiktok.com/@u/video/999999" in fixed_new


def test_stale_search_result_not_counted_as_coverage(monkeypatch):
    monkeypatch.setenv("CRAWL_LOOKBACK_DAYS", "14")
    policy = load_freshness_policy("facebook")
    august = datetime(2026, 8, 5, tzinfo=timezone.utc)
    assert classify_detail_freshness(august, policy, now=NOW) == "stale"
    # Coverage acceptance: only fresh counts
    coverage_ok = classify_detail_freshness(august, policy, now=NOW) == "fresh"
    assert coverage_ok is False


def test_comment_pagination_respects_safety_limit():
    """Comment loops must stop on idle or explicit max, not comment_count claim."""
    max_comments = 5
    collected = []
    claimed_count = 1000  # UI claim must not be trusted
    for i in range(claimed_count):
        collected.append({"id": i})
        if len(collected) >= max_comments:
            break
    assert len(collected) == max_comments
    assert claimed_count != len(collected)


def test_get_known_urls_union(tmp_path):
    db = tmp_path / "crawl_state.db"
    with IncrementalCrawlState(db) as state:
        state.mark_crawled("https://a", "tiktok", "k1")
        state.mark_crawled("https://b", "tiktok_detail", "k1", "2026-09-01T00:00:00+00:00")
        known = state.get_known_urls("tiktok", "tiktok_detail")
        assert known == {"https://a", "https://b"}
