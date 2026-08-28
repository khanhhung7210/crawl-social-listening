#!/usr/bin/env python3
"""Import film keyword mentions into galaxy_sl (posts/comments/mentions + mention_films).

Khác MKT: KHÔNG bắt buộc brand Galaxy/CGV. Match theo film slug (path + alias).
Có brand thì vẫn gắn mention_brands nếu detect được.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.brand_rules import detect_competitive_brands  # noqa: E402
from social_listening.film_classify import detect_sentiment  # noqa: E402
from social_listening.film_rules import (  # noqa: E402
    detect_film_slugs,
    film_listening_from,
    film_slug_from_path,
)
from social_listening.paths import DATA_DIR  # noqa: E402
from social_listening.pg import fetch_brand_map, get_connection  # noqa: E402
from social_listening.vietnam_filter import is_vietnam_relevant  # noqa: E402


def parse_dt(value) -> datetime:
    if not value:
        return datetime.utcnow()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def _int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def hashlib_fallback(item: dict) -> str:
    return hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:20]


def platform_ok(code: str, cur) -> bool:
    cur.execute("SELECT 1 FROM platforms WHERE platform_code = %s", (code,))
    return cur.fetchone() is not None


def fetch_film_map(cur) -> dict[str, str]:
    cur.execute("SELECT film_slug::text, film_id::text FROM films")
    return {row[0].lower(): row[1] for row in cur.fetchall()}


def find_mention_files(root: Path, film: str | None = None) -> list[Path]:
    paths = sorted(root.glob("*/*/processed/**/*_keyword_mentions.json")) + sorted(
        root.glob("*/processed/**/*_keyword_mentions.json")
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    if film:
        slug = film.strip().lower().replace(" ", "_")
        out = [p for p in out if slug in {part.lower() for part in p.parts}]
    # Prefer distribution film folders (exclude pure brand galaxy_cinema unless asked)
    if not film:
        dis_slugs = set(fetch_catalog_slugs())
        if dis_slugs:
            out = [p for p in out if any(s in {part.lower() for part in p.parts} for s in dis_slugs)]
    return out


def fetch_catalog_slugs() -> list[str]:
    catalog = DATA_DIR / "distribution" / "film_catalog.json"
    if not catalog.exists():
        return []
    data = json.loads(catalog.read_text(encoding="utf-8"))
    return [str(f.get("slug") or "").lower() for f in (data.get("films") or []) if f.get("slug")]


def resolve_platform(item: dict, path: Path) -> str:
    platform = str(item.get("platform") or "").lower()
    if platform in {"", "processed", "raw", "data"}:
        platform = ""
        for part in path.parts:
            if part in {"facebook", "tiktok", "threads", "youtube", "instagram", "google_maps", "news"}:
                platform = "google" if part == "google_maps" else part
                break
    if platform == "google_maps":
        platform = "google"
    return platform


def upsert_post(cur, item: dict, platform: str) -> str:
    external_id = str(item.get("post_id") or item.get("id") or item.get("url") or "")
    if not external_id:
        external_id = hashlib_fallback(item)
    text = str(item.get("post_text") or item.get("text") or item.get("content") or "")
    posted_at = parse_dt(item.get("post_created_at") or item.get("created_at"))
    url = item.get("post_url") or item.get("url") or ""
    author = item.get("page_name") or item.get("author") or item.get("author_name")
    stats = item.get("stats") or {}
    cur.execute(
        """
        INSERT INTO posts (
            platform_code, external_post_id, author_key, author_name, post_text,
            posted_at, post_url, like_count, comment_count, view_count, media_type, metadata
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'earned', %s::jsonb
        )
        ON CONFLICT (platform_code, external_post_id) DO UPDATE SET
            post_text = EXCLUDED.post_text,
            posted_at = COALESCE(EXCLUDED.posted_at, posts.posted_at),
            post_url = COALESCE(EXCLUDED.post_url, posts.post_url),
            view_count = COALESCE(EXCLUDED.view_count, posts.view_count),
            like_count = COALESCE(EXCLUDED.like_count, posts.like_count),
            comment_count = COALESCE(EXCLUDED.comment_count, posts.comment_count),
            updated_at = NOW()
        RETURNING post_id::text
        """,
        (
            platform,
            external_id,
            str(item.get("page_id") or author or ""),
            author,
            text,
            posted_at,
            url,
            _int(stats.get("like_count") or stats.get("digg_count")),
            _int(stats.get("comment_count") or item.get("comment_count")),
            _int(stats.get("view_count") or stats.get("play_count")),
            json.dumps({"source": item.get("source"), "pipeline": "distribution"}, ensure_ascii=False),
        ),
    )
    return cur.fetchone()[0]


def _link_films(cur, mention_id: str, film_slugs: list[str], film_map: dict[str, str], method: str) -> int:
    linked = 0
    for slug in film_slugs:
        film_id = film_map.get(slug.lower())
        if not film_id:
            continue
        cur.execute(
            """
            INSERT INTO mention_films (mention_id, film_id, match_method, confidence)
            VALUES (%s, %s, %s, 1.0)
            ON CONFLICT DO NOTHING
            """,
            (mention_id, film_id, method),
        )
        linked += 1
    return linked


def _link_brands(cur, mention_id: str, brands: list[str], brand_map: dict[str, str]) -> None:
    for slug in brands:
        brand_id = brand_map.get(slug)
        if not brand_id:
            continue
        cur.execute(
            """
            INSERT INTO mention_brands (mention_id, brand_id, match_method, confidence)
            VALUES (%s, %s, 'keyword', 1.0)
            ON CONFLICT DO NOTHING
            """,
            (mention_id, brand_id),
        )


def filter_films_by_listening_window(film_slugs: list[str], occurred: datetime) -> list[str]:
    """Drop films whose listening_from is after the mention timestamp (e.g. Minion meme archive)."""
    kept: list[str] = []
    for slug in film_slugs:
        start = film_listening_from(slug)
        if not start:
            kept.append(slug)
            continue
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            kept.append(slug)
            continue
        if occurred.replace(tzinfo=None) >= start_dt:
            kept.append(slug)
    return kept


def resolve_films_for_text(
    text: str,
    matches: list | None,
    path_slug: str | None,
    film_map: dict[str, str],
) -> tuple[list[str], str]:
    """Link films by text/keyword detection — không gắn chỉ vì nằm trong folder crawl."""
    match_list = matches if isinstance(matches, list) else []
    detected = detect_film_slugs(text, match_list)
    method = "alias"
    if path_slug and path_slug.lower() in film_map:
        path = path_slug.lower()
        detected_l = [s.lower() for s in detected]
        if path in detected_l:
            method = "path+alias"
        elif detected:
            # Text rõ ràng là phim khác — bỏ folder crawl
            method = "alias"
        else:
            # Folder-only: chỉ chấp nhận nếu crawl keyword cũng detect đúng phim đó
            kw_only = detect_film_slugs("", match_list)
            if path in [s.lower() for s in kw_only]:
                detected = [path_slug]
                method = "path+keyword"
            else:
                detected = []
                method = "skip-path"
    return detected, method


def upsert_mention_for_post(
    cur,
    post_id: str,
    platform: str,
    item: dict,
    brand_map: dict[str, str],
    film_map: dict[str, str],
    path_slug: str | None,
) -> tuple[bool, int]:
    text = str(item.get("post_text") or item.get("text") or "")
    matches = item.get("post_keyword_matches") or item.get("matched_search_keywords") or []
    permalink = item.get("post_url") or item.get("url")
    author_key = str(item.get("page_id") or item.get("page_name") or "")
    if not is_vietnam_relevant(text, permalink=str(permalink or ""), author=author_key, platform=platform):
        return False, 0

    film_slugs, method = resolve_films_for_text(
        text, matches if isinstance(matches, list) else [], path_slug, film_map
    )
    occurred = parse_dt(item.get("post_created_at") or item.get("created_at"))
    film_slugs = filter_films_by_listening_window(film_slugs, occurred)
    if not film_slugs:
        return False, 0

    brands = detect_competitive_brands(text, matches if isinstance(matches, list) else [])
    # News headline ≠ audience sentiment — giữ neutral để tránh khen/chê ảo trên dashboard.
    sentiment = "neutral" if platform == "news" else detect_sentiment(text)
    metadata = json.dumps(
        {"keyword_matches": matches, "pipeline": "distribution", "film_slugs": film_slugs},
        ensure_ascii=False,
        default=str,
    )

    cur.execute(
        """
        SELECT mention_id::text FROM mentions
        WHERE mention_kind = 'post' AND post_id = %s::uuid
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (post_id,),
    )
    row = cur.fetchone()
    inserted = False
    if row:
        mention_id = row[0]
        cur.execute(
            """
            UPDATE mentions SET
                content_text = %s,
                sentiment = COALESCE(%s, sentiment),
                occurred_at = COALESCE(%s, occurred_at),
                permalink = COALESCE(%s, permalink),
                metadata = %s::jsonb,
                updated_at = NOW()
            WHERE mention_id = %s::uuid
            """,
            (text or "(empty)", sentiment, occurred, permalink, metadata, mention_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO mentions (
                mention_kind, post_id, platform_code, author_key, content_text,
                media_type, sentiment, sentiment_provider, occurred_at, permalink, metadata
            ) VALUES (
                'post', %s, %s, %s, %s, 'earned', %s, 'keywords', %s, %s, %s::jsonb
            )
            RETURNING mention_id::text
            """,
            (post_id, platform, author_key, text or "(empty)", sentiment, occurred, permalink, metadata),
        )
        mention_id = cur.fetchone()[0]
        inserted = True

    linked = _link_films(cur, mention_id, film_slugs, film_map, method)
    _link_brands(cur, mention_id, brands, brand_map)
    return inserted, linked


def upsert_comment_mentions(
    cur,
    post_id: str,
    platform: str,
    comments: list,
    brand_map: dict[str, str],
    film_map: dict[str, str],
    path_slug: str | None,
) -> tuple[int, int]:
    new_count = 0
    linked_total = 0
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or c.get("comment_text") or c.get("message") or "")
        if not text.strip():
            continue
        if not is_vietnam_relevant(
            text,
            permalink=str(c.get("url") or ""),
            author=str(c.get("author") or c.get("author_name") or ""),
            platform=platform,
        ):
            continue

        film_slugs, method = resolve_films_for_text(text, None, path_slug, film_map)
        commented_at = parse_dt(c.get("created_at") or c.get("commented_at"))
        film_slugs = filter_films_by_listening_window(film_slugs, commented_at)
        if not film_slugs:
            continue

        ext = str(c.get("external_id") or c.get("id") or hashlib_fallback(c)).strip() or hashlib_fallback(c)
        brands = detect_competitive_brands(text, None)

        cur.execute(
            """
            INSERT INTO comments (
                post_id, platform_code, external_comment_id, author_key, author_name,
                comment_text, commented_at, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT (post_id, external_comment_id)
                WHERE external_comment_id IS NOT NULL AND external_comment_id <> ''
            DO UPDATE SET
                comment_text = EXCLUDED.comment_text,
                author_key = COALESCE(EXCLUDED.author_key, comments.author_key),
                author_name = COALESCE(EXCLUDED.author_name, comments.author_name),
                commented_at = COALESCE(EXCLUDED.commented_at, comments.commented_at),
                updated_at = NOW()
            RETURNING comment_id::text, (xmax = 0) AS inserted
            """,
            (
                post_id,
                platform,
                ext,
                str(c.get("author") or c.get("author_name") or ""),
                c.get("author") or c.get("author_name"),
                text,
                commented_at,
            ),
        )
        comment_id, inserted = cur.fetchone()
        sentiment = detect_sentiment(text)

        cur.execute(
            """
            SELECT mention_id::text FROM mentions
            WHERE mention_kind = 'comment' AND comment_id = %s::uuid
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (comment_id,),
        )
        mrow = cur.fetchone()
        if mrow:
            mention_id = mrow[0]
            cur.execute(
                """
                UPDATE mentions SET
                    content_text = %s,
                    sentiment = COALESCE(%s, sentiment),
                    occurred_at = COALESCE(%s, occurred_at),
                    permalink = COALESCE(%s, permalink),
                    updated_at = NOW()
                WHERE mention_id = %s::uuid
                """,
                (text, sentiment, commented_at, c.get("url"), mention_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO mentions (
                    mention_kind, post_id, comment_id, platform_code, author_key, content_text,
                    media_type, sentiment, sentiment_provider, occurred_at, permalink,
                    metadata
                ) VALUES (
                    'comment', %s, %s, %s, %s, %s, 'earned', %s, 'keywords', %s, %s,
                    %s::jsonb
                )
                RETURNING mention_id::text
                """,
                (
                    post_id,
                    comment_id,
                    platform,
                    str(c.get("author") or ""),
                    text,
                    sentiment,
                    commented_at,
                    c.get("url"),
                    json.dumps({"pipeline": "distribution", "film_slugs": film_slugs}, ensure_ascii=False),
                ),
            )
            mention_id = cur.fetchone()[0]
            if inserted:
                new_count += 1

        linked_total += _link_films(cur, mention_id, film_slugs, film_map, method)
        _link_brands(cur, mention_id, brands, brand_map)
    return new_count, linked_total


def import_file(
    cur, path: Path, brand_map: dict[str, str], film_map: dict[str, str]
) -> tuple[int, int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items") or data.get("mentions") or data.get("data") or []
    else:
        items = data

    path_slug = film_slug_from_path(path)
    posts_n = comments_n = linked_n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        platform = resolve_platform(item, path)
        if not platform or not platform_ok(platform, cur):
            continue
        post_id = upsert_post(cur, item, platform)
        inserted, linked = upsert_mention_for_post(
            cur, post_id, platform, item, brand_map, film_map, path_slug
        )
        if inserted:
            posts_n += 1
        linked_n += linked
        new_c, linked_c = upsert_comment_mentions(
            cur,
            post_id,
            platform,
            item.get("comments") or [],
            brand_map,
            film_map,
            path_slug,
        )
        comments_n += new_c
        linked_n += linked_c
    return posts_n, comments_n, linked_n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_DIR)
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--film", default="", help="Only folders matching film slug")
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        film = (args.film or "").strip() or None
        files = find_mention_files(args.root, film=film)
    files = [f for f in files if f and f.exists()]
    if not files:
        print("No film keyword mention files found.")
        return 0

    total_posts = total_comments = total_linked = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'films'
            """
        )
        if not cur.fetchone():
            raise SystemExit(
                "Table films missing. Run seed first:\n"
                "  PYTHONPATH=src python3 scripts/distribution/seed_films.py --apply-schema"
            )
        brand_map = fetch_brand_map(cur)
        film_map = fetch_film_map(cur)
        if not film_map:
            raise SystemExit("No films in DB. Run: python3 scripts/distribution/seed_films.py")

        for path in files:
            p, c, linked = import_file(cur, path, brand_map, film_map)
            total_posts += p
            total_comments += c
            total_linked += linked
            print(f"  {path}: posts={p} comments={c} film_links={linked}")

    print(
        f"Imported posts={total_posts} comments={total_comments} film_links={total_linked}"
    )

    if not args.skip_metrics:
        try:
            from importlib.util import module_from_spec, spec_from_file_location

            metrics_path = Path(__file__).resolve().parent / "metrics" / "recompute_daily_film_metrics.py"
            spec = spec_from_file_location("recompute_daily_film_metrics", metrics_path)
            if spec and spec.loader:
                mod = module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.main()
        except Exception as exc:
            print(f"Warning: could not recompute daily_film_metrics: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
