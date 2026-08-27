#!/usr/bin/env python3
"""Keyword-classify CX topics on mentions → mention_topics + daily_topic_metrics.

Usage:
  PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_topics.py
  PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_topics.py --brand glx
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.pg import get_connection  # noqa: E402

# Order = priority (first match wins for primary; we still allow multi-match)
CX_TOPIC_RULES: list[tuple[str, list[str]]] = [
    (
        "booking",
        [
            "đặt vé",
            "dat ve",
            "booking",
            "giữ ghế",
            "giu ghe",
            "ứng dụng",
            "ung dung",
            "app galaxy",
            "thanh toán",
            "thanh toan",
            "momo",
            "zalopay",
            "otp",
            "đăng nhập app",
            "dang nhap app",
        ],
    ),
    (
        "ticket_price",
        [
            "giá vé",
            "gia ve",
            "vé đắt",
            "ve dat",
            "vé rẻ",
            "ve re",
            "giảm giá",
            "giam gia",
            "ưu đãi vé",
            "uu dai ve",
            "promo vé",
            "sale vé",
            "combo giá",
            "phụ thu",
            "phu thu",
        ],
    ),
    (
        "merch",
        [
            "merch",
            "merchandise",
            "standee",
            "blind box",
            "mô hình",
            "mo hinh",
            "quà tặng",
            "qua tang",
            "poster phim",
            "gấu bông",
            "gau bong",
            "keychain",
            "móc khóa",
            "moc khoa",
        ],
    ),
    (
        "fnb",
        [
            "bắp rang",
            "bap rang",
            "popcorn",
            "combo bắp",
            "combo bap",
            "đồ ăn",
            "do an",
            "nước ngọt",
            "nuoc ngot",
            "snack",
            "f&b",
            "fnb",
            "bắp nước",
            "bap nuoc",
        ],
    ),
    (
        "facility",
        [
            "ghế ngồi",
            "ghe ngoi",
            "ghế đôi",
            "ghe doi",
            "màn hình",
            "man hinh",
            "âm thanh",
            "am thanh",
            "phòng chiếu",
            "phong chieu",
            "điều hòa",
            "dieu hoa",
            "nhà vệ sinh",
            "nha ve sinh",
            "wc ",
            "cơ sở vật chất",
            "co so vat chat",
            "rạp sạch",
            "rap sach",
            "rạp bẩn",
            "rap ban",
        ],
    ),
    (
        "service",
        [
            "nhân viên",
            "nhan vien",
            "phục vụ",
            "phuc vu",
            "thái độ",
            "thai do",
            "dịch vụ",
            "dich vu",
            "lễ tân",
            "le tan",
            "cskh",
            "chăm sóc khách",
            "cham soc khach",
            "soát vé",
            "soat ve",
            "check in",
            "check-in",
        ],
    ),
    (
        "parking",
        ["gửi xe", "gui xe", "bãi xe", "bai xe", "đậu xe", "dau xe", "parking", "chỗ đậu"],
    ),
    (
        "tech",
        ["imax", "dolby", "4dx", "screenx", "laser", "atmos"],
    ),
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def match_topics(text: str) -> list[str]:
    blob = normalize(text)
    if not blob:
        return []
    # Avoid Samsung Galaxy phone noise when no cinema context
    if "samsung galaxy" in blob or re.search(r"\bgalaxy s\d", blob):
        if not any(k in blob for k in ("cinema", "rạp", "rap ", "vé", "ve ", "chiếu")):
            return []

    hits: list[str] = []
    for slug, needles in CX_TOPIC_RULES:
        if any(n in blob for n in needles):
            hits.append(slug)
    return hits


def classify(cur, brand_slug: str | None) -> tuple[int, int]:
    cur.execute(
        "SELECT topic_slug::text, topic_id::text FROM topics WHERE topic_group = 'cx' AND is_active"
    )
    topic_ids = {r[0]: r[1] for r in cur.fetchall()}
    if not topic_ids:
        raise RuntimeError("No CX topics in DB — run galaxy_mkt_schema seed")

    if brand_slug:
        cur.execute(
            """
            SELECT m.mention_id::text, m.content_text
            FROM mentions m
            JOIN mention_brands mb ON mb.mention_id = m.mention_id
            JOIN brands b ON b.brand_id = mb.brand_id
            WHERE m.is_spam = FALSE
              AND b.brand_slug = %s
            """,
            (brand_slug,),
        )
    else:
        cur.execute(
            """
            SELECT m.mention_id::text, m.content_text
            FROM mentions m
            WHERE m.is_spam = FALSE
              AND EXISTS (SELECT 1 FROM mention_brands mb WHERE mb.mention_id = m.mention_id)
            """
        )

    rows = cur.fetchall()
    assigned = 0
    mention_with_topic = 0

    # Clear previous keyword CX tags (keep human overrides if any — we only delete keyword method)
    if brand_slug:
        cur.execute(
            """
            DELETE FROM mention_topics mt
            USING mention_brands mb, brands b, topics t
            WHERE mt.mention_id = mb.mention_id
              AND mb.brand_id = b.brand_id
              AND mt.topic_id = t.topic_id
              AND b.brand_slug = %s
              AND t.topic_group = 'cx'
              AND mt.match_method = 'keyword'
            """,
            (brand_slug,),
        )
    else:
        cur.execute(
            """
            DELETE FROM mention_topics mt
            USING topics t
            WHERE mt.topic_id = t.topic_id
              AND t.topic_group = 'cx'
              AND mt.match_method = 'keyword'
            """
        )

    for mention_id, content in rows:
        slugs = match_topics(content or "")
        slugs = [s for s in slugs if s in topic_ids]
        if not slugs:
            continue
        mention_with_topic += 1
        for slug in slugs:
            cur.execute(
                """
                INSERT INTO mention_topics (mention_id, topic_id, match_method, confidence)
                VALUES (%s::uuid, %s::uuid, 'keyword', 1.0)
                ON CONFLICT (mention_id, topic_id) DO UPDATE
                SET match_method = EXCLUDED.match_method,
                    confidence = EXCLUDED.confidence
                """,
                (mention_id, topic_ids[slug]),
            )
            assigned += 1

    return assigned, mention_with_topic


def recompute_daily_topic_metrics(cur) -> int:
    cur.execute("DELETE FROM daily_topic_metrics")
    cur.execute(
        """
        WITH base AS (
            SELECT
                (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS metric_date,
                mb.brand_id,
                mt.topic_id,
                m.platform_code,
                m.sentiment
            FROM mentions m
            JOIN mention_brands mb ON mb.mention_id = m.mention_id
            JOIN mention_topics mt ON mt.mention_id = m.mention_id
            WHERE m.is_spam = FALSE
              AND m.occurred_at IS NOT NULL
        ),
        agg_platform AS (
            SELECT
                metric_date,
                brand_id,
                topic_id,
                platform_code,
                COUNT(*) AS mention_count,
                COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count
            FROM base
            GROUP BY metric_date, brand_id, topic_id, platform_code
        ),
        agg_all AS (
            SELECT
                metric_date,
                brand_id,
                topic_id,
                'all'::text AS platform_code,
                COUNT(*) AS mention_count,
                COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count
            FROM base
            GROUP BY metric_date, brand_id, topic_id
        ),
        combined AS (
            SELECT * FROM agg_platform
            UNION ALL
            SELECT * FROM agg_all
        )
        INSERT INTO daily_topic_metrics (
            metric_date, brand_id, topic_id, platform_code,
            mention_count, positive_count, negative_count, neutral_count,
            created_at, updated_at
        )
        SELECT
            metric_date, brand_id, topic_id, platform_code,
            mention_count, positive_count, negative_count, neutral_count,
            NOW(), NOW()
        FROM combined
        """
    )
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", default="", help="Optional brand_slug filter, e.g. glx")
    args = parser.parse_args()
    brand = (args.brand or "").strip().lower() or None

    with get_connection() as conn:
        cur = conn.cursor()
        assigned, with_topic = classify(cur, brand)
        metrics_rows = recompute_daily_topic_metrics(cur)
        conn.commit()

    print(
        f"mention_topics assigned={assigned} mentions_with_topic={with_topic} "
        f"daily_topic_metrics_rows={metrics_rows}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
