#!/usr/bin/env python3
"""Crawl Google News RSS cho từng phim Distribution (không cần Chrome)."""

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

CATALOG = DATA_DIR / "distribution" / "film_catalog.json"


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]


def parse_pub(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return datetime.now(timezone.utc).isoformat()


def fetch_rss(query: str, days: int) -> list[dict]:
    q = f"{query} when:{days}d"
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": q, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GalaxyDistribution/1.0)",
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
                "post_keyword_matches": [query],
                "source": "crawl_film_news",
                "stats": {},
                "comments": [],
            }
        )
    return items


def resolve_keyword_file(film: dict) -> Path:
    rel = str(film.get("keyword_file") or f"films/{film['slug']}.json")
    return DATA_DIR / "distribution" / rel


def crawl_film(film: dict, days: int) -> tuple[Path, int]:
    slug = str(film.get("slug") or "").strip()
    kw_path = resolve_keyword_file(film)
    if not kw_path.exists():
        raise FileNotFoundError(kw_path)
    terms = collect_search_terms(load_keyword_payload(kw_path), include_hashtags=False)
    # Prefer title + primary keywords first
    title = str(film.get("title") or "").strip()
    if title and title not in terms:
        terms.insert(0, title)

    out_dir = ensure_dir(DATA_DIR / "news" / "processed" / slug)
    out_path = out_dir / "news_keyword_mentions.json"

    existing: list[dict] = []
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                existing = prev
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[news/{slug}] warn: cannot read existing {out_path}: {exc}", file=sys.stderr)

    seen: set[str] = set()
    merged: list[dict] = []
    fetch_ok = 0
    fetch_fail = 0
    for term in terms[:12]:
        try:
            batch = fetch_rss(term, max(1, days))
            fetch_ok += 1
        except Exception as exc:
            fetch_fail += 1
            print(f"[news/{slug}] skip {term!r}: {exc}", file=sys.stderr)
            continue
        print(f"[news/{slug}] {term!r}: {len(batch)}")
        for row in batch:
            key = row["post_id"]
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)

    # Never wipe a good file with [] on total network failure / empty crawl.
    if not merged:
        if existing:
            reason = "all fetches failed" if fetch_ok == 0 else "new crawl empty"
            print(
                f"[news/{slug}] KEEP previous {len(existing)} mentions "
                f"({reason}; ok={fetch_ok} fail={fetch_fail}) → {out_path}",
                file=sys.stderr,
            )
            return out_path, len(existing)
        out_path.write_text("[]\n", encoding="utf-8")
        return out_path, 0

    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path, len(merged)


def _configure_stdio() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--film", default="", help="Film slug; default all active")
    parser.add_argument("--import-db", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    films = catalog.get("films") or []
    if args.film:
        films = [f for f in films if f.get("slug") == args.film]
    else:
        films = [f for f in films if f.get("active")]

    total = 0
    for film in films:
        path, n = crawl_film(film, args.days)
        total += n
        print(f"Wrote {n} → {path}")

    if args.import_db and total > 0:
        import subprocess

        for film in films:
            slug = film.get("slug")
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts/distribution/import_film_mentions.py"), "--film", slug],
                cwd=str(PROJECT_ROOT),
                env={
                    **os.environ,
                    "PYTHONPATH": str(PROJECT_ROOT / "src"),
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                check=False,
            )

    print(f"Total news mentions: {total}")
    return 0 if total >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
