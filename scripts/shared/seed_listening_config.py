#!/usr/bin/env python3
"""Seed listening_queries, cinemas, and alert_rules from JSON files into Postgres.

Run once (or with --force to refresh):

  PYTHONPATH=src python3 scripts/shared/seed_listening_config.py
  PYTHONPATH=src python3 scripts/shared/seed_listening_config.py --force
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.pg import get_connection
from social_listening.paths import DATA_DIR

KEYWORD_FILE = DATA_DIR / "shared" / "social_keywords.json"
CINEMA_FILE = DATA_DIR / "shared" / "galaxy_cinemas.json"

BRAND_HINTS: dict[str, tuple[str, ...]] = {
    "glx": ("galaxy", "glx", "#galaxycinema", "#galaxymovie", "#galaxyrewards", "#galaxyimax", "cine chào", "cine chao"),
    "cgv": ("cgv",),
    "lotte": ("lotte",),
    "beta": ("beta",),
    "bhd": ("bhd",),
    "cinestar": ("cinestar",),
}

DEFAULT_PLATFORMS = ["facebook", "tiktok", "threads", "google_maps", "instagram", "youtube"]


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "cinema"


def _matches_brand(term: str, hints: tuple[str, ...]) -> bool:
    low = term.lower()
    return any(hint in low for hint in hints)


def _split_terms(terms: list[str], brand_slug: str) -> list[str]:
    hints = BRAND_HINTS.get(brand_slug, ())
    if not hints:
        return []
    return [term for term in terms if _matches_brand(term, hints)]


def _brand_map(cur) -> dict[str, str]:
    cur.execute("SELECT brand_slug::text, brand_id::text FROM brands")
    return {row[0]: row[1] for row in cur.fetchall()}


def seed_aggregate(cur, payload: dict, force: bool) -> None:
    cur.execute(
        "SELECT query_id FROM listening_queries WHERE query_type = 'brand' AND query_name = '__aggregate__'"
    )
    exists = cur.fetchone()
    if exists and not force:
        print("  aggregate config: already exists (skip)")
        return

    metadata = json.dumps({"full_payload": payload}, ensure_ascii=False)
    if exists:
        cur.execute(
            """
            UPDATE listening_queries
            SET metadata = %s::jsonb, updated_at = NOW(), is_active = TRUE
            WHERE query_name = '__aggregate__' AND query_type = 'brand'
            """,
            (metadata,),
        )
    else:
        cur.execute(
            """
            INSERT INTO listening_queries (query_type, query_name, keywords, hashtags, platforms, metadata)
            VALUES ('brand', '__aggregate__', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s::jsonb)
            """,
            (metadata,),
        )
    print("  aggregate config: OK")


def seed_brand_queries(cur, payload: dict, brand_ids: dict[str, str], force: bool) -> None:
    keywords = [str(x) for x in payload.get("keywords") or []]
    sub_keywords = [str(x) for x in payload.get("sub_keywords") or []]
    branch_keywords = [str(x) for x in payload.get("branch_keywords") or []]
    hashtags = [str(x) for x in payload.get("hashtags") or []]
    listening_keywords = [str(x) for x in payload.get("listening_keywords") or []]

    for brand_slug, brand_id in brand_ids.items():
        if brand_slug in ("others", "ncc"):
            continue

        cur.execute(
            """
            SELECT query_id FROM listening_queries
            WHERE query_type = 'brand' AND brand_id = %s::uuid AND query_name <> '__aggregate__'
            """,
            (brand_id,),
        )
        row = cur.fetchone()
        if row and not force:
            print(f"  brand {brand_slug}: already exists (skip)")
            continue

        brand_keywords = _split_terms(keywords, brand_slug)
        brand_sub = _split_terms(sub_keywords, brand_slug)
        brand_branch = _split_terms(branch_keywords, brand_slug)
        brand_tags = _split_terms(hashtags, brand_slug)
        brand_listen = _split_terms(listening_keywords, brand_slug) if brand_slug == "glx" else []

        if brand_slug == "glx" and not brand_keywords:
            brand_keywords = [
                "Galaxy Cinema",
                "galaxy cine",
                "rạp galaxy",
                "rap galaxy",
            ]

        kw_json = json.dumps(
            [{"value": term, "match": "exact"} for term in brand_keywords],
            ensure_ascii=False,
        )
        ht_json = json.dumps(
            [{"value": term, "kind": "brand"} for term in brand_tags],
            ensure_ascii=False,
        )
        platforms_json = json.dumps(DEFAULT_PLATFORMS, ensure_ascii=False)
        meta = json.dumps(
            {
                "sub_keywords": brand_sub,
                "branch_keywords": brand_branch,
                "listening_keywords": brand_listen,
            },
            ensure_ascii=False,
        )

        brand_name = brand_slug.upper()
        cur.execute("SELECT brand_name FROM brands WHERE brand_id = %s::uuid", (brand_id,))
        name_row = cur.fetchone()
        if name_row:
            brand_name = name_row[0]

        if row:
            cur.execute(
                """
                UPDATE listening_queries
                SET keywords = %s::jsonb,
                    hashtags = %s::jsonb,
                    platforms = %s::jsonb,
                    metadata = %s::jsonb,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE query_id = %s::uuid
                """,
                (kw_json, ht_json, platforms_json, meta, row[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO listening_queries
                    (query_type, brand_id, query_name, keywords, hashtags, platforms, metadata)
                VALUES ('brand', %s::uuid, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (brand_id, brand_name, kw_json, ht_json, platforms_json, meta),
            )
        print(f"  brand {brand_slug}: OK ({len(brand_keywords)} keywords)")


def seed_cinemas(cur, brand_ids: dict[str, str], force: bool) -> None:
    glx_id = brand_ids.get("glx")
    if not glx_id or not CINEMA_FILE.exists():
        print("  cinemas: skip (no glx brand or missing galaxy_cinemas.json)")
        return

    payload = json.loads(CINEMA_FILE.read_text(encoding="utf-8"))
    cinemas = payload.get("cinemas") if isinstance(payload, dict) else payload
    if not isinstance(cinemas, list):
        print("  cinemas: invalid file")
        return

    inserted = updated = 0
    for name in cinemas:
        query = str(name).strip()
        if not query:
            continue
        slug = slugify(query)
        meta = json.dumps({"google_maps_query": query}, ensure_ascii=False)
        cur.execute(
            """
            SELECT cinema_id FROM cinemas
            WHERE brand_id = %s::uuid AND cinema_slug = %s
            """,
            (glx_id, slug),
        )
        row = cur.fetchone()
        if row:
            if force:
                cur.execute(
                    """
                    UPDATE cinemas
                    SET cinema_name = %s, metadata = %s::jsonb, is_active = TRUE, updated_at = NOW()
                    WHERE cinema_id = %s::uuid
                    """,
                    (query, meta, row[0]),
                )
                updated += 1
            continue
        cur.execute(
            """
            INSERT INTO cinemas (brand_id, cinema_slug, cinema_name, metadata)
            VALUES (%s::uuid, %s, %s, %s::jsonb)
            """,
            (glx_id, slug, query, meta),
        )
        inserted += 1

    print(f"  cinemas: inserted={inserted} updated={updated}")


def seed_exclude_rules(cur, force: bool) -> None:
    cur.execute(
        "SELECT query_id FROM listening_queries WHERE query_type = 'crisis' AND query_name = 'exclude_rules'"
    )
    row = cur.fetchone()
    if row and not force:
        print("  exclude rules: already exists (skip)")
        return

    metadata = json.dumps(
        {
            "exclude_context": ["Honda Odyssey", "Assassin's Creed Odyssey", "Homer Odyssey"],
            "exclude_spam": [
                "spambot123",
                "marketing_fake_vn",
                "rapgalaxy",
                "rvpgalaxy",
                "tuyển dụng",
                "part-time",
                "parttime",
                "part time",
                "giao dịch trung gian",
                "GDTG",
                "hú mình (chủ nhóm)",
                "admin (chủ nhóm)",
                "book vé rạp galaxy",
                "rẻ hơn giá rạp",
                "giảm giá đến 30%",
                "pass vé",
                "pass gấp",
                "cần pass",
                "nhượng lại vé",
                "số lượng lớn",
                "tất cả các phim",
                "tất cả các rạp",
                "các suất chiếu",
                "áp dụng cho tất cả",
            ],
            "languages": ["vi", "en"],
        },
        ensure_ascii=False,
    )
    if row:
        cur.execute(
            """
            UPDATE listening_queries
            SET metadata = %s::jsonb, updated_at = NOW(), is_active = TRUE
            WHERE query_id = %s::uuid
            """,
            (metadata, row[0]),
        )
    else:
        cur.execute(
            """
            INSERT INTO listening_queries (query_type, query_name, keywords, hashtags, platforms, metadata)
            VALUES ('crisis', 'exclude_rules', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s::jsonb)
            """,
            (metadata,),
        )
    print("  exclude rules: OK")


def seed_alert_rules(cur, brand_ids: dict[str, str], force: bool) -> None:
    glx_id = brand_ids.get("glx")
    if not glx_id:
        return

    cur.execute(
        "SELECT alert_rule_id FROM alert_rules WHERE rule_name = 'default_thresholds'"
    )
    row = cur.fetchone()
    if row and not force:
        print("  alert rules: already exists (skip)")
        return

    config = json.dumps(
        {
            "thresholds": [
                {"id": "neg_spike", "label": "Negative spike", "value": 5, "unit": "%", "enabled": True},
                {"id": "buzz_spike", "label": "Buzz spike", "value": 30, "unit": "%", "enabled": True},
                {"id": "app_rating", "label": "App rating drop", "value": 3.5, "unit": "★", "enabled": True},
            ],
            "channels": {"email": "marketing@galaxystudio.vn", "teams_webhook": ""},
            "check_frequency": "hourly",
        },
        ensure_ascii=False,
    )

    if row:
        cur.execute(
            """
            UPDATE alert_rules SET config = %s::jsonb, is_active = TRUE
            WHERE alert_rule_id = %s::uuid
            """,
            (config, row[0]),
        )
    else:
        cur.execute(
            """
            INSERT INTO alert_rules (rule_name, rule_type, brand_id, config)
            VALUES ('default_thresholds', 'negative_spike', %s::uuid, %s::jsonb)
            """,
            (glx_id, config),
        )
    print("  alert rules: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite existing rows")
    args = parser.parse_args()

    if not KEYWORD_FILE.exists():
        print(f"Missing {KEYWORD_FILE}")
        return 1

    payload = json.loads(KEYWORD_FILE.read_text(encoding="utf-8"))
    print("Seeding listening config to Postgres...")

    with get_connection() as conn:
        cur = conn.cursor()
        brand_ids = _brand_map(cur)
        seed_aggregate(cur, payload, args.force)
        seed_brand_queries(cur, payload, brand_ids, args.force)
        seed_cinemas(cur, brand_ids, args.force)
        seed_exclude_rules(cur, args.force)
        seed_alert_rules(cur, brand_ids, args.force)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
