#!/usr/bin/env python3
"""Classify gift-demand signals → gift_leads only (no cinema SL mixing).

Usage:
  PYTHONPATH=src python3 scripts/mkt/classify/classify_gift_leads.py --purge-non-leads
  PYTHONPATH=src python3 scripts/mkt/classify/classify_gift_leads.py --from-raw data/facebook/raw/galaxy_cinema/20260915
  PYTHONPATH=src python3 scripts/mkt/classify/classify_gift_leads.py --platform facebook --days 30
"""

from __future__ import annotations

import argparse
import json
import re
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

from social_listening.gift_leads import match_gift_intent  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402


def ensure_table(cur) -> None:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'gift_leads'
        """
    )
    if cur.fetchone():
        return
    migration = PROJECT_ROOT / "sql" / "migrations" / "001_gift_leads.sql"
    if not migration.is_file():
        raise RuntimeError(f"gift_leads table missing and no migration at {migration}")
    cur.execute(migration.read_text(encoding="utf-8"))


def fetch_candidates(cur, days: int | None, platform: str | None) -> list[tuple]:
    clauses = ["m.is_spam = FALSE", "COALESCE(m.content_text, '') <> ''"]
    params: list = []
    if days and days > 0:
        clauses.append("m.occurred_at >= NOW() - (%s || ' days')::interval")
        params.append(str(days))
    if platform:
        clauses.append("m.platform_code = %s")
        params.append(platform)

    where = " AND ".join(clauses)
    cur.execute(
        f"""
        SELECT
            m.mention_id::text,
            m.platform_code,
            COALESCE(m.author_key, '') AS author_key,
            COALESCE(
                NULLIF(p.author_name, ''),
                NULLIF(c.author_name, ''),
                m.author_key,
                ''
            ) AS author_name,
            m.content_text,
            m.permalink,
            m.occurred_at,
            COALESCE(p.post_url, m.permalink) AS profile_hint
        FROM mentions m
        LEFT JOIN posts p ON p.post_id = m.post_id
        LEFT JOIN comments c ON c.comment_id = m.comment_id
        WHERE {where}
        ORDER BY m.occurred_at DESC NULLS LAST
        """,
        params,
    )
    return cur.fetchall()


def _update_lead_sql() -> str:
    return """
        author_name = COALESCE(%s, gift_leads.author_name),
        profile_url = COALESCE(%s, gift_leads.profile_url),
        entity_type = %s,
        intent_tag = %s,
        signal_score = GREATEST(gift_leads.signal_score, %s),
        evidence_text = %s,
        evidence_url = COALESCE(%s, gift_leads.evidence_url),
        evidence_at = COALESCE(%s, gift_leads.evidence_at),
        mention_id = COALESCE(gift_leads.mention_id, %s::uuid),
        contact_phone = COALESCE(%s, gift_leads.contact_phone),
        contact_email = COALESCE(%s, gift_leads.contact_email),
        contact_zalo = COALESCE(%s, gift_leads.contact_zalo),
        matched_keywords = %s::jsonb,
        updated_at = NOW()
    """


def upsert_lead(cur, row: tuple) -> bool:
    (
        mention_id,
        platform_code,
        author_key,
        author_name,
        content_text,
        permalink,
        occurred_at,
        profile_hint,
    ) = row

    matched = match_gift_intent(content_text or "", author_name=author_name or "")
    if not matched:
        return False

    evidence_url = (permalink or "").strip() or None
    profile_url = (profile_hint or permalink or "").strip() or None
    keywords_json = json.dumps(matched.matched_keywords, ensure_ascii=False)
    author_key = author_key or ""
    meta = json.dumps({"source": "gift_only", "clusters": matched.clusters_hit}, ensure_ascii=False)

    update_params = (
        author_name or None,
        profile_url,
        matched.entity_type,
        matched.intent_tag,
        matched.signal_score,
        content_text,
        evidence_url,
        occurred_at,
        mention_id,
        matched.contact_phone,
        matched.contact_email,
        matched.contact_zalo,
        keywords_json,
    )

    if mention_id:
        cur.execute(
            f"""
            UPDATE gift_leads
            SET {_update_lead_sql()},
                metadata = COALESCE(gift_leads.metadata, '{{}}'::jsonb) || %s::jsonb
            WHERE mention_id = %s::uuid
              AND status IN ('new', 'contacted')
            """,
            (*update_params, meta, mention_id),
        )
        if cur.rowcount:
            return True

    if evidence_url:
        cur.execute(
            f"""
            UPDATE gift_leads
            SET {_update_lead_sql()},
                metadata = COALESCE(gift_leads.metadata, '{{}}'::jsonb) || %s::jsonb
            WHERE platform_code = %s
              AND author_key = %s
              AND evidence_url = %s
              AND intent_tag = %s
              AND status IN ('new', 'contacted')
            """,
            (
                *update_params,
                meta,
                platform_code,
                author_key,
                evidence_url,
                matched.intent_tag,
            ),
        )
        if cur.rowcount:
            return True

    cur.execute(
        """
        INSERT INTO gift_leads (
            platform_code, author_key, author_name, profile_url,
            entity_type, intent_tag, signal_score,
            evidence_text, evidence_url, evidence_at, mention_id,
            contact_phone, contact_email, contact_zalo,
            matched_keywords, status, metadata, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s::uuid,
            %s, %s, %s,
            %s::jsonb, 'new', %s::jsonb, NOW()
        )
        """,
        (
            platform_code,
            author_key,
            author_name or None,
            profile_url,
            matched.entity_type,
            matched.intent_tag,
            matched.signal_score,
            content_text,
            evidence_url,
            occurred_at,
            mention_id,
            matched.contact_phone,
            matched.contact_email,
            matched.contact_zalo,
            keywords_json,
            meta,
        ),
    )
    return True


def purge_non_leads(cur) -> int:
    cur.execute(
        """
        SELECT lead_id::text, author_name, evidence_text
        FROM gift_leads
        WHERE status IN ('new', 'contacted')
        """
    )
    removed = 0
    for lead_id, author_name, evidence_text in cur.fetchall():
        if match_gift_intent(evidence_text or "", author_name=author_name or ""):
            continue
        cur.execute("DELETE FROM gift_leads WHERE lead_id = %s::uuid", (lead_id,))
        removed += 1
    return removed


def _parse_time(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def iter_raw_facebook_rows(raw_dir: Path) -> list[tuple]:
    rows: list[tuple] = []
    files = sorted(raw_dir.glob("search_*.jsonl"))
    for path in files:
        for line in path.open(encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = str(obj.get("message") or obj.get("story") or "").strip()
            permalink = str(obj.get("permalink_url") or "").strip() or None
            if not message:
                continue
            author = ""
            if permalink:
                m = re.search(r"facebook\.com/([^/]+)/", permalink)
                if m:
                    author = m.group(1)
            occurred = _parse_time(str(obj.get("created_time") or obj.get("published_at") or ""))
            external_id = str(obj.get("id") or "")
            rows.append(
                (
                    None,  # no mention_id — gift-only path
                    "facebook",
                    external_id or author,
                    author,
                    message,
                    permalink,
                    occurred,
                    permalink,
                )
            )
            # comments under post
            comments = (obj.get("comments") or {}).get("data") or []
            if isinstance(comments, list):
                for c in comments:
                    ctext = str((c or {}).get("message") or "").strip()
                    if not ctext:
                        continue
                    cid = str((c or {}).get("id") or "")
                    rows.append(
                        (
                            None,
                            "facebook",
                            cid or author,
                            author,
                            ctext,
                            permalink,
                            _parse_time(str((c or {}).get("created_time") or "")) or occurred,
                            permalink,
                        )
                    )
    return rows


def classify_rows(rows: list[tuple]) -> tuple[int, int]:
    with get_connection() as conn:
        cur = conn.cursor()
        ensure_table(cur)
        written = 0
        for row in rows:
            try:
                if upsert_lead(cur, row):
                    written += 1
                conn.commit()
            except Exception as exc:
                conn.rollback()
                print(f"[gift_leads] skip: {exc}", flush=True)
        return written, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=180, help="Mentions lookback (0=all)")
    parser.add_argument(
        "--platform",
        choices=["facebook", "threads", "instagram", "tiktok", "youtube", "google_maps", "news"],
        default=None,
    )
    parser.add_argument(
        "--from-raw",
        type=str,
        default=None,
        help="Classify gift-only from Facebook raw search_*.jsonl directory",
    )
    parser.add_argument(
        "--purge-non-leads",
        action="store_true",
        help="Delete gift_leads rows that fail current gift-only classifier",
    )
    parser.add_argument(
        "--skip-mentions",
        action="store_true",
        help="Do not scan cinema/brand mentions table",
    )
    args = parser.parse_args()

    if args.purge_non_leads:
        with get_connection() as conn:
            cur = conn.cursor()
            ensure_table(cur)
            removed = purge_non_leads(cur)
            conn.commit()
            print(f"gift_leads: purged_non_leads={removed}")

    if args.from_raw:
        raw_dir = Path(args.from_raw)
        if not raw_dir.is_absolute():
            raw_dir = PROJECT_ROOT / raw_dir
        rows = iter_raw_facebook_rows(raw_dir)
        written, scanned = classify_rows(rows)
        print(f"gift_leads from_raw: scanned={scanned} upserted={written} dir={raw_dir}")
        return 0

    if args.skip_mentions:
        print("gift_leads: skip mentions scan")
        return 0

    days = None if args.days == 0 else args.days
    with get_connection() as conn:
        cur = conn.cursor()
        ensure_table(cur)
        rows = fetch_candidates(cur, days=days, platform=args.platform)
    written, scanned = classify_rows(rows)
    print(f"gift_leads: scanned={scanned} upserted={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
