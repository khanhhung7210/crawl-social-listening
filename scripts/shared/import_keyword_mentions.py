#!/usr/bin/env python3
"""Import platform *_keyword_mentions.json into galaxy_sl posts/comments/mentions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.brand_rules import (  # noqa: E402
    detect_brands,
    detect_competitive_brands,
)
from social_listening.pg import fetch_brand_map, get_connection  # noqa: E402
from social_listening.paths import DATA_DIR  # noqa: E402
from social_listening.review_utils import (  # noqa: E402
    clean_google_maps_author,
    clean_google_maps_review_text,
    is_google_maps_ui_junk,
    is_relative_only_time_label,
    parse_facebook_datetime_label,
    parse_relative_time_label,
)
from social_listening.text_utils import parse_compact_count  # noqa: E402
from social_listening.marketing_sentiment import detect_sentiment  # noqa: E402
from social_listening.vietnam_filter import is_vietnam_relevant  # noqa: E402


def raw_post_date_label(item: dict) -> str:
    return str(
        item.get("post_created_at_label")
        or item.get("created_time_label")
        or item.get("post_created_at")
        or item.get("created_at")
        or item.get("posted_at")
        or ""
    ).strip()


def resolve_post_occurred_at(item: dict, platform: str) -> tuple[datetime | None, str]:
    """Resolve post occurred_at + date_source; flag relative-only scrape labels."""
    raw_label = raw_post_date_label(item)
    # Absolute FB UI labels with an explicit year beat a wrong crawler ISO.
    if raw_label and re.search(r"\b(19|20)\d{2}\b", raw_label) and not re.match(
        r"^\d{4}-\d{2}-\d{2}T", raw_label
    ):
        fb_dt = parse_facebook_datetime_label(raw_label)
        if fb_dt is not None:
            return fb_dt, "parsed"

    if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", raw_label):
        dt = parse_dt(raw_label)
        if dt is not None:
            return dt, "parsed"

    occurred = resolve_item_occurred_at(item)
    if occurred is None:
        return None, "crawl_fallback"
    if is_relative_only_time_label(raw_label):
        return occurred, "relative_unverified"
    return occurred, "parsed"


def parse_dt(value, *, reference: datetime | None = None) -> datetime | None:
    """Parse post/comment timestamps. Never invents 'now' for bad labels.

    Supports ISO, MM/DD/YY (Threads EN UI), DD/MM/YYYY, and relative labels (13h, 2d, 3 giờ trước).
    Returns None when unknown so upserts can keep an existing occurred_at.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    text = str(value).strip()
    if not text:
        return None

    ref = reference or datetime.utcnow()

    # ISO / RFC3339
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass

    # Absolute dates — prefer MM/DD/YY for Threads English UI (e.g. 07/31/26)
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # Embedded absolute date inside noisy scraped body
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text)
    if m:
        chunk = m.group(1)
        for fmt in ("%m/%d/%y", "%m/%d/%Y", "%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(chunk, fmt)
            except ValueError:
                continue

    # Relative: 13h / 2d / 3 giờ trước
    relative = parse_relative_time_label(text, ref)
    if relative is not None:
        return relative.replace(tzinfo=None) if relative.tzinfo else relative

    fb_dt = parse_facebook_datetime_label(text, reference=ref)
    if fb_dt is not None:
        return fb_dt

    # Compact relative alone: 13h, 2d, 45m
    m = re.fullmatch(r"(\d+)\s*([smhdw])", text.casefold())
    if m:
        unit = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}[m.group(2)]
        return ref - timedelta(seconds=int(m.group(1)) * unit)

    return None


def resolve_comment_occurred_at(comment: dict, parent_item: dict | None = None) -> tuple[datetime | None, str]:
    """Return (occurred_at, date_source) for a comment/review mention."""
    dt = parse_dt(comment.get("created_at") or comment.get("commented_at"))
    if dt is not None:
        return dt, "parsed"

    dt = parse_dt((parent_item or {}).get("post_created_at"))
    if dt is not None:
        return dt, "post_inferred"

    dt = resolve_item_occurred_at(
        {
            "post_created_at": comment.get("created_at"),
            "post_text": comment.get("text") or comment.get("comment_text") or comment.get("message"),
        }
    )
    if dt is not None:
        return dt, "parsed"
    return None, "crawl_fallback"


def resolve_item_occurred_at(item: dict) -> datetime | None:
    """Best-effort post time from explicit fields, then noisy body text."""
    for key in ("post_created_at", "created_at", "posted_at", "commented_at"):
        raw = item.get(key)
        if raw and is_relative_only_time_label(str(raw)):
            continue
        dt = parse_dt(raw)
        if dt is not None:
            return dt

    # Prefer absolute date buried in scraped chrome text over relative crumbs like "13h"
    blob = " ".join(
        str(item.get(k) or "")
        for k in ("post_text", "text", "content", "body_text")
    )
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", blob)
    if m:
        dt = parse_dt(m.group(1))
        if dt is not None:
            return dt

    # Last resort: relative token near author block (avoid matching random numbers)
    m = re.search(r"(?i)\b(\d+\s*[smhdw])\b|\b(\d+\s*(?:giờ|phút|ngày|tuần)\s*trước)\b", blob)
    if m:
        dt = parse_dt(m.group(0))
        if dt is not None:
            return dt
    return None


def platform_ok(code: str, cur) -> bool:
    cur.execute("SELECT 1 FROM platforms WHERE platform_code = %s", (code,))
    return cur.fetchone() is not None


def find_mention_files(root: Path, film: str | None = None) -> list[Path]:
    paths = sorted(root.glob("*/*/processed/**/*_keyword_mentions.json")) + sorted(
        root.glob("*/processed/**/*_keyword_mentions.json")
    )
    # dedupe + skip accidental nested data/data/... mirrors on Windows hosts
    root_resolved = root.resolve()
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp in seen:
            continue
        try:
            rel = rp.relative_to(root_resolved)
        except ValueError:
            rel = None
        if rel is not None and rel.parts and rel.parts[0].lower() == "data":
            # e.g. <repo>/data/data/youtube/... — junk mirror, not real crawl output
            continue
        seen.add(rp)
        out.append(p)
    if film:
        slug = film.strip().lower().replace(" ", "_")
        out = [p for p in out if slug in {part.lower() for part in p.parts}]
    return out


def post_engagement_from_item(item: dict) -> dict[str, int | None]:
    """Map crawler/formatter stats onto posts engagement columns."""
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    return {
        "like_count": _int(stats.get("like_count") or stats.get("digg_count") or item.get("like_count")),
        "comment_count": _int(stats.get("comment_count") or item.get("comment_count")),
        "view_count": _int(stats.get("view_count") or stats.get("play_count") or item.get("view_count")),
        "share_count": _int(stats.get("share_count") or item.get("share_count")),
    }


def upsert_post(cur, item: dict, platform: str) -> str:
    external_id = str(item.get("post_id") or item.get("id") or item.get("url") or "")
    if not external_id:
        external_id = hashlib_fallback(item)
    text = str(item.get("post_text") or item.get("text") or item.get("content") or "")
    posted_at = resolve_item_occurred_at(item)
    url = item.get("post_url") or item.get("url") or ""
    author = item.get("page_name") or item.get("author") or item.get("author_name")
    engagement = post_engagement_from_item(item)
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    post_meta: dict = {"source": item.get("source")}
    for key in ("place_rating", "place_review_count", "rating", "address", "search_keyword", "sample_review_count"):
        if stats.get(key) is not None and stats.get(key) != "":
            post_meta[key] = stats.get(key)
    # posts.posted_at may be NOT NULL — utcnow is only a posts-row placeholder.
    # Mentions require a real publish time via resolve_post_occurred_at (no invent).
    posted_at_value = posted_at or datetime.utcnow()
    cur.execute(
        """
        INSERT INTO posts (
            platform_code, external_post_id, author_key, author_name, post_text,
            posted_at, post_url, like_count, comment_count, view_count, share_count,
            media_type, metadata
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'earned', %s::jsonb
        )
        ON CONFLICT (platform_code, external_post_id) DO UPDATE SET
            post_text = EXCLUDED.post_text,
            author_name = COALESCE(EXCLUDED.author_name, posts.author_name),
            posted_at = COALESCE(%s, posts.posted_at),
            post_url = COALESCE(EXCLUDED.post_url, posts.post_url),
            like_count = COALESCE(EXCLUDED.like_count, posts.like_count),
            comment_count = COALESCE(EXCLUDED.comment_count, posts.comment_count),
            view_count = COALESCE(EXCLUDED.view_count, posts.view_count),
            share_count = COALESCE(EXCLUDED.share_count, posts.share_count),
            metadata = COALESCE(posts.metadata, '{}'::jsonb) || EXCLUDED.metadata,
            updated_at = NOW()
        RETURNING post_id::text
        """,
        (
            platform,
            external_id,
            str(item.get("page_id") or author or ""),
            author,
            text,
            posted_at_value,
            url,
            engagement["like_count"],
            engagement["comment_count"],
            engagement["view_count"],
            engagement["share_count"],
            json.dumps(post_meta, ensure_ascii=False, default=str),
            posted_at,  # do not overwrite good dates with utcnow fallback
        ),
    )
    return cur.fetchone()[0]


def hashlib_fallback(item: dict) -> str:
    import hashlib

    return hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _int(value) -> int | None:
    return parse_compact_count(value)


def _link_brands(cur, mention_id: str, brands: list[str], brand_map: dict[str, str]) -> None:
    """Replace brand assignments for one mention with the current detection result."""
    cur.execute(
        "DELETE FROM mention_brands WHERE mention_id = %s::uuid",
        (mention_id,),
    )
    seen: set[str] = set()
    for slug in brands:
        if slug in seen:
            continue
        seen.add(slug)
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


def upsert_mention_for_post(
    cur, post_id: str, platform: str, item: dict, brand_map: dict[str, str]
) -> bool:
    """Upsert post-level mention. Returns True if newly inserted."""
    text = str(item.get("post_text") or item.get("text") or "")
    # Google Maps place pages are containers only — real signal lives in review comments.
    if item.get("skip_post_mention") or (platform == "google" and is_google_maps_ui_junk(text)):
        return False
    if platform == "google" and not item.get("force_post_mention"):
        return False
    matches = item.get("post_keyword_matches") or item.get("matched_search_keywords") or []
    permalink = item.get("post_url") or item.get("url")
    author_key = str(item.get("page_id") or item.get("page_name") or "")
    if not is_vietnam_relevant(text, permalink=str(permalink or ""), author=author_key, platform=platform):
        return False
    brands = detect_competitive_brands(
        text,
        matches if isinstance(matches, list) else [],
        permalink=str(permalink or ""),
        author=author_key,
        platform=platform,
    )
    if not brands:
        return False
    sentiment = detect_sentiment(text)
    occurred, date_source = resolve_post_occurred_at(item, platform)
    meta: dict = {"keyword_matches": matches, "date_source": date_source}
    if raw_label := raw_post_date_label(item):
        meta["date_label"] = raw_label
    if item.get("rating") is not None:
        meta["rating"] = item.get("rating")
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    like_v = _int(stats.get("like_count") or stats.get("digg_count") or item.get("like_count"))
    comment_v = _int(stats.get("comment_count") or item.get("comment_count"))
    view_v = _int(stats.get("view_count") or stats.get("play_count") or item.get("view_count"))
    share_v = _int(stats.get("share_count") or item.get("share_count"))
    if like_v is not None:
        meta["like_count"] = like_v
    if comment_v is not None:
        meta["comment_count"] = comment_v
    if view_v is not None:
        meta["view_count"] = view_v
    if share_v is not None:
        meta["share_count"] = share_v
    metadata = json.dumps(meta, ensure_ascii=False, default=str)
    if occurred is None:
        return False
    if date_source in {"crawl_fallback", "relative_unverified"}:
        # Still refresh text/permalink, but never trust relative-only scrape dates.
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
        if not row:
            return False
        mention_id = row[0]
        cur.execute(
            """
            UPDATE mentions SET
                content_text = %s,
                sentiment = COALESCE(%s, sentiment),
                permalink = COALESCE(%s, permalink),
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE mention_id = %s::uuid
            """,
            (text or "(empty)", sentiment, permalink, metadata, mention_id),
        )
        _link_brands(cur, mention_id, brands, brand_map)
        return False
    occurred_value = occurred
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
    if row:
        mention_id = row[0]
        cur.execute(
            """
            UPDATE mentions SET
                content_text = %s,
                sentiment = COALESCE(%s, sentiment),
                occurred_at = COALESCE(%s, occurred_at),
                permalink = COALESCE(%s, permalink),
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE mention_id = %s::uuid
            """,
            (text or "(empty)", sentiment, occurred, permalink, metadata, mention_id),
        )
        _link_brands(cur, mention_id, brands, brand_map)
        return False

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
        (
            post_id,
            platform,
            author_key,
            text or "(empty)",
            sentiment,
            occurred_value,
            permalink,
            metadata,
        ),
    )
    mention_id = cur.fetchone()[0]
    _link_brands(cur, mention_id, brands, brand_map)
    return True


def upsert_comment_mentions(
    cur, post_id: str, platform: str, comments: list, brand_map: dict[str, str], parent_matches: list,
    parent_item: dict | None = None,
) -> tuple[int, int]:
    """Upsert comments + comment mentions. Returns (new_comments, total_processed)."""
    new_count = 0
    total = 0
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or c.get("comment_text") or c.get("message") or "")
        if platform == "google":
            text = clean_google_maps_review_text(text)
            if c.get("author"):
                c = {**c, "author": clean_google_maps_author(c.get("author"))}
        if platform == "google":
            text = clean_google_maps_review_text(text)
            if c.get("author"):
                c = {**c, "author": clean_google_maps_author(c.get("author"))}
        if not text.strip() or (platform == "google" and is_google_maps_ui_junk(text)):
            continue
        # Threads reply pages quote the parent post — don't import parent as comment on child thread.
        if platform == "threads":
            post_author = str((parent_item or {}).get("page_name") or "").lstrip("@").casefold()
            comment_author = str(c.get("author") or "").lstrip("@").casefold()
            if post_author and comment_author and comment_author != post_author:
                parent_text = str((parent_item or {}).get("post_text") or "").strip()
                if parent_text and text.strip() == parent_text.strip():
                    continue
        commented_at, date_source = resolve_comment_occurred_at(c, parent_item)
        if date_source == "crawl_fallback":
            if platform != "google":
                continue
            commented_at = commented_at or datetime.utcnow()
        ext = str(c.get("external_id") or c.get("id") or hashlib_fallback(c)).strip()
        if not ext:
            ext = hashlib_fallback(c)

        cur.execute("SELECT post_url FROM posts WHERE post_id = %s::uuid", (post_id,))
        parent_row = cur.fetchone()
        parent_url = str((parent_row or [None])[0] or "").strip() or None
        comment_url = str(c.get("url") or "").strip() or parent_url

        brands = detect_competitive_brands(
            text,
            None,
            permalink=str(comment_url or ""),
            author=str(c.get("author") or c.get("author_name") or ""),
            platform=platform,
        )
        if not brands and platform == "google":
            parent = parent_item or {}
            stats = parent.get("stats") if isinstance(parent.get("stats"), dict) else {}
            place_blob = " ".join(
                [
                    str(parent.get("page_name") or ""),
                    str(parent.get("post_text") or ""),
                    str(parent.get("post_url") or parent.get("url") or ""),
                    str(parent.get("search_keyword") or ""),
                    str(stats.get("search_keyword") or ""),
                ]
            )
            brands = detect_competitive_brands(
                place_blob,
                None,
                permalink=str(parent.get("post_url") or parent.get("url") or ""),
                author=str(parent.get("page_name") or ""),
                platform=platform,
            )
        if not brands:
            continue

        if not is_vietnam_relevant(
            text,
            permalink=str(comment_url or ""),
            author=str(c.get("author") or c.get("author_name") or ""),
            platform=platform,
        ):
            continue

        comment_meta = json.dumps(
            {
                **({"rating": c["rating"]} if c.get("rating") is not None else {}),
                "date_source": date_source,
            },
            ensure_ascii=False,
            default=str,
        )
        cur.execute(
            """
            INSERT INTO comments (
                post_id, platform_code, external_comment_id, author_key, author_name,
                comment_text, commented_at, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (post_id, external_comment_id)
                WHERE external_comment_id IS NOT NULL AND external_comment_id <> ''
            DO UPDATE SET
                comment_text = EXCLUDED.comment_text,
                author_key = COALESCE(EXCLUDED.author_key, comments.author_key),
                author_name = COALESCE(EXCLUDED.author_name, comments.author_name),
                commented_at = COALESCE(EXCLUDED.commented_at, comments.commented_at),
                metadata = comments.metadata || EXCLUDED.metadata,
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
                comment_meta,
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
        mention_meta = comment_meta
        occurred_value = commented_at
        if mrow:
            mention_id = mrow[0]
            cur.execute(
                """
                UPDATE mentions SET
                    content_text = %s,
                    sentiment = COALESCE(%s, sentiment),
                    occurred_at = %s,
                    permalink = COALESCE(%s, permalink),
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE mention_id = %s::uuid
                """,
                (text, sentiment, occurred_value, comment_url, mention_meta, mention_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO mentions (
                    mention_kind, post_id, comment_id, platform_code, author_key, content_text,
                    media_type, sentiment, sentiment_provider, occurred_at, permalink, metadata
                ) VALUES (
                    'comment', %s, %s, %s, %s, %s, 'earned', %s, 'keywords', %s, %s, %s::jsonb
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
                    occurred_value,
                    comment_url,
                    mention_meta,
                ),
            )
            mention_id = cur.fetchone()[0]
            if inserted:
                new_count += 1

        _link_brands(cur, mention_id, brands, brand_map)
        total += 1
    return new_count, total


def import_file(cur, path: Path, brand_map: dict[str, str]) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items") or data.get("mentions") or data.get("data") or []
    else:
        items = data
    posts_n = 0
    comments_n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or path.parts[-4] if len(path.parts) > 4 else "facebook").lower()
        if platform in {"processed", "raw", "data"}:
            # guess from path: data/<platform>/processed/...
            for part in path.parts:
                if part in {"facebook", "tiktok", "threads", "youtube", "instagram", "google_maps"}:
                    platform = "google" if part == "google_maps" else part
                    break
        if platform == "google_maps":
            platform = "google"
        if not platform_ok(platform, cur):
            continue
        post_id = upsert_post(cur, item, platform)
        if upsert_mention_for_post(cur, post_id, platform, item, brand_map):
            posts_n += 1
        matches = item.get("post_keyword_matches") or []
        _new_c, processed_c = upsert_comment_mentions(
            cur, post_id, platform, item.get("comments") or [], brand_map, matches if isinstance(matches, list) else [], item
        )
        comments_n += processed_c
    return posts_n, comments_n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_DIR)
    parser.add_argument("--file", type=Path, default=None, help="Single keyword mentions JSON")
    parser.add_argument(
        "--film",
        default="",
        help="Only import folders matching film slug, e.g. galaxy_cinema (skips pizza/meili leftovers)",
    )
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        film = (args.film or "").strip() or "galaxy_cinema"
        files = find_mention_files(args.root, film=film)
    files = [f for f in files if f and f.exists()]
    if not files:
        print("No keyword mention files found.")
        return 0

    total_posts = total_comments = 0
    with get_connection() as conn:
        cur = conn.cursor()
        brand_map = fetch_brand_map(cur)
        for path in files:
            p, c = import_file(cur, path, brand_map)
            total_posts += p
            total_comments += c
            print(f"  {path}: posts={p} comments={c}")

    print(f"Imported posts={total_posts} comment_mentions={total_comments}")
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "recompute_daily_brand_metrics",
            PROJECT_ROOT / "scripts" / "marketing" / "metrics" / "recompute_daily_brand_metrics.py",
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            old_argv = sys.argv[:]
            try:
                # Avoid leaking importer flags (--film/--file) into metrics CLI.
                sys.argv = [str(PROJECT_ROOT / "scripts" / "marketing" / "metrics" / "recompute_daily_brand_metrics.py")]
                spec.loader.exec_module(mod)
                mod.main()
            finally:
                sys.argv = old_argv
    except Exception as exc:
        print(f"Warning: could not recompute daily metrics: {exc}")

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "build_campaign_tracking",
            PROJECT_ROOT / "scripts" / "marketing" / "classify" / "build_campaign_tracking.py",
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            old_argv = sys.argv[:]
            try:
                sys.argv = [
                    str(PROJECT_ROOT / "scripts" / "marketing" / "classify" / "build_campaign_tracking.py"),
                    "--brand",
                    "glx",
                ]
                spec.loader.exec_module(mod)
                if hasattr(mod, "main"):
                    mod.main()
            finally:
                sys.argv = old_argv
    except Exception as exc:
        print(f"Warning: could not build campaign tracking: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
