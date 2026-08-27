#!/usr/bin/env python3
"""Crawl live Google Play + App Store ratings/reviews for Galaxy Cinema (and Play competitors).

Writes JSON consumed by import_app_reviews.py (no sample/demo derivation).

App Store public RSS is often empty; reviews are scraped from apps.apple.com SSR JSON.

Usage:
  PYTHONPATH=src python3 scripts/marketing/crawl/reviews/crawl_app_reviews.py
  PYTHONPATH=src python3 scripts/marketing/crawl/reviews/crawl_app_reviews.py --play-count 200
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()

GLX_PLAY_ID = "com.galaxy.cinema"
GLX_IOS_ID = "593312549"
COMPETITORS_PLAY = {
    "CGV": "com.cgv.cinema.vn",
    "Lotte": "vn.com.lottecinema.pro",
    "Beta": "com.beta.betacineplex",
    "BHD": "io.starec.bhdstarcineplex",
    "Cinestar": "com.kingprocompany.cinestar",
}
COMPETITORS_IOS = {
    "CGV": "1067166194",
    "Lotte": "6448061305",
    "Beta": "1403107666",
    "BHD": "1493152806",
    "Cinestar": "1473249809",
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def crawl_play(app_id: str, *, lang: str, country: str) -> dict:
    from google_play_scraper import app as gp_app

    a = gp_app(app_id, lang=lang, country=country)
    return {
        "brand": "GLX" if app_id == GLX_PLAY_ID else None,
        "store": "google_play",
        "appId": a.get("appId"),
        "title": a.get("title"),
        "score": a.get("score"),
        "ratings": a.get("ratings"),
        "reviews": a.get("reviews"),
        "installs": a.get("installs"),
        "version": a.get("version"),
        "updated": a.get("updated"),
        "histogram": a.get("histogram"),
        "url": a.get("url"),
    }


def crawl_play_reviews(app_id: str, *, lang: str, country: str, count: int) -> list[dict]:
    from google_play_scraper import Sort, reviews

    result, _ = reviews(app_id, lang=lang, country=country, sort=Sort.NEWEST, count=count)
    out = []
    for r in result:
        out.append(
            {
                "reviewId": r.get("reviewId"),
                "score": r.get("score"),
                "at": r.get("at").isoformat() if r.get("at") else None,
                "content": r.get("content"),
                "version": r.get("reviewCreatedVersion") or r.get("appVersion"),
                "userName": r.get("userName"),
                "replyContent": r.get("replyContent"),
                "thumbsUpCount": r.get("thumbsUpCount"),
            }
        )
    return out


def crawl_ios_lookup(app_id: str, country: str) -> dict:
    data = fetch_json(f"https://itunes.apple.com/lookup?id={app_id}&country={country}")
    item = (data.get("results") or [{}])[0]
    return {
        "brand": "GLX",
        "store": "appstore",
        "app_id": int(app_id),
        "app_name": item.get("trackName") or "Galaxy Cinema",
        "score": item.get("averageUserRating"),
        "ratings": item.get("userRatingCount"),
        "score_current": item.get("averageUserRatingForCurrentVersion"),
        "ratings_current": item.get("userRatingCountForCurrentVersion"),
        "version": item.get("version"),
        "url": item.get("trackViewUrl")
        or f"https://apps.apple.com/{country}/app/id{app_id}",
        "bundle_id": item.get("bundleId"),
    }


def _parse_apps_ssr(html: str) -> dict | None:
    match = re.search(
        r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        return None
    return json.loads(match.group(1))


def _walk_reviews(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        kind = node.get("$kind")
        if kind == "Review" or (
            "rating" in node and "contents" in node and "reviewerName" in node
        ):
            out.append(node)
        if kind == "Ratings" and "ratingCounts" in node:
            out.append({"$kind": "Ratings", **node})
        for value in node.values():
            _walk_reviews(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_reviews(item, out)


def crawl_ios_from_apps_page(app_id: str, country: str) -> tuple[dict, list[dict]]:
    """Scrape ratings + featured reviews from apps.apple.com product page SSR."""
    urls = [
        f"https://apps.apple.com/{country}/app/id{app_id}",
        f"https://apps.apple.com/{country}/app/galaxy-cinema/id{app_id}",
        f"https://apps.apple.com/{country}/app/{app_id}?see-all=reviews",
    ]
    reviews: list[dict] = []
    ratings_meta: dict = {}
    seen: set[str] = set()

    for url in urls:
        try:
            html = fetch_text(url)
        except Exception as exc:  # noqa: BLE001
            print(f"iOS page failed {url}: {exc}", file=sys.stderr)
            continue
        data = _parse_apps_ssr(html)
        if not data:
            continue
        found: list[dict] = []
        _walk_reviews(data, found)
        for node in found:
            if node.get("$kind") == "Ratings":
                counts = node.get("ratingCounts") or []
                # Apple order: [5★, 4★, 3★, 2★, 1★] → store as Play-style [1..5]
                if len(counts) >= 5:
                    ratings_meta = {
                        "score": node.get("ratingAverage"),
                        "ratings": node.get("totalNumberOfRatings"),
                        "histogram": [
                            int(counts[4] or 0),
                            int(counts[3] or 0),
                            int(counts[2] or 0),
                            int(counts[1] or 0),
                            int(counts[0] or 0),
                        ],
                    }
                continue
            rid = str(node.get("id") or "")
            if not rid or rid in seen:
                continue
            rating = int(node.get("rating") or 0)
            if rating < 1 or rating > 5:
                continue
            seen.add(rid)
            reply = None
            response = node.get("response")
            if isinstance(response, dict):
                reply = response.get("contents")
            reviews.append(
                {
                    "id": rid,
                    "rating": rating,
                    "title": node.get("title"),
                    "review": node.get("contents"),
                    "author": node.get("reviewerName"),
                    "version": None,
                    "updated": node.get("date"),
                    "replyContent": reply,
                }
            )

    reviews.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return ratings_meta, reviews


def crawl_ios_reviews_rss(app_id: str, country: str, pages: int) -> list[dict]:
    """Legacy RSS fallback (often empty since Apple retired public feeds)."""
    reviews: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        url = (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"page={page}/id={app_id}/sortby=mostrecent/json"
        )
        try:
            data = fetch_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"iOS RSS page {page} failed: {exc}", file=sys.stderr)
            break
        entries = data.get("feed", {}).get("entry") or []
        page_new = 0
        for e in entries:
            if "im:rating" not in e:
                continue
            rid = str((e.get("id") or {}).get("label") or "")
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            page_new += 1
            reviews.append(
                {
                    "id": rid or None,
                    "rating": int((e.get("im:rating") or {}).get("label") or 0),
                    "title": (e.get("title") or {}).get("label"),
                    "review": (e.get("content") or {}).get("label"),
                    "author": ((e.get("author") or {}).get("name") or {}).get("label"),
                    "version": (e.get("im:version") or {}).get("label"),
                    "updated": (e.get("updated") or {}).get("label"),
                }
            )
        if page_new == 0:
            break
    return reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "app-reviews" / "live.json",
    )
    parser.add_argument("--lang", default="vi")
    parser.add_argument("--country", default="vn")
    parser.add_argument("--play-count", type=int, default=200)
    parser.add_argument("--ios-pages", type=int, default=10)
    parser.add_argument("--skip-competitors", action="store_true")
    args = parser.parse_args()

    try:
        import google_play_scraper  # noqa: F401
    except ImportError:
        print("Install: pip install 'google-play-scraper>=1.2.7'", file=sys.stderr)
        return 1

    out: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "live_crawl",
    }

    glx_play = crawl_play(GLX_PLAY_ID, lang=args.lang, country=args.country)
    glx_play["brand"] = "GLX"
    out["galaxy_google_play"] = glx_play
    out["galaxy_google_play_reviews"] = crawl_play_reviews(
        GLX_PLAY_ID, lang=args.lang, country=args.country, count=args.play_count
    )

    competitors = [glx_play]
    if not args.skip_competitors:
        for brand, app_id in COMPETITORS_PLAY.items():
            try:
                row = crawl_play(app_id, lang=args.lang, country=args.country)
                row["brand"] = brand
                competitors.append(row)
            except Exception as exc:  # noqa: BLE001
                print(f"Competitor Play failed {brand}/{app_id}: {exc}", file=sys.stderr)
    out["competitor_google_play_summary"] = competitors

    ios_meta = crawl_ios_lookup(GLX_IOS_ID, args.country)
    page_meta, page_reviews = crawl_ios_from_apps_page(GLX_IOS_ID, args.country)
    if page_meta.get("score") is not None:
        ios_meta["score"] = page_meta["score"]
    if page_meta.get("ratings") is not None:
        ios_meta["ratings"] = page_meta["ratings"]
    if page_meta.get("histogram"):
        ios_meta["histogram"] = page_meta["histogram"]

    ios_reviews = page_reviews
    if not ios_reviews:
        print("apps.apple.com returned 0 reviews; trying legacy RSS…", file=sys.stderr)
        ios_reviews = crawl_ios_reviews_rss(GLX_IOS_ID, args.country, args.ios_pages)

    out["galaxy_app_store"] = ios_meta
    out["galaxy_app_store_meta"] = ios_meta
    out["galaxy_app_store_reviews"] = ios_reviews

    ios_competitors = [ios_meta]
    if not args.skip_competitors:
        for brand, app_id in COMPETITORS_IOS.items():
            try:
                row = crawl_ios_lookup(app_id, args.country)
                row["brand"] = brand
                # Enrich histogram from product page when cheap enough
                page_m, _ = crawl_ios_from_apps_page(app_id, args.country)
                if page_m.get("score") is not None:
                    row["score"] = page_m["score"]
                if page_m.get("ratings") is not None:
                    row["ratings"] = page_m["ratings"]
                if page_m.get("histogram"):
                    row["histogram"] = page_m["histogram"]
                ios_competitors.append(row)
            except Exception as exc:  # noqa: BLE001
                print(f"Competitor iOS failed {brand}/{app_id}: {exc}", file=sys.stderr)
    out["competitor_app_store_summary"] = ios_competitors

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(
        f"Play {glx_play.get('score')}★ ({glx_play.get('ratings')} ratings) "
        f"reviews={len(out['galaxy_google_play_reviews'])}"
    )
    print(
        f"iOS  {ios_meta.get('score')}★ ({ios_meta.get('ratings')} ratings) "
        f"reviews={len(ios_reviews)} hist={'yes' if ios_meta.get('histogram') else 'no'}"
    )
    print(f"iOS competitors={len(ios_competitors) - 1}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
