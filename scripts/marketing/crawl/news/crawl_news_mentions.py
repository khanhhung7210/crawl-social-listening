#!/usr/bin/env python3
"""Crawl Google News RSS for cinema brands → *_keyword_mentions.json (no Chrome).

Usage:
  PYTHONPATH=src python3 scripts/marketing/crawl/news/crawl_news_mentions.py
  PYTHONPATH=src python3 scripts/marketing/crawl/news/crawl_news_mentions.py --days 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
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
    "\"Cine Chào Summer\" Galaxy",
]


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


def fetch_rss(query: str, days: int) -> list[dict]:
    q = f"{query} when:{days}d"
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(
            {"q": q, "hl": "vi", "gl": "VN", "ceid": "VN:vi"}
        )
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GalaxySocialListening/1.0)",
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
                "source": "crawl_news_mentions",
                "stats": {},
                "comments": [],
            }
        )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="Google News when:Nd window")
    args = parser.parse_args()

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

    seen: set[str] = set()
    merged: list[dict] = []
    fetch_ok = 0
    fetch_fail = 0
    skipped_market = 0
    for term in terms:
        try:
            batch = fetch_rss(term, max(1, args.days))
            fetch_ok += 1
        except Exception as exc:
            fetch_fail += 1
            print(f"[news] skip {term!r}: {exc}", file=sys.stderr)
            continue
        print(f"[news] {term!r}: {len(batch)} items")
        for row in batch:
            key = row["post_id"]
            if key in seen:
                continue
            if not is_vietnam_relevant(
                row.get("post_text"),
                permalink=row.get("post_url"),
                author=row.get("page_name"),
                platform="news",
            ):
                skipped_market += 1
                continue
            seen.add(key)
            merged.append(row)

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

    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(merged)} mentions → {out_path} (skipped_market={skipped_market})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
