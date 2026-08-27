#!/usr/bin/env python3
"""Seed films / aliases / milestones from data/distribution into galaxy_sl."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_rules import normalize  # noqa: E402
from social_listening.paths import DATA_DIR  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402

CATALOG = DATA_DIR / "distribution" / "film_catalog.json"
MILESTONES = DATA_DIR / "distribution" / "film_milestones.json"
SCREENS = DATA_DIR / "distribution" / "film_region_screens.json"
SCHEMA = PROJECT_ROOT / "sql" / "galaxy_dis_schema.sql"


def schema_ready(cur) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = 'films'
        """
    )
    return cur.fetchone() is not None


def apply_schema_via_psycopg2() -> None:
    """Apply galaxy_dis_schema.sql without requiring psql (Windows-friendly)."""
    if not SCHEMA.exists():
        raise SystemExit(f"Missing schema file: {SCHEMA}")
    sql = SCHEMA.read_text(encoding="utf-8")
    print(f"Applying {SCHEMA} via psycopg2 …")
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
    print("Schema apply OK")


def apply_schema_via_psql() -> None:
    import os
    import shutil
    import subprocess

    if not SCHEMA.exists():
        raise SystemExit(f"Missing schema file: {SCHEMA}")
    if not shutil.which("psql"):
        apply_schema_via_psycopg2()
        return

    db = os.getenv("PGDATABASE", "galaxy_social_listening")
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER") or os.getenv("USER") or "postgres"
    print(f"Applying {SCHEMA} via psql → {db} …")
    cmd = ["psql", "-h", host, "-p", str(port), "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-f", str(SCHEMA)]
    env = os.environ.copy()
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"psql failed with code {result.returncode}")


def apply_schema() -> None:
    """Prefer psql when available; otherwise use psycopg2."""
    try:
        apply_schema_via_psql()
    except FileNotFoundError:
        apply_schema_via_psycopg2()


def deactivate_missing_films(cur, keep_slugs: set[str]) -> int:
    """Chỉ tắt phim không còn trong catalog. Không đụng slug đang có trong JSON."""
    cur.execute("SELECT film_slug::text FROM films")
    existing = [row[0] for row in cur.fetchall()]
    n = 0
    for slug in existing:
        key = (slug or "").strip().lower()
        if not key or key in keep_slugs:
            continue
        cur.execute(
            """
            UPDATE films
            SET is_active = FALSE, status = 'ended', updated_at = NOW()
            WHERE film_slug = %s
            """,
            (slug,),
        )
        print(f"  deactivated (not in catalog): {slug}")
        n += 1
    return n


def install_keep_active_guard(cur, keep_slugs: set[str]) -> None:
    """Chặn job cũ (catalog cũ, chạy trên máy DB) tắt nhầm phim đang active.

    Bất kỳ UPDATE nào set is_active=FALSE cho slug nằm trong films_keep_active
    đều bị vô hiệu hoá ở tầng DB, không phụ thuộc code phía client.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS films_keep_active (
            film_slug TEXT PRIMARY KEY,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    cur.execute("DELETE FROM films_keep_active")
    for slug in sorted(keep_slugs):
        cur.execute(
            "INSERT INTO films_keep_active (film_slug) VALUES (%s) ON CONFLICT DO NOTHING",
            (slug,),
        )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION films_keep_active_fn() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.is_active = FALSE
               AND EXISTS (SELECT 1 FROM films_keep_active k WHERE k.film_slug = NEW.film_slug)
            THEN
                NEW.is_active := TRUE;
                IF NEW.status = 'ended' AND OLD.status <> 'ended' THEN
                    NEW.status := OLD.status;
                END IF;
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql
        """
    )
    cur.execute("DROP TRIGGER IF EXISTS trg_films_keep_active ON films")
    cur.execute(
        """
        CREATE TRIGGER trg_films_keep_active BEFORE UPDATE ON films
        FOR EACH ROW EXECUTE FUNCTION films_keep_active_fn()
        """
    )


def load_region_screens() -> dict[str, dict]:
    if not SCREENS.exists():
        return {}
    payload = json.loads(SCREENS.read_text(encoding="utf-8"))
    return payload.get("films") or {}


def seed_films(cur) -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    region_screens = load_region_screens()
    n = 0
    for film in catalog.get("films") or []:
        slug = str(film.get("slug") or "").strip()
        title = str(film.get("title") or "").strip()
        if not slug or not title:
            continue
        cur.execute(
            """
            INSERT INTO films (
                film_slug, film_title, short_title, status, is_active,
                release_date, trailer_date, distributor, compare_group, metadata, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW()
            )
            ON CONFLICT (film_slug) DO UPDATE SET
                film_title = EXCLUDED.film_title,
                short_title = EXCLUDED.short_title,
                status = EXCLUDED.status,
                is_active = EXCLUDED.is_active,
                release_date = EXCLUDED.release_date,
                trailer_date = EXCLUDED.trailer_date,
                distributor = EXCLUDED.distributor,
                compare_group = EXCLUDED.compare_group,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING film_id::text
            """,
            (
                slug,
                title,
                film.get("short_title"),
                film.get("status") or "upcoming",
                bool(film.get("active", True)),
                film.get("release_date"),
                film.get("trailer_date"),
                film.get("distributor"),
                film.get("compare_group"),
                json.dumps(
                    {
                        "keyword_file": film.get("keyword_file"),
                        "aliases": film.get("aliases") or [],
                        "region_screens": region_screens.get(slug) or {},
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        film_id = cur.fetchone()[0]
        n += 1

        aliases = []
        for field in ("title", "short_title"):
            val = str(film.get(field) or "").strip()
            if val:
                aliases.append(val)
        for alias in film.get("aliases") or []:
            val = str(alias or "").strip()
            if val:
                aliases.append(val)

        for alias in aliases:
            norm = normalize(alias)
            if len(norm) < 3:
                continue
            cur.execute(
                """
                INSERT INTO film_aliases (film_id, alias, alias_norm)
                VALUES (%s, %s, %s)
                ON CONFLICT (alias_norm) DO UPDATE SET
                    film_id = EXCLUDED.film_id,
                    alias = EXCLUDED.alias
                """,
                (film_id, alias, norm),
            )
    return n


def parse_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return date.fromisoformat(str(d).strip()[:10])
    except ValueError:
        return None


def lifecycle_milestones(film: dict) -> list[dict]:
    """5 mốc lifecycle chuẩn (giống mock Distribution)."""
    rd = parse_iso(film.get("release_date"))
    if not rd:
        return []
    td = parse_iso(film.get("trailer_date")) or (rd - timedelta(days=45))
    press = parse_iso(film.get("press_date")) or (rd - timedelta(days=1))
    ann = td - timedelta(days=14) if td else rd - timedelta(days=30)

    return [
        {
            "kind": "announcement",
            "label": "Công bố dự án",
            "date": ann.isoformat(),
            "color": "#60A5FA",
        },
        {
            "kind": "trailer",
            "label": "Trailer Drop",
            "date": td.isoformat(),
            "color": "#F59E0B",
        },
        {
            "kind": "press_sneak",
            "label": "Press Tour / Sneak Show",
            "date": press.isoformat(),
            "color": "#8B5CF6",
        },
        {
            "kind": "premiere",
            "label": "Premiere / Opening Weekend",
            "date": rd.isoformat(),
            "color": "#EF4444",
        },
        {
            "kind": "w1_decay",
            "label": "W1 → W2 Decay",
            "date": (rd + timedelta(days=5)).isoformat(),
            "color": "#64748B",
        },
    ]


def load_milestone_overrides() -> dict[str, list[dict]]:
    if not MILESTONES.exists():
        return {}
    payload = json.loads(MILESTONES.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = {}
    for row in payload.get("milestones") or []:
        slug = str(row.get("film_slug") or "").strip()
        if not slug:
            continue
        grouped.setdefault(slug, []).append(row)
    return grouped


DEFAULT_PLATFORMS = ["facebook", "tiktok", "threads", "google_maps", "instagram", "youtube"]


def _term_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            val = str(item.get("value") or item.get("keyword") or item.get("term") or "").strip()
        else:
            val = str(item or "").strip()
        if val and val not in out:
            out.append(val)
    return out


def seed_movie_queries(cur, *, force: bool = False) -> int:
    """Upsert listening_queries (query_type=movie) from data/distribution/films/*.json."""
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    n = 0
    for film in catalog.get("films") or []:
        slug = str(film.get("slug") or "").strip()
        title = str(film.get("title") or "").strip()
        if not slug or not title:
            continue

        rel = str(film.get("keyword_file") or f"films/{slug}.json")
        path = DATA_DIR / "distribution" / rel
        payload: dict = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded

        keywords = _term_list(payload.get("keywords")) or [title]
        hashtags = _term_list(payload.get("hashtags"))
        kw_json = json.dumps(
            [{"value": t, "match": "exact"} for t in keywords],
            ensure_ascii=False,
        )
        ht_json = json.dumps(
            [{"value": t, "kind": "brand"} for t in hashtags],
            ensure_ascii=False,
        )
        platforms_json = json.dumps(DEFAULT_PLATFORMS, ensure_ascii=False)

        full = dict(payload)
        full.setdefault("film_title", title)
        full.setdefault("film_slug", slug)
        full.setdefault("query_type", "movie")
        full.setdefault("distribution", True)

        meta = {
            "film_slug": slug,
            "core_keywords": _term_list(payload.get("core_keywords")),
            "sub_keywords": _term_list(payload.get("sub_keywords")),
            "branch_keywords": _term_list(payload.get("branch_keywords")),
            "listening_keywords": _term_list(payload.get("listening_keywords")),
            "boost_keywords": _term_list(payload.get("boost_keywords")),
            "ambiguous_keywords": _term_list(payload.get("ambiguous_keywords")),
            "ambiguous_context_keywords": _term_list(payload.get("ambiguous_context_keywords")),
            "context_keywords": _term_list(payload.get("context_keywords")),
            "exclude_keywords": _term_list(payload.get("exclude_keywords")),
            "soft_exclude_keywords": _term_list(payload.get("soft_exclude_keywords")),
            "require_context": bool(payload.get("require_context", False)),
            "listening_from": str(payload.get("listening_from") or "").strip() or None,
            "full_payload": full,
        }
        meta_json = json.dumps(meta, ensure_ascii=False)
        is_active = bool(film.get("active", True))

        cur.execute(
            """
            SELECT query_id::text
            FROM listening_queries
            WHERE query_type = 'movie'
              AND metadata->>'film_slug' = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (slug,),
        )
        row = cur.fetchone()
        if row and not force:
            print(f"  movie query {slug}: already exists (skip)")
            continue

        if row:
            cur.execute(
                """
                UPDATE listening_queries
                SET query_name = %s,
                    keywords = %s::jsonb,
                    hashtags = %s::jsonb,
                    platforms = %s::jsonb,
                    metadata = %s::jsonb,
                    is_active = %s,
                    updated_at = NOW()
                WHERE query_id = %s::uuid
                """,
                (title, kw_json, ht_json, platforms_json, meta_json, is_active, row[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO listening_queries
                    (query_type, query_name, keywords, hashtags, platforms, metadata, is_active)
                VALUES ('movie', %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                """,
                (title, kw_json, ht_json, platforms_json, meta_json, is_active),
            )
        print(f"  movie query {slug}: OK ({len(keywords)} keywords)")
        n += 1
    return n


def seed_milestones(cur) -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    overrides = load_milestone_overrides()
    n = 0

    for film in catalog.get("films") or []:
        if not film.get("active", True):
            continue
        slug = str(film.get("slug") or "").strip()
        if not slug:
            continue

        cur.execute("SELECT film_id::text FROM films WHERE film_slug = %s", (slug,))
        found = cur.fetchone()
        if not found:
            continue
        film_id = found[0]

        cur.execute("DELETE FROM film_milestones WHERE film_id = %s::uuid", (film_id,))

        rows = overrides.get(slug) or lifecycle_milestones(film)
        for i, row in enumerate(rows):
            label = str(row.get("label") or "").strip()
            d = row.get("date")
            if not label or not d:
                continue
            kind = str(row.get("kind") or "custom")
            meta = {"kind": kind}
            cur.execute(
                """
                INSERT INTO film_milestones (film_id, label, milestone_date, color, sort_order, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (film_id, label, d, row.get("color"), i, json.dumps(meta, ensure_ascii=False)),
            )
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-schema", action="store_true", help="Apply galaxy_dis_schema.sql if films missing")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Tắt phim không còn trong film_catalog.json (mặc định: không prune — tránh seed song song/old catalog xóa nhầm)",
    )
    parser.add_argument(
        "--force-queries",
        action="store_true",
        help="Refresh listening_queries movie rows from films/*.json even if already seeded",
    )
    args = parser.parse_args()

    if not CATALOG.exists():
        raise SystemExit(f"Missing catalog: {CATALOG}")

    if args.apply_schema:
        try:
            with get_connection() as conn:
                if not schema_ready(conn.cursor()):
                    apply_schema()
                else:
                    print("Schema films already present — skip apply")
        except Exception as exc:
            print(f"Schema check failed ({exc}); trying apply …")
            apply_schema()

    with get_connection() as conn:
        cur = conn.cursor()
        if not schema_ready(cur):
            raise SystemExit(
                "Table films missing. Run:\n"
                f"  psql -d galaxy_social_listening -f {SCHEMA}\n"
                "or: PYTHONPATH=src python3 scripts/distribution/seed_films.py --apply-schema"
            )

        print(f"Catalog: {CATALOG}")
        films_n = seed_films(cur)
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        keep = {str(f.get("slug") or "").strip().lower() for f in (catalog.get("films") or []) if f.get("slug")}
        keep_active = {
            str(f.get("slug") or "").strip().lower()
            for f in (catalog.get("films") or [])
            if f.get("slug") and bool(f.get("active", True))
        }
        # Refresh guard trước khi ép trạng thái để catalog vẫn tắt được phim khi cần
        install_keep_active_guard(cur, keep_active)
        deactivated = 0
        if args.prune:
            deactivated = deactivate_missing_films(cur, keep)
        # Luôn ép trạng thái từ catalog cuối cùng — tránh job song song/catalog cũ tắt nhầm phim mới
        for film in catalog.get("films") or []:
            slug = str(film.get("slug") or "").strip()
            if not slug:
                continue
            cur.execute(
                """
                UPDATE films
                SET is_active = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE film_slug = %s
                """,
                (
                    bool(film.get("active", True)),
                    film.get("status") or "upcoming",
                    slug,
                ),
            )
        ms_n = seed_milestones(cur)
        try:
            mq_n = seed_movie_queries(cur, force=args.force_queries)
        except Exception as exc:
            # listening_queries lives in MKT schema — may be absent on bare DIS DB
            print(f"  movie queries: skip ({exc})")
            mq_n = 0
        print(
            f"Seeded films={films_n} milestones={ms_n} movie_queries={mq_n} "
            f"deactivated_old={deactivated} keep={len(keep)} guarded_active={len(keep_active)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
