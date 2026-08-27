#!/usr/bin/env python3
"""Import App Store / Google Play crawl JSON into galaxy_sl.app_reviews + snapshots.

Expects output from crawl_app_reviews.py (live store scores). Does not invent
App Store overall rating from a biased review subset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.pg import fetch_app_id, fetch_brand_map, get_connection  # noqa: E402

BRAND_CODE_TO_SLUG = {
    "GLX": "glx",
    "CGV": "cgv",
    "Lotte": "lotte",
    "LOTTE": "lotte",
    "Beta": "beta",
    "BETA": "beta",
    "BHD": "bhd",
    "Cinestar": "cinestar",
    "CINESTAR": "cinestar",
}

TOPIC_RULES = [
    ("app_login", ["đăng nhập", "dang nhap", "otp", "mật khẩu", "mat khau", "sđt", "sdt"]),
    (
        "app_booking_error",
        ["đặt vé", "dat ve", "giữ ghế", "giu ghe", "không có vé", "booking", "book vé", "book ve"],
    ),
    ("app_payment", ["thanh toán", "thanh toan", "trừ tiền", "tru tien", "momo", "payment"]),
    (
        "app_crash",
        ["crash", "văng app", "bị văng", "bi vang", "force close", "lỗi kết nối", "loi ket noi", "rớt mạng", "rot mang"],
    ),
    ("app_slow", ["lag", "chậm", "cham", "load chậm", "load cham", "loading"]),
    (
        "app_ui",
        ["giao diện", "giao dien", "user flow", "khó dùng", "kho dung", "ui/ux", "ux "],
    ),
]

# Review khen rạp / ghế / màn chiếu — không phải topic app
_FACILITY_HINTS = (
    "ghế",
    "ghe ",
    "rạp",
    "rap ",
    "màn hình",
    "man hinh",
    "âm thanh",
    "am thanh",
    "phòng chiếu",
    "phong chieu",
    "mỏi mắt",
    "moi mat",
)
_APP_HINTS = (
    "app",
    "ứng dụng",
    "ung dung",
    "đăng nhập",
    "dang nhap",
    "otp",
    "đặt vé",
    "dat ve",
    "thanh toán",
    "thanh toan",
    "crash",
    "lag",
    "giao diện",
    "giao dien",
)


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    text = str(value).strip()
    # Normalize Z / fractional seconds for fromisoformat
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        # Keep up to microseconds then timezone
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def sentiment_from_score(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 4:
        return "positive"
    if score <= 2:
        return "negative"
    return "neutral"


def stable_review_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def hist_to_json(hist: list | dict | None) -> dict:
    if isinstance(hist, dict) and hist:
        out = {}
        for i in range(1, 6):
            out[str(i)] = int(hist.get(str(i), hist.get(i, 0)) or 0)
        if any(out.values()):
            return out
    if not hist or not isinstance(hist, list) or len(hist) < 5:
        return {}
    # Google Play / App Store list form: [1★, 2★, 3★, 4★, 5★]
    return {str(i + 1): int(hist[i] or 0) for i in range(5)}


def classify_topic(text: str, topic_ids: dict[str, str]) -> str | None:
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    # "màn hình nghiền / ghế ngồi" = cơ sở rạp, không phải UI app
    if any(h in lowered for h in _FACILITY_HINTS) and not any(h in lowered for h in _APP_HINTS):
        return None
    for slug, needles in TOPIC_RULES:
        if any(n in lowered for n in needles):
            return topic_ids.get(slug)
    return None


def reclassify_existing(cur, topic_ids: dict[str, str]) -> int:
    cur.execute(
        """
        SELECT r.app_review_id::text, COALESCE(r.title, '') || ' ' || COALESCE(r.review_text, '')
        FROM app_reviews r
        JOIN mobile_apps a ON a.app_id = r.app_id
        JOIN brands b ON b.brand_id = a.brand_id
        WHERE b.brand_slug = 'glx'
        """
    )
    updated = 0
    for review_id, blob in cur.fetchall():
        topic_id = classify_topic(blob, topic_ids)
        cur.execute(
            """
            UPDATE app_reviews
            SET topic_id = %s::uuid, updated_at = NOW()
            WHERE app_review_id = %s::uuid
              AND topic_id IS DISTINCT FROM %s::uuid
            """,
            (topic_id, review_id, topic_id),
        )
        updated += cur.rowcount
    return updated


def upsert_snapshot(cur, app_id: str, payload: dict, snapshot_date: date) -> None:
    hist = payload.get("histogram")
    cur.execute(
        """
        INSERT INTO app_rating_snapshots (
            app_id, snapshot_date, avg_rating, ratings_count, reviews_count,
            histogram, version_latest
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (app_id, snapshot_date) DO UPDATE SET
            avg_rating = EXCLUDED.avg_rating,
            ratings_count = EXCLUDED.ratings_count,
            reviews_count = EXCLUDED.reviews_count,
            histogram = EXCLUDED.histogram,
            version_latest = EXCLUDED.version_latest
        """,
        (
            app_id,
            snapshot_date,
            payload.get("score"),
            payload.get("ratings"),
            payload.get("reviews"),
            json.dumps(hist_to_json(hist)),
            payload.get("version"),
        ),
    )


def insert_review(
    cur,
    *,
    app_id: str,
    external_id: str,
    author: str | None,
    rating: int,
    title: str | None,
    text: str | None,
    version: str | None,
    reviewed_at: datetime | None,
    thumbs: int | None,
    reply: str | None,
    topic_id: str | None,
    raw: dict,
) -> bool:
    # If an older sample row exists (different external id, same author/rating/text),
    # reuse that row so live crawl IDs replace hashes instead of doubling.
    cur.execute(
        """
        SELECT app_review_id::text, external_review_id
        FROM app_reviews
        WHERE app_id = %s::uuid
          AND COALESCE(author_name, '') = COALESCE(%s, '')
          AND rating = %s
          AND COALESCE(review_text, '') = COALESCE(%s, '')
          AND (external_review_id IS DISTINCT FROM %s)
        LIMIT 1
        """,
        (app_id, author, rating, text, external_id),
    )
    twin = cur.fetchone()
    if twin:
        cur.execute(
            """
            UPDATE app_reviews SET
                external_review_id = %s,
                title = %s,
                app_version = %s,
                reviewed_at = COALESCE(%s, reviewed_at),
                thumbs_up_count = %s,
                developer_reply = %s,
                topic_id = %s::uuid,
                sentiment = %s,
                raw_payload = %s::jsonb,
                updated_at = NOW()
            WHERE app_review_id = %s::uuid
            """,
            (
                external_id,
                title,
                version,
                reviewed_at,
                thumbs,
                reply,
                topic_id,
                sentiment_from_score(rating),
                json.dumps(raw, ensure_ascii=False, default=str),
                twin[0],
            ),
        )
        return True

    cur.execute(
        """
        INSERT INTO app_reviews (
            app_id, external_review_id, author_name, rating, title, review_text,
            app_version, reviewed_at, thumbs_up_count, developer_reply,
            topic_id, sentiment, raw_payload
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        )
        ON CONFLICT (app_id, external_review_id) WHERE external_review_id IS NOT NULL
        DO UPDATE SET
            rating = EXCLUDED.rating,
            review_text = EXCLUDED.review_text,
            title = EXCLUDED.title,
            app_version = EXCLUDED.app_version,
            reviewed_at = COALESCE(EXCLUDED.reviewed_at, app_reviews.reviewed_at),
            thumbs_up_count = EXCLUDED.thumbs_up_count,
            developer_reply = EXCLUDED.developer_reply,
            topic_id = EXCLUDED.topic_id,
            sentiment = EXCLUDED.sentiment,
            raw_payload = EXCLUDED.raw_payload,
            updated_at = NOW()
        """,
        (
            app_id,
            external_id,
            author,
            rating,
            title,
            text,
            version,
            reviewed_at,
            thumbs,
            reply,
            topic_id,
            sentiment_from_score(rating),
            json.dumps(raw, ensure_ascii=False, default=str),
        ),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "app-reviews" / "live.json",
    )
    parser.add_argument(
        "--reclassify-only",
        action="store_true",
        help="Only re-run keyword topic classification on existing Galaxy reviews",
    )
    args = parser.parse_args()

    if args.reclassify_only:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT topic_slug::text, topic_id::text FROM topics WHERE topic_group = 'app'"
            )
            topic_ids = {r[0]: r[1] for r in cur.fetchall()}
            n = reclassify_existing(cur, topic_ids)
            conn.commit()
        print(f"Reclassified topics updated={n}")
        return 0

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        print(
            "Run: PYTHONPATH=src python3 scripts/marketing/crawl/reviews/crawl_app_reviews.py",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    snapshot_date = date.today()
    inserted = 0
    snapshots = 0

    # Prefer live crawl keys; only fall back to legacy sample keys if live missing.
    live_play = payload.get("galaxy_google_play_reviews")
    play_reviews = list(
        live_play
        if live_play is not None
        else (
            (payload.get("galaxy_google_play_reviews_sample") or [])
            + (payload.get("galaxy_google_play_low_star_sample") or [])
        )
    )

    live_ios = payload.get("galaxy_app_store_reviews")
    ios_reviews = list(
        live_ios
        if live_ios is not None
        else (payload.get("galaxy_app_store_reviews_sample") or [])
    )
    ios_meta = payload.get("galaxy_app_store") or payload.get("galaxy_app_store_meta") or {}
    glx_play = payload.get("galaxy_google_play") or {}
    glx_play_store_id = str(glx_play.get("appId") or "com.galaxy.cinema")

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT topic_slug::text, topic_id::text FROM topics WHERE topic_group = 'app'")
        topic_ids = {r[0]: r[1] for r in cur.fetchall()}
        brand_map = fetch_brand_map(cur)

        # Play snapshots (skip Galaxy if also present in galaxy_google_play to avoid double work)
        for row in payload.get("competitor_google_play_summary") or []:
            store_app_id = str(row.get("appId") or "")
            if store_app_id == glx_play_store_id and glx_play:
                continue
            app_id = fetch_app_id(cur, "google_play", store_app_id)
            if not app_id:
                slug = BRAND_CODE_TO_SLUG.get(str(row.get("brand") or ""), "")
                brand_id = brand_map.get(slug)
                if brand_id and store_app_id:
                    cur.execute(
                        """
                        INSERT INTO mobile_apps (brand_id, store, store_app_id, app_name, is_primary)
                        VALUES (%s, 'google_play', %s, %s, FALSE)
                        ON CONFLICT (store, store_app_id, country_code) DO UPDATE
                        SET app_name = EXCLUDED.app_name
                        RETURNING app_id::text
                        """,
                        (brand_id, store_app_id, row.get("title") or store_app_id),
                    )
                    app_id = cur.fetchone()[0]
            if app_id:
                upsert_snapshot(cur, app_id, row, snapshot_date)
                snapshots += 1

        if glx_play:
            app_id = fetch_app_id(cur, "google_play", glx_play_store_id)
            if app_id:
                upsert_snapshot(cur, app_id, glx_play, snapshot_date)
                snapshots += 1

        play_app_id = fetch_app_id(cur, "google_play", "com.galaxy.cinema")
        for rev in play_reviews:
            if not play_app_id:
                break
            score = int(rev.get("score") or 0)
            if score < 1 or score > 5:
                continue
            text = rev.get("content") or ""
            author = rev.get("userName") or ""
            at = parse_dt(rev.get("at"))
            ext = str(rev.get("reviewId") or "").strip() or stable_review_id(
                "gp", author, str(at), text[:80]
            )
            topic_id = classify_topic(text, topic_ids)
            insert_review(
                cur,
                app_id=play_app_id,
                external_id=ext,
                author=author,
                rating=score,
                title=None,
                text=text,
                version=rev.get("version"),
                reviewed_at=at,
                thumbs=rev.get("thumbsUpCount"),
                reply=rev.get("replyContent"),
                topic_id=topic_id,
                raw=rev,
            )
            inserted += 1

        ios_app_id = fetch_app_id(cur, "appstore", "593312549")
        for rev in ios_reviews:
            if not ios_app_id:
                break
            rating = int(rev.get("rating") or 0)
            if rating < 1 or rating > 5:
                continue
            text = rev.get("review") or ""
            author = rev.get("author") or ""
            at = parse_dt(rev.get("updated"))
            ext = str(rev.get("id") or "").strip() or stable_review_id(
                "ios", author, str(at), text[:80]
            )
            topic_id = classify_topic(f"{rev.get('title') or ''} {text}", topic_ids)
            insert_review(
                cur,
                app_id=ios_app_id,
                external_id=ext,
                author=author,
                rating=rating,
                title=rev.get("title"),
                text=text,
                version=rev.get("version"),
                reviewed_at=at,
                thumbs=None,
                reply=rev.get("replyContent"),
                topic_id=topic_id,
                raw=rev,
            )
            inserted += 1

        # Competitor App Store snapshots (CGV/Lotte/Beta/BHD)
        glx_ios_id = str(ios_meta.get("app_id") or "593312549")
        for row in payload.get("competitor_app_store_summary") or []:
            store_app_id = str(row.get("app_id") or row.get("trackId") or "")
            if not store_app_id:
                continue
            if store_app_id == glx_ios_id and ios_meta:
                continue
            app_id = fetch_app_id(cur, "appstore", store_app_id)
            if not app_id:
                slug = BRAND_CODE_TO_SLUG.get(str(row.get("brand") or ""), "")
                brand_id = brand_map.get(slug)
                if brand_id:
                    cur.execute(
                        """
                        INSERT INTO mobile_apps (brand_id, store, store_app_id, app_name, is_primary)
                        VALUES (%s, 'appstore', %s, %s, FALSE)
                        ON CONFLICT (store, store_app_id, country_code) DO UPDATE
                        SET app_name = EXCLUDED.app_name
                        RETURNING app_id::text
                        """,
                        (brand_id, store_app_id, row.get("app_name") or store_app_id),
                    )
                    app_id = cur.fetchone()[0]
            score = row.get("score") or row.get("averageUserRating")
            if app_id and score is not None:
                upsert_snapshot(
                    cur,
                    app_id,
                    {
                        "score": score,
                        "ratings": row.get("ratings") or row.get("userRatingCount"),
                        "reviews": row.get("reviews"),
                        "histogram": row.get("histogram"),
                        "version": row.get("version"),
                    },
                    snapshot_date,
                )
                snapshots += 1

        if ios_app_id:
            explicit_score = ios_meta.get("score") or ios_meta.get("averageUserRating")
            explicit_ratings = ios_meta.get("ratings") or ios_meta.get("userRatingCount")
            if explicit_score is not None:
                upsert_snapshot(
                    cur,
                    ios_app_id,
                    {
                        "score": explicit_score,
                        "ratings": explicit_ratings,
                        "reviews": ios_meta.get("reviews") or len(ios_reviews) or None,
                        "histogram": ios_meta.get("histogram"),
                        "version": ios_meta.get("version") or ios_meta.get("version_latest"),
                    },
                    snapshot_date,
                )
                snapshots += 1
            else:
                print(
                    "Skip App Store snapshot: crawl has no store-level score "
                    "(will not derive from review subset).",
                    file=sys.stderr,
                )

        reclass = reclassify_existing(cur, topic_ids)
        conn.commit()

    print(
        f"Imported app reviews={inserted}, snapshots={snapshots}, "
        f"topics_reclassified={reclass} from {args.input}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
