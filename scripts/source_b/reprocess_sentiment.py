#!/usr/bin/env python3
"""Reprocess sentiment on existing mentions without crawling (Source B).

Uses shared PhoBERT + ``prepare_sentiment_text`` (via provider). News → neutral.
Never overwrites sentiment_provider='human'.

Examples:
  PYTHONPATH=src:.pip_packages SENTIMENT_PROVIDER=phobert \\
    python3 scripts/source_b/reprocess_sentiment.py --dry-run --limit 100
  PYTHONPATH=src:.pip_packages SENTIMENT_PROVIDER=phobert \\
    python3 scripts/source_b/reprocess_sentiment.py --batch-size 32
"""

from __future__ import annotations

import argparse
import json
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
from social_listening.processing.sentiment import (  # noqa: E402
    SENTIMENT_PROVIDER_HUMAN,
    apply_news_neutral,
    apply_sentiment_batch,
)


def _parse_meta(raw) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return dict(json.loads(raw))
        except json.JSONDecodeError:
            return {}
    return {}


def _rating_from_meta(meta: dict) -> float | None:
    raw = meta.get("rating")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _should_update(old_label, old_provider, out: dict) -> bool:
    if str(old_provider or "").lower() == SENTIMENT_PROVIDER_HUMAN:
        return False
    new_label = out.get("sentiment")
    provider = out.get("sentiment_provider")
    confidence = out.get("sentiment_confidence")
    if new_label != old_label:
        return True
    if (old_provider or "") != (provider or ""):
        return True
    if confidence is not None:
        return True
    if out.get("negative_score") is not None:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="")
    parser.add_argument("--limit", type=int, default=0, help="0 = all matching rows")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="PhoBERT batch size (non-news rows)",
    )
    parser.add_argument(
        "--providers",
        default="keywords,phobert",
        help="Comma-separated sentiment_provider values to reprocess (default: keywords,phobert)",
    )
    args = parser.parse_args()

    provider_list = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    placeholders = ",".join(["%s"] * len(provider_list))
    where = [
        f"(sentiment_provider IS NULL OR sentiment_provider IN ({placeholders}))"
    ]
    params: list = list(provider_list)
    if args.platform:
        where.append("platform_code = %s")
        params.append(args.platform.strip().lower())

    sql = f"""
        SELECT mention_id::text, platform_code, content_text, sentiment,
               sentiment_provider, metadata
        FROM mentions
        WHERE {' AND '.join(where)}
          AND COALESCE(is_spam, FALSE) = FALSE
        ORDER BY platform_code, updated_at NULLS LAST, created_at
    """
    if args.limit and args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"

    updated = scanned = 0
    news_n = model_n = 0

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        print(f"selected_rows={len(rows)} dry_run={args.dry_run}")

        model_batch: list[tuple] = []

        def flush_model_batch(batch_rows: list[tuple]) -> None:
            nonlocal updated, scanned, model_n
            if not batch_rows:
                return
            payloads: list[tuple[dict, str]] = []
            ratings: list[float | None] = []
            for _mid, _plat, text, _ol, _op, meta in batch_rows:
                meta_d = _parse_meta(meta)
                payloads.append(({}, text or ""))
                ratings.append(_rating_from_meta(meta_d))
            enriched = apply_sentiment_batch(payloads, ratings=ratings)
            for row, out in zip(batch_rows, enriched):
                mention_id, platform, text, old_label, old_provider, meta = row
                scanned += 1
                model_n += 1
                if not _should_update(old_label, old_provider, out):
                    continue
                updated += 1
                if args.dry_run:
                    continue
                _write_update(cur, mention_id, meta, out)
            if not args.dry_run:
                conn.commit()

        for row in rows:
            mention_id, platform, text, old_label, old_provider, meta = row
            platform = (platform or "").lower()
            if platform == "news":
                scanned += 1
                news_n += 1
                out = apply_news_neutral({})
                if not _should_update(old_label, old_provider, out):
                    continue
                updated += 1
                if args.dry_run:
                    continue
                _write_update(cur, mention_id, meta, out)
                continue

            model_batch.append(row)
            if len(model_batch) >= max(1, int(args.batch_size)):
                flush_model_batch(model_batch)
                model_batch = []

        flush_model_batch(model_batch)
        if not args.dry_run:
            conn.commit()

    print(
        f"scanned={scanned} news={news_n} model={model_n} "
        f"would_update_or_updated={updated} dry_run={args.dry_run}"
    )
    return 0


def _write_update(cur, mention_id: str, meta_raw, out: dict) -> None:
    meta = _parse_meta(meta_raw)
    scores = {
        k: out.get(k)
        for k in (
            "negative_score",
            "neutral_score",
            "positive_score",
            "sentiment_confidence",
        )
        if out.get(k) is not None
    }
    if scores:
        meta["sentiment_scores"] = scores
    meta["sentiment_reprocessed"] = True
    patch = {"sentiment_scores": scores} if scores else {}
    cur.execute(
        """
        UPDATE mentions SET
            sentiment = %s,
            sentiment_provider = %s,
            sentiment_score = COALESCE(%s, sentiment_score),
            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
            updated_at = NOW()
        WHERE mention_id = %s::uuid
          AND COALESCE(sentiment_provider, '') <> 'human'
        """,
        (
            out.get("sentiment"),
            out.get("sentiment_provider"),
            out.get("sentiment_confidence"),
            json.dumps(patch, ensure_ascii=False, default=str),
            mention_id,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
