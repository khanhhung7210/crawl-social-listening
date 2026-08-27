#!/usr/bin/env python3
"""Suy ra trailer / premiere từ Google News RSS (không cần API Google chính thức)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
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

from social_listening.paths import DATA_DIR  # noqa: E402

CATALOG = DATA_DIR / "distribution" / "film_catalog.json"
MILESTONES = DATA_DIR / "distribution" / "film_milestones.json"

TRAILER_RE = re.compile(r"\btrailer\b", re.I)
PREMIERE_RE = re.compile(
    r"\b(premiere|premier|khởi chiếu|công chiếu|release date|opens in theaters|in theaters|ra rạp)\b",
    re.I,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def fetch_rss(query: str, days: int = 365) -> list[dict]:
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
        pub_raw = item.findtext("pubDate")
        pub_dt: datetime | None = None
        if pub_raw:
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
            except (TypeError, ValueError, IndexError):
                pub_dt = None
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        text = f"{title}. {desc}".strip()
        if title:
            items.append({"title": title, "text": text, "pub_dt": pub_dt})
    return items


def parse_dates(text: str) -> list[date]:
    found: list[date] = []
    today = date.today()

    for m in re.finditer(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](20\d{2})\b", text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            found.append(date(y, mo, d))
        except ValueError:
            pass

    for m in re.finditer(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
        re.I,
    ):
        mo = MONTHS.get(m.group(1).lower())
        if mo:
            try:
                found.append(date(int(m.group(3)), mo, int(m.group(2))))
            except ValueError:
                pass

    for m in re.finditer(r"\b(\d{1,2})\s+th[aá]ng\s+(\d{1,2}),?\s+(20\d{2})\b", text, re.I):
        try:
            found.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass

    # Chỉ giữ ngày hợp lý: từ 2024 → +3 năm
    lo = date(2024, 1, 1)
    hi = date(today.year + 3, 12, 31)
    return [d for d in found if lo <= d <= hi]


def most_common_future_date(dates: list[date]) -> date | None:
    if not dates:
        return None
    counts = Counter(dates)
    return counts.most_common(1)[0][0]


def infer_milestones(title: str) -> dict[str, str | None]:
    trailer_items = fetch_rss(f'"{title}" trailer', days=540)
    release_items = fetch_rss(f'"{title}" khởi chiếu OR premiere OR "release date"', days=540)

    trailer_pub: date | None = None
    for item in trailer_items:
        if TRAILER_RE.search(item["text"]) and item["pub_dt"]:
            d = item["pub_dt"].date()
            if trailer_pub is None or d < trailer_pub:
                trailer_pub = d

    premiere_dates: list[date] = []
    for item in release_items:
        if PREMIERE_RE.search(item["text"]):
            premiere_dates.extend(parse_dates(item["text"]))

    premiere = most_common_future_date(premiere_dates)
    return {
        "trailer_date": trailer_pub.isoformat() if trailer_pub else None,
        "release_date": premiere.isoformat() if premiere else None,
        "trailer_hits": len(trailer_items),
        "release_hits": len(release_items),
    }


def load_catalog() -> list[dict]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    return [f for f in payload.get("films") or [] if f.get("active", True)]


def load_milestones() -> dict:
    if MILESTONES.exists():
        return json.loads(MILESTONES.read_text(encoding="utf-8"))
    return {"_note": "Lifecycle markers — auto + manual.", "milestones": []}


def upsert_milestone(rows: list[dict], slug: str, label: str, d: str, color: str) -> None:
    rows[:] = [r for r in rows if not (r.get("film_slug") == slug and r.get("label") == label)]
    rows.append({"film_slug": slug, "label": label, "date": d, "color": color})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", action="append", help="Film slug (default: all active)")
    parser.add_argument("--write", action="store_true", help="Ghi film_catalog.json + film_milestones.json")
    parser.add_argument("--seed-db", action="store_true", help="Chạy seed_films.py sau khi ghi JSON")
    args = parser.parse_args()

    catalog_payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    films = catalog_payload.get("films") or []
    wanted = {s.lower() for s in (args.slug or [])}
    selected = [f for f in films if f.get("active", True) and (not wanted or f.get("slug", "").lower() in wanted)]

    ms_payload = load_milestones()
    ms_rows: list[dict] = list(ms_payload.get("milestones") or [])

    for film in selected:
        slug = film["slug"]
        title = film["title"]
        print(f"\n=== {title} ({slug}) ===")
        inferred = infer_milestones(title)
        print(f"  trailer_date: {inferred['trailer_date']}  ({inferred['trailer_hits']} news hits)")
        print(f"  release_date: {inferred['release_date']}  ({inferred['release_hits']} news hits)")

        if not args.write:
            continue

        if inferred["trailer_date"]:
            film["trailer_date"] = inferred["trailer_date"]
            upsert_milestone(ms_rows, slug, "Trailer", inferred["trailer_date"], "#f59e0b")
        if inferred["release_date"]:
            film["release_date"] = inferred["release_date"]
            upsert_milestone(ms_rows, slug, "Khởi chiếu", inferred["release_date"], "#22c55e")

    if args.write:
        catalog_payload["films"] = films
        CATALOG.write_text(json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ms_payload["milestones"] = ms_rows
        MILESTONES.write_text(json.dumps(ms_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {CATALOG.name} + {MILESTONES.name}")

    if args.seed_db and args.write:
        import subprocess

        seed = PROJECT_ROOT / "scripts" / "distribution" / "seed_films.py"
        subprocess.run([sys.executable, str(seed)], check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
