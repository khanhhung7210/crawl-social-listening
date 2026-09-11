"""
Shared freshness / incremental crawl policy.

Search rankings are NOT assumed chronological. Do not stop scrolling solely
because previously seen URLs appeared in a row. Stop only on:
  - no additional results (idle/empty),
  - configured safety limits,
  - or a validated content-timestamp freshness boundary.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


def env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class FreshnessPolicy:
    """Configurable lookback and safety limits for one platform."""

    platform: str
    lookback: timedelta
    # Discover broadly (search scroll), then keep newest FINAL after timestamps.
    discovery_limit: int
    final_limit: int
    max_scroll_rounds: int
    max_runtime_seconds: int
    keyword_runtime_seconds: int
    idle_rounds_before_stop: int
    empty_rounds_before_skip: int
    # After this many validated-stale detail fetches for one keyword, stop detailing it
    max_stale_details_per_keyword: int
    # Only when content timestamps are validated AND ordering is trusted (e.g. Threads recent)
    consecutive_stale_content_stop: int
    # Comment safety limits
    max_comments: int
    max_comment_scroll_rounds: int
    comment_idle_rounds_before_stop: int

    @property
    def lookback_days(self) -> float:
        return self.lookback.total_seconds() / 86400.0

    @property
    def max_new_urls_per_keyword(self) -> int:
        """Backward-compatible alias for final_limit (kept newest after sort)."""
        return self.final_limit


def _platform_env(platform: str, suffix: str, default: str) -> str:
    key = f"{platform.upper()}_{suffix}"
    shared = os.getenv(f"CRAWL_{suffix}", "").strip()
    specific = os.getenv(key, "").strip()
    return specific or shared or default


def load_freshness_policy(platform: str) -> FreshnessPolicy:
    """
    Load per-platform freshness + safety limits from environment.

    Shared:
      CRAWL_LOOKBACK_DAYS (default 14)
      CRAWL_DISCOVERY_LIMIT (default 300) — search candidate pool
      CRAWL_FINAL_LIMIT (default 100) — newest kept after timestamp sort
      CRAWL_MAX_STALE_DETAILS_PER_KEYWORD (default 25)
      CRAWL_CONSECUTIVE_STALE_CONTENT_STOP (default 0 = disabled)

    Per-platform overrides: PREFIX_DISCOVERY_LIMIT / PREFIX_FINAL_LIMIT
    Legacy aliases (map to FINAL): FACEBOOK_MAX_POSTS*, TIKTOK_MAX_VIDEOS, etc.
    """
    p = platform.lower().strip()
    lookback_days = float(_platform_env(p, "LOOKBACK_DAYS", "14") or "14")
    lookback_days = max(0.0, lookback_days)

    defaults = {
        "facebook": {
            "discovery": 300,
            "final": 100,
            "scroll": 80,
            "runtime": 900,
            "keyword_runtime": 300,
            "idle": 8,
            "empty": 5,
            "comments": 200,
            "comment_scroll": 48,
            "comment_idle": 5,
            "stale_stop": 0,
        },
        "tiktok": {
            "discovery": 300,
            "final": 100,
            "scroll": 240,
            "runtime": 600,
            "keyword_runtime": 240,
            "idle": 8,
            "empty": 5,
            "comments": 500,
            "comment_scroll": 80,
            "comment_idle": 6,
            "stale_stop": 0,
        },
        "threads": {
            "discovery": 300,
            "final": 100,
            "scroll": 240,
            "runtime": 600,
            "keyword_runtime": 240,
            "idle": 8,
            "empty": 5,
            "comments": 300,
            "comment_scroll": 40,
            "comment_idle": 4,
            # Threads search uses filter=recent — allow content-time stop when validated
            "stale_stop": 12,
        },
        "instagram": {
            "discovery": 300,
            "final": 100,
            "scroll": 120,
            "runtime": 420,
            "keyword_runtime": 180,
            "idle": 8,
            "empty": 5,
            "comments": 300,
            "comment_scroll": 80,
            "comment_idle": 6,
            "stale_stop": 0,
        },
        "youtube": {
            "discovery": 300,
            "final": 100,
            "scroll": 80,
            "runtime": 300,
            "keyword_runtime": 180,
            "idle": 6,
            "empty": 5,
            "comments": 200,
            "comment_scroll": 40,
            "comment_idle": 5,
            "stale_stop": 0,
        },
        "google_maps": {
            "discovery": 300,
            "final": 100,
            "scroll": 8,
            "runtime": 600,
            "keyword_runtime": 300,
            "idle": 3,
            "empty": 3,
            "comments": 500,
            "comment_scroll": 8,
            "comment_idle": 3,
            "stale_stop": 0,
        },
    }
    d = defaults.get(p, defaults["tiktok"])

    discovery = env_int(
        f"{p.upper()}_DISCOVERY_LIMIT",
        env_int("CRAWL_DISCOVERY_LIMIT", d["discovery"]),
    )
    # Legacy MAX_* aliases feed FINAL (kept newest), not discovery.
    legacy_final = d["final"]
    if p == "tiktok":
        legacy_final = env_int("TIKTOK_MAX_VIDEOS", legacy_final)
    elif p == "threads":
        legacy_final = env_int(
            "THREADS_MAX_URLS_PER_KEYWORD",
            env_int("THREADS_MAX_THREADS", legacy_final),
        )
    elif p == "facebook":
        legacy_final = env_int(
            "FACEBOOK_MAX_POSTS_PER_KEYWORD",
            env_int("FACEBOOK_MAX_POSTS", legacy_final),
        )
    elif p == "instagram":
        legacy_final = env_int("INSTAGRAM_MAX_POSTS", legacy_final)
    elif p == "youtube":
        legacy_final = env_int("YOUTUBE_MAX_VIDEOS", legacy_final)
    else:
        legacy_final = env_int(f"{p.upper()}_MAX_URLS_PER_KEYWORD", legacy_final)

    final = env_int(
        f"{p.upper()}_FINAL_LIMIT",
        env_int("CRAWL_FINAL_LIMIT", legacy_final),
    )
    discovery = max(1, discovery)
    final = max(1, min(final, discovery))

    return FreshnessPolicy(
        platform=p,
        lookback=timedelta(days=lookback_days),
        discovery_limit=discovery,
        final_limit=final,
        max_scroll_rounds=env_int(f"{p.upper()}_MAX_SCROLL_ROUNDS", d["scroll"]),
        max_runtime_seconds=env_int(f"{p.upper()}_MAX_RUNTIME_SECONDS", d["runtime"]),
        keyword_runtime_seconds=env_int(f"{p.upper()}_KEYWORD_RUNTIME_SECONDS", d["keyword_runtime"]),
        idle_rounds_before_stop=env_int(f"{p.upper()}_IDLE_ROUNDS_BEFORE_STOP", d["idle"]),
        empty_rounds_before_skip=env_int(f"{p.upper()}_MAX_EMPTY_ROUNDS_BEFORE_SKIP", d["empty"]),
        max_stale_details_per_keyword=env_int(
            f"{p.upper()}_MAX_STALE_DETAILS_PER_KEYWORD",
            env_int("CRAWL_MAX_STALE_DETAILS_PER_KEYWORD", 25),
        ),
        consecutive_stale_content_stop=env_int(
            f"{p.upper()}_CONSECUTIVE_STALE_CONTENT_STOP",
            env_int("CRAWL_CONSECUTIVE_STALE_CONTENT_STOP", d["stale_stop"]),
        ),
        max_comments=env_int(f"{p.upper()}_MAX_COMMENTS", d["comments"]),
        max_comment_scroll_rounds=env_int(
            f"{p.upper()}_MAX_COMMENT_SCROLL_ROUNDS",
            env_int(
                f"{p.upper()}_COMMENT_LOAD_ROUNDS",
                env_int(f"{p.upper()}_REPLY_SCROLL_ROUNDS", d["comment_scroll"]),
            ),
        ),
        comment_idle_rounds_before_stop=env_int(
            f"{p.upper()}_COMMENT_IDLE_ROUNDS_BEFORE_STOP",
            env_int(f"{p.upper()}_REPLY_IDLE_ROUNDS", d["comment_idle"]),
        ),
    )


def parse_content_timestamp(value: object, *, reference: datetime | None = None) -> Optional[datetime]:
    """Parse platform content timestamps into timezone-aware UTC datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        ts = float(value)
        # Heuristic: ms vs seconds
        if ts > 1e12:
            ts = ts / 1000.0
        if ts <= 0:
            return None
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d{9,13}", text):
        return parse_content_timestamp(int(text), reference=reference)

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    return None


def is_stale(
    content_timestamp: object,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
) -> Optional[bool]:
    """
    Return True if content is older than lookback, False if fresh, None if unknown.
    Unknown timestamps must NOT be treated as proof of freshness or staleness.
    """
    parsed = parse_content_timestamp(content_timestamp, reference=now)
    if parsed is None:
        return None
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    cutoff = ref.astimezone(timezone.utc) - policy.lookback
    return parsed < cutoff


def is_fresh(
    content_timestamp: object,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
) -> Optional[bool]:
    stale = is_stale(content_timestamp, policy, now=now)
    if stale is None:
        return None
    return not stale


def should_stop_for_validated_stale_content(
    consecutive_stale_with_timestamp: int,
    policy: FreshnessPolicy,
) -> bool:
    """
    Stop pagination only when we have validated content timestamps that are
    outside the lookback window, and the platform opted into content-time stop.
    Never use URL-history consecutive-old for this decision.
    """
    threshold = policy.consecutive_stale_content_stop
    if threshold <= 0:
        return False
    return consecutive_stale_with_timestamp >= threshold


def should_stop_keyword_details(stale_detail_count: int, policy: FreshnessPolicy) -> bool:
    """Stop detailing one keyword after too many validated-stale detail fetches."""
    limit = policy.max_stale_details_per_keyword
    if limit <= 0:
        return False
    return stale_detail_count >= limit


@dataclass
class KeywordCrawlStats:
    keyword: str
    discovered: int = 0
    new: int = 0
    stale: int = 0
    already_seen: int = 0
    detail_success: int = 0
    detail_failed: int = 0
    comments_found: int = 0
    comments_crawled: int = 0
    runtime_seconds: float = 0.0
    stop_reason: str = ""
    extras: dict = field(default_factory=dict)

    def log(self, prefix: str) -> None:
        parts = [
            f"keyword={self.keyword}",
            f"discovered={self.discovered}",
            f"new={self.new}",
            f"stale={self.stale}",
            f"already_seen={self.already_seen}",
            f"detail_success={self.detail_success}",
            f"detail_failed={self.detail_failed}",
            f"comments_found={self.comments_found}",
            f"comments_crawled={self.comments_crawled}",
            f"runtime={self.runtime_seconds:.1f}s",
        ]
        if self.stop_reason:
            parts.append(f"reason={self.stop_reason}")
        for key, value in self.extras.items():
            parts.append(f"{key}={value}")
        print(f"[{prefix}] " + " ".join(parts), flush=True)


def extract_unix_create_time_from_html(html: str) -> Optional[datetime]:
    """Best-effort createTime / taken_at extraction from raw HTML/JSON blobs."""
    if not html:
        return None
    patterns = (
        r'"createTime"\s*:\s*"?(\d{9,13})"?',
        r'"create_time"\s*:\s*"?(\d{9,13})"?',
        r'"taken_at_timestamp"\s*:\s*"?(\d{9,13})"?',
        r'"taken_at"\s*:\s*"?(\d{9,13})"?',
        r'"published_time"\s*:\s*"?(\d{9,13})"?',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"uploadDate"\s*:\s*"([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if not match:
            continue
        parsed = parse_content_timestamp(match.group(1))
        if parsed is not None:
            return parsed
    return None


def classify_detail_freshness(
    content_timestamp: object,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
) -> str:
    """
    Return one of: 'fresh', 'stale', 'unknown'.
    Unknown must not be counted as successful current coverage by itself.
    """
    stale = is_stale(content_timestamp, policy, now=now)
    if stale is True:
        return "stale"
    if stale is False:
        return "fresh"
    return "unknown"


_TIME_FIELDS = (
    "created_time",
    "created_at",
    "published_at",
    "upload_date",
    "taken_at_timestamp",
    "timestamp",
    "content_timestamp",
)


def content_time_sort_key(item: object, fields: tuple[str, ...] = _TIME_FIELDS) -> str:
    """ISO UTC string for reverse-sort; empty sorts last when reverse=True."""
    if not isinstance(item, dict):
        return ""
    for field_name in fields:
        parsed = parse_content_timestamp(item.get(field_name))
        if parsed is not None:
            return parsed.astimezone(timezone.utc).isoformat()
    return ""


def select_newest(items: list, limit: int, fields: tuple[str, ...] = _TIME_FIELDS) -> list:
    """Return up to ``limit`` items with the newest content timestamps."""
    if limit <= 0:
        return []
    ranked = sorted(items, key=lambda x: content_time_sort_key(x, fields), reverse=True)
    return ranked[:limit]


def attach_freshness_fields(
    record: dict,
    content_timestamp: object,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
    newest_rank: int | None = None,
    in_final_limit: bool | None = None,
) -> dict:
    """
    Annotate a crawl record without dropping it.

    Business rules (import / comment spend) read ``freshness`` / ``in_final_limit``.
    Discovery/detail must keep the row even when stale.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    parsed = parse_content_timestamp(content_timestamp, reference=ref)
    freshness = classify_detail_freshness(content_timestamp, policy, now=ref)
    published = parsed.astimezone(timezone.utc).isoformat() if parsed else None
    record["published_at"] = published or record.get("published_at")
    if parsed is not None and not record.get("created_time"):
        record["created_time"] = published
    record["discovered_at"] = ref.astimezone(timezone.utc).isoformat()
    record["freshness"] = freshness
    record["stale"] = freshness == "stale"
    if newest_rank is not None:
        record["newest_rank"] = newest_rank
    if in_final_limit is not None:
        record["in_final_limit"] = in_final_limit
    # Coverage = in final window AND not validated-stale (unknown still eligible).
    if in_final_limit is False or freshness == "stale":
        record["coverage"] = False
    elif in_final_limit is True:
        record["coverage"] = True
    return record


def should_spend_on_comments(freshness: str) -> bool:
    """Expensive comment pagination only for non-stale items."""
    return freshness != "stale"
