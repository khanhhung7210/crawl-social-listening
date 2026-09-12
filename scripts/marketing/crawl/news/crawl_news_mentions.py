#!/usr/bin/env python3
"""Crawl Google News RSS for cinema brands → *_keyword_mentions.json (no Chrome).

Google News RSS has no reliable date-sort (scoring=n is a no-op on /rss/search).
A wide when:30d window ranks by relevance and buries fresh stories, so we crawl
multiple recency windows (1d + 7d + lookback) and merge/dedupe, then sort by pubDate.

Usage:
  PYTHONPATH=src python3 scripts/marketing/crawl/news/crawl_news_mentions.py
  PYTHONPATH=src python3 scripts/marketing/crawl/news/crawl_news_mentions.py --days 14
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload  # noqa: E402
from social_listening.paths import DATA_DIR, ensure_dir  # noqa: E402
from social_listening.vietnam_filter import is_vietnam_relevant  # noqa: E402

QUERIES_EXTRA = [
    "Galaxy Cinema",
    "CGV Cinemas",
    "Lotte Cinema",
    "Beta Cinemas",
    "BHD Star",
    "Cinestar",
    "Cine Chào Summer",
    "Cine Chao Summer",
    '"Cine Chào Summer" Galaxy',
]

# Narrow → wide. Narrow windows surface hours/days-old stories that a wide
# relevance SERP buries under promo/evergreen hits.
DEFAULT_WINDOW_DAYS = (1, 7)


def stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def parse_pub(value: str | None) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def resolve_windows(days: int) -> list[tuple[str, int]]:
    """Return ordered (mode, when_days) windows, always ending with lookback."""
    lookback = max(1, int(days))
    windows: list[tuple[str, int]] = []
    seen: set[int] = set()
    for d in DEFAULT_WINDOW_DAYS:
        if d < lookback and d not in seen:
            windows.append((f"when_{d}d", d))
            seen.add(d)
    if lookback not in seen:
        windows.append((f"when_{lookback}d", lookback))
    return windows


def fetch_rss(query: str, when_days: int, mode: str) -> list[dict]:
    q = f"{query} when:{when_days}d"
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": q, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    items: list[dict] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = parse_pub(item.findtext("pubDate"))
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        if not title or not link:
            continue
        post_id = stable_id(link, title)
        text = title if not desc else f"{title}. {desc}"
        items.append(
            {
                "platform": "news",
                "post_id": post_id,
                "page_id": source or "google_news",
                "page_name": source or "Google News",
                "post_url": link,
                "post_created_at": pub,
                "post_text": text,
                "post_keyword_match": True,
                "parent_keyword_match": True,
                "post_keyword_matches": [query],
                "search_modes": [mode],
                "source": "crawl_news_mentions",
                "stats": {},
                "comments": [],
            }
        )
    return items


def merge_row(existing: dict, incoming: dict) -> dict:
    modes = []
    for src in (existing, incoming):
        raw = src.get("search_modes") or []
        if isinstance(raw, list):
            modes.extend(str(x) for x in raw if x)
    matches = []
    for src in (existing, incoming):
        raw = src.get("post_keyword_matches") or []
        if isinstance(raw, list):
            matches.extend(str(x) for x in raw if x)
    out = dict(existing)
    out.update({k: v for k, v in incoming.items() if v not in (None, "", [], {})})
    # Prefer richer / newer timestamp if one side empty
    if not out.get("post_created_at"):
        out["post_created_at"] = incoming.get("post_created_at") or existing.get("post_created_at") or ""
    out["search_modes"] = sorted(set(modes))
    out["post_keyword_matches"] = list(dict.fromkeys(matches))
    return out


def within_lookback(row: dict, cutoff: datetime) -> bool:
    dt = parse_iso(row.get("post_created_at"))
    if dt is None:
        # Keep unknown-date rows from this crawl; drop ancient unknowns from file merge
        return bool(row.get("_from_crawl"))
    return dt >= cutoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_days = int(os.getenv("CRAWL_LOOKBACK_DAYS", "14") or "14")
    parser.add_argument(
        "--days",
        type=int,
        default=default_days,
        help="Google News lookback window (default CRAWL_LOOKBACK_DAYS or 14)",
    )
    args = parser.parse_args()
    lookback_days = max(1, args.days)
    windows = resolve_windows(lookback_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    terms = list(dict.fromkeys(collect_search_terms(load_keyword_payload()) + QUERIES_EXTRA))
    # Prefer brand-ish terms; skip bare hashtags for news search quality
    terms = [t for t in terms if not t.startswith("#")]

    out_dir = ensure_dir(DATA_DIR / "news" / "processed" / "galaxy_cinema")
    out_path = out_dir / "news_keyword_mentions.json"

    existing: list[dict] = []
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                existing = prev
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[news] warn: cannot read existing {out_path}: {exc}", file=sys.stderr)

    by_id: dict[str, dict] = {}
    mode_counts: dict[str, int] = {mode: 0 for mode, _ in windows}
    fetch_ok = 0
    fetch_fail = 0
    skipped_market = 0

    print(
        f"[news] lookback={lookback_days}d windows={[m for m, _ in windows]} "
        f"terms={len(terms)}",
        flush=True,
    )

    for term in terms:
        term_new = 0
        for mode, when_days in windows:
            try:
                batch = fetch_rss(term, when_days, mode)
                fetch_ok += 1
            except Exception as exc:
                fetch_fail += 1
                print(f"[news] skip {term!r} mode={mode}: {exc}", file=sys.stderr)
                continue
            for row in batch:
                row["_from_crawl"] = True
                if not is_vietnam_relevant(
                    row.get("post_text"),
                    permalink=row.get("post_url"),
                    author=row.get("page_name"),
                    platform="news",
                ):
                    skipped_market += 1
                    continue
                if not within_lookback(row, cutoff):
                    continue
                key = str(row["post_id"])
                prev = by_id.get(key)
                if prev is None:
                    by_id[key] = row
                    mode_counts[mode] = mode_counts.get(mode, 0) + 1
                    term_new += 1
                else:
                    by_id[key] = merge_row(prev, row)
                    # Count first-seen mode only for extras; still tag modes on row
        print(
            f"[news] {term!r}: +{term_new} unique "
            f"(windows={ {m: mode_counts.get(m, 0) for m, _ in windows} })",
            flush=True,
        )

    # Keep prior file rows still inside lookback (RSS cap ~100; avoid wipe).
    kept_existing = 0
    for row in existing:
        if not isinstance(row, dict):
            continue
        key = str(row.get("post_id") or "").strip()
        if not key:
            continue
        if key in by_id:
            by_id[key] = merge_row(row, by_id[key])
            continue
        if not within_lookback(row, cutoff):
            continue
        if not is_vietnam_relevant(
            row.get("post_text"),
            permalink=row.get("post_url"),
            author=row.get("page_name"),
            platform="news",
        ):
            continue
        by_id[key] = dict(row)
        kept_existing += 1

    merged = list(by_id.values())
    for row in merged:
        row.pop("_from_crawl", None)

    if not merged:
        if existing:
            reason = "all fetches failed" if fetch_ok == 0 else "new crawl empty"
            print(
                f"[news] KEEP previous {len(existing)} mentions "
                f"({reason}; ok={fetch_ok} fail={fetch_fail}) → {out_path}"
            )
            return 0
        out_path.write_text("[]\n", encoding="utf-8")
        print(f"Wrote 0 mentions → {out_path}")
        return 1

    merged.sort(
        key=lambda r: str(r.get("post_created_at") or ""),
        reverse=True,
    )
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(merged)} mentions → {out_path} "
        f"(skipped_market={skipped_market} kept_existing={kept_existing} "
        f"ok={fetch_ok} fail={fetch_fail} modes={mode_counts})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
