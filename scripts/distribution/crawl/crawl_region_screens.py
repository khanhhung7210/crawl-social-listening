#!/usr/bin/env python3
"""Crawl suất chiếu / rạp theo vùng từ Moveek → data/distribution/film_region_screens.json.

Nguồn heatmap row "Screens" trên Distribution dashboard.
Mặc định đếm suất chiếu Galaxy Cinema theo 6 tỉnh/TP (+ Khác = phần còn lại).

Ví dụ:
  PYTHONPATH=src python3 scripts/distribution/crawl/crawl_region_screens.py --all-active
  PYTHONPATH=src python3 scripts/distribution/crawl/crawl_region_screens.py --film the_odyssey --seed-db
  PYTHONPATH=src python3 scripts/distribution/crawl/crawl_region_screens.py --film minion --chain all --metric cinemas
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.dis_regions import (  # noqa: E402
    DIS_REGIONS,
    MOVEEK_REGION_TO_DIS,
    empty_region_counts,
)
from social_listening.paths import DATA_DIR  # noqa: E402

CATALOG = DATA_DIR / "distribution" / "film_catalog.json"
SCREENS_OUT = DATA_DIR / "distribution" / "film_region_screens.json"
MOVEEK_MAP = DATA_DIR / "distribution" / "moveek_films.json"
USER_AGENT = "Mozilla/5.0 (compatible; GalaxyDistribution/1.0; +internal)"

# Known Moveek slugs (override / bootstrap search)
DEFAULT_MOVEEK: dict[str, dict] = {
    "the_odyssey": {"slug": "the-odyssey"},
    "minion": {"slug": "minions-quai-vat", "aliases": ["Minions & Quái Vật", "Minions"]},
    "nguoi_nhen_khoi_dau_moi": {"slug": "spider-man-4-brand-new-day", "aliases": ["Người Nhện 4", "Brand New Day"]},
    "nghi_he_so_nghi_huu": {"slug": "nghi-he-so-nghi-huu"},
    "am_chuoi_phim_ngan_linh_di": {"slug": "am-chuoi-phim-ngan-linh-di"},
    "lilo_stitch": {"slug": "lilo-and-stitch", "aliases": ["Lilo & Stitch", "Lilo Stitch"]},
}


def http_get(url: str, accept: str = "*/*", timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "vi-VN,vi;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_moveek_cache() -> dict[str, dict]:
    payload = load_json(MOVEEK_MAP)
    films = dict(DEFAULT_MOVEEK)
    films.update(payload.get("films") or {})
    return films


def save_moveek_cache(films: dict[str, dict]) -> None:
    save_json(
        MOVEEK_MAP,
        {
            "_note": "Moveek film id/slug cache — crawl_region_screens.py cập nhật tự động.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "films": films,
        },
    )


def extract_film_id(html: str) -> int | None:
    m = re.search(r"id:\s*'(\d+)'", html)
    if m:
        return int(m.group(1))
    m = re.search(r'data-id="(\d+)"[^>]*btn-do-movie-like', html)
    if m:
        return int(m.group(1))
    m = re.search(r'btn-do-movie-like[^>]*data-id="(\d+)"', html)
    if m:
        return int(m.group(1))
    return None


def search_moveek_slug(query: str) -> list[tuple[str, str]]:
    """Return [(title, /phim/slug/)] from Moveek search."""
    url = "https://moveek.com/tim-kiem/?" + urllib.parse.urlencode({"s": query})
    try:
        html = http_get(url, accept="text/html").decode("utf-8", "ignore")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  [search] fail {query!r}: {exc}", file=sys.stderr)
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r'href="(/phim/([a-z0-9-]+)/)"[^>]*>([^<]{2,120})', html, re.I):
        href, slug, title = m.group(1), m.group(2), re.sub(r"\s+", " ", m.group(3)).strip()
        if slug in seen or title.lower() in {"mua vé", "đặt vé"}:
            continue
        seen.add(slug)
        out.append((title, href))
    # fallback: bare links without text in same tag
    if not out:
        for m in re.finditer(r'href="(/phim/([a-z0-9-]+)/)"', html, re.I):
            href, slug = m.group(1), m.group(2)
            if slug not in seen:
                seen.add(slug)
                out.append((slug, href))
    return out


def resolve_moveek_film(film: dict, cache: dict[str, dict]) -> tuple[int, str]:
    slug = str(film.get("slug") or "")
    entry = dict(cache.get(slug) or {})
    moveek_slug = str(entry.get("slug") or "").strip().strip("/")
    film_id = entry.get("id")

    if not moveek_slug:
        queries = [str(film.get("title") or "")]
        queries += list(film.get("aliases") or [])
        queries += list(entry.get("aliases") or [])
        for q in queries:
            q = (q or "").strip()
            if not q:
                continue
            hits = search_moveek_slug(q)
            if hits:
                title, href = hits[0]
                moveek_slug = href.strip("/").split("/")[-1]
                print(f"  [resolve] {slug} ← search {q!r} → {moveek_slug} ({title})")
                break
        if not moveek_slug:
            raise LookupError(f"Cannot resolve Moveek slug for film {slug}")

    if not film_id:
        html = http_get(f"https://moveek.com/phim/{moveek_slug}/", accept="text/html").decode(
            "utf-8", "ignore"
        )
        film_id = extract_film_id(html)
        if not film_id:
            raise LookupError(f"No Moveek film id on /phim/{moveek_slug}/")
        print(f"  [resolve] {slug} id={film_id}")

    entry["slug"] = moveek_slug
    entry["id"] = int(film_id)
    cache[slug] = entry
    return int(film_id), moveek_slug


def list_cinemas(film_id: int, show_date: str, region_id: int, chain: str) -> list[dict]:
    url = (
        f"https://moveek.com/showtime/movie/{film_id}"
        f"?date={show_date}&region={region_id}&version=&ticketing=0"
    )
    raw = http_get(url, accept="application/json")
    data = json.loads(raw.decode("utf-8"))
    rows: list[dict] = []
    for cp in data.get("cineplexes") or []:
        brand = str((cp.get("data") or {}).get("name") or "")
        if chain == "galaxy" and "galaxy" not in brand.lower():
            continue
        for c in cp.get("cinemas") or []:
            rows.append(
                {
                    "id": int(c["id"]),
                    "name": c.get("name"),
                    "cineplex": brand,
                    "address": (c.get("location") or {}).get("address") or "",
                }
            )
    return rows


def count_showtimes(film_id: int, show_date: str, cinema_id: int) -> int:
    url = f"https://moveek.com/showtime/movie/{film_id}?date={show_date}&cinema={cinema_id}"
    html = http_get(url, accept="text/html").decode("utf-8", "ignore")
    return html.count("btn-showtime")


def crawl_region_metric(
    film_id: int,
    show_date: str,
    region_id: int,
    chain: str,
    metric: str,
    workers: int,
) -> tuple[int, int]:
    """Return (value, cinema_count)."""
    cinemas = list_cinemas(film_id, show_date, region_id, chain)
    if metric == "cinemas":
        return len(cinemas), len(cinemas)
    if not cinemas:
        return 0, 0
    total = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(count_showtimes, film_id, show_date, c["id"]) for c in cinemas]
        for fut in as_completed(futs):
            try:
                total += int(fut.result() or 0)
            except Exception as exc:
                print(f"    [warn] cinema showtime fail: {exc}", file=sys.stderr)
    return total, len(cinemas)


def crawl_film_screens(
    film: dict,
    cache: dict[str, dict],
    show_date: str,
    chain: str,
    metric: str,
    workers: int,
    sleep_s: float,
) -> dict[str, int]:
    slug = str(film.get("slug") or "")
    film_id, moveek_slug = resolve_moveek_film(film, cache)
    counts = empty_region_counts()
    detail: dict[str, dict] = {}

    # Named DIS cities via Moveek region ids
    for region_id, dis_name in MOVEEK_REGION_TO_DIS.items():
        if sleep_s > 0:
            time.sleep(sleep_s)
        value, n_cinemas = crawl_region_metric(
            film_id, show_date, region_id, chain, metric, workers
        )
        counts[dis_name] = value
        detail[dis_name] = {"moveek_region_id": region_id, "cinemas": n_cinemas, "value": value}
        print(f"  [{slug}] {dis_name}: {value} ({n_cinemas} rạp)")

    # Khác = các tỉnh còn lại (scan a few known leftover ids lightly via cinema list)
    other_ids = [
        rid
        for rid in range(1, 60)
        if rid not in MOVEEK_REGION_TO_DIS
    ]
    other_total = 0
    other_cinemas = 0
    for region_id in other_ids:
        try:
            if sleep_s > 0:
                time.sleep(sleep_s * 0.25)
            value, n_cinemas = crawl_region_metric(
                film_id, show_date, region_id, chain, metric, workers
            )
        except Exception:
            continue
        if n_cinemas <= 0 and value <= 0:
            continue
        other_total += value
        other_cinemas += n_cinemas
    counts["Khác"] = other_total
    detail["Khác"] = {"cinemas": other_cinemas, "value": other_total}
    print(f"  [{slug}] Khác: {other_total} ({other_cinemas} rạp)")

    cache[slug] = {
        **cache.get(slug, {}),
        "slug": moveek_slug,
        "id": film_id,
        "last_crawl": {
            "date": show_date,
            "chain": chain,
            "metric": metric,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return counts


def merge_screens(existing: dict, film_slug: str, counts: dict[str, int], meta: dict) -> dict:
    payload = dict(existing) if existing else {}
    payload["_note"] = (
        "Suất chiếu / rạp theo vùng — crawl từ Moveek (crawl_region_screens.py). "
        "Dashboard Distribution đọc qua seed_films → films.metadata.region_screens."
    )
    payload["regions"] = list(DIS_REGIONS)
    payload["source"] = meta
    films = dict(payload.get("films") or {})
    films[film_slug] = {r: int(counts.get(r) or 0) for r in DIS_REGIONS}
    payload["films"] = films
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", default="", help="Film slug; default all active")
    parser.add_argument("--all-active", action="store_true", help="Crawl mọi phim active trong catalog")
    parser.add_argument("--date", default="", help="YYYY-MM-DD (mặc định hôm nay)")
    parser.add_argument(
        "--chain",
        choices=("galaxy", "all"),
        default="galaxy",
        help="Lọc cụm rạp (mặc định Galaxy Cinema)",
    )
    parser.add_argument(
        "--metric",
        choices=("showtimes", "cinemas"),
        default="showtimes",
        help="showtimes = số suất; cinemas = số rạp có chiếu",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.05, help="Pause giữa region requests")
    parser.add_argument("--seed-db", action="store_true", help="Chạy seed_films.py sau khi ghi JSON")
    parser.add_argument("--dry-run", action="store_true", help="Không ghi file")
    args = parser.parse_args()

    catalog = load_json(CATALOG)
    films = list(catalog.get("films") or [])
    if args.film:
        films = [f for f in films if f.get("slug") == args.film]
    elif args.all_active or not args.film:
        films = [f for f in films if f.get("active")]

    if not films:
        print("No films to crawl", file=sys.stderr)
        return 1

    show_date = args.date or date.today().isoformat()
    cache = load_moveek_cache()
    existing = load_json(SCREENS_OUT)

    print(f"Crawl screens date={show_date} chain={args.chain} metric={args.metric}")
    for film in films:
        slug = film.get("slug")
        print(f"\n=== {slug} ===")
        try:
            counts = crawl_film_screens(
                film,
                cache,
                show_date,
                args.chain,
                args.metric,
                args.workers,
                args.sleep,
            )
        except Exception as exc:
            print(f"  FAIL {slug}: {exc}", file=sys.stderr)
            continue
        existing = merge_screens(
            existing,
            str(slug),
            counts,
            {
                "provider": "moveek",
                "date": show_date,
                "chain": args.chain,
                "metric": args.metric,
            },
        )
        print(f"  → {counts}")

    if args.dry_run:
        print("\nDry-run — not writing files")
        return 0

    save_moveek_cache(cache)
    save_json(SCREENS_OUT, existing)
    print(f"\nWrote {SCREENS_OUT}")

    if args.seed_db:
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts/distribution/seed_films.py")]
        print(f">>> {' '.join(cmd)}")
        subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            check=False,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(PROJECT_ROOT / "src")},
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
