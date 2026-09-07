#!/usr/bin/env python3
"""Rebuild mention_brands from current detect_competitive_brands() rules.

STEP B (historical alignment). Default mode is dry-run: compare existing tags vs
newly detected brands WITHOUT writing to the database.

Usage:
  PYTHONPATH=src python3 scripts/marketing/classify/rebuild_mention_brands.py --dry-run
  PYTHONPATH=src python3 scripts/marketing/classify/rebuild_mention_brands.py --dry-run --limit 5000
  PYTHONPATH=src python3 scripts/marketing/classify/rebuild_mention_brands.py --dry-run --examples 5

Execute mode (writes) requires --execute AND is intentionally gated; do not use
until STEP B dry-run has been reviewed and approved separately.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.brand_rules import detect_competitive_brands  # noqa: E402
from social_listening.pg import fetch_brand_map, get_connection  # noqa: E402

COMPETITIVE_SLUGS = ("glx", "cgv", "lotte", "beta", "bhd", "cinestar")


@dataclass(frozen=True)
class BrandDelta:
    """Per-mention comparison of existing vs newly detected brand slugs."""

    mention_id: str
    existing: tuple[str, ...]
    detected: tuple[str, ...]
    additions: tuple[str, ...]
    removals: tuple[str, ...]
    unchanged: tuple[str, ...]

    @property
    def has_change(self) -> bool:
        return bool(self.additions or self.removals)

    @property
    def loses_all_brands(self) -> bool:
        return bool(self.existing) and not self.detected

    @property
    def gains_from_empty(self) -> bool:
        return not self.existing and bool(self.detected)

    @property
    def is_replacement(self) -> bool:
        """Existing tags partially/fully swapped (both removals and additions)."""
        return bool(self.additions) and bool(self.removals)


def normalize_brand_slugs(slugs: Iterable[str] | None) -> tuple[str, ...]:
    """Deduplicate while preserving first-seen order; lower-case slug strings."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in slugs or []:
        slug = str(raw or "").strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return tuple(out)


def compare_brand_sets(
    existing: Sequence[str] | None,
    detected: Sequence[str] | None,
    *,
    mention_id: str = "",
) -> BrandDelta:
    """Compare existing mention_brands slugs vs freshly detected slugs."""
    old = normalize_brand_slugs(existing)
    new = normalize_brand_slugs(detected)
    old_set, new_set = set(old), set(new)
    additions = tuple(s for s in new if s not in old_set)
    removals = tuple(s for s in old if s not in new_set)
    unchanged = tuple(s for s in old if s in new_set)
    return BrandDelta(
        mention_id=mention_id,
        existing=old,
        detected=new,
        additions=additions,
        removals=removals,
        unchanged=unchanged,
    )


def detect_brands_for_mention(
    *,
    content_text: str,
    permalink: str = "",
    author_key: str = "",
    platform_code: str = "",
    metadata: Any = None,
) -> list[str]:
    """Call the same detector as import_keyword_mentions (no second implementation)."""
    matches: list[str] = []
    if isinstance(metadata, dict):
        raw = metadata.get("keyword_matches") or metadata.get("matched_search_keywords") or []
        if isinstance(raw, list):
            matches = [str(x) for x in raw]
    return detect_competitive_brands(
        content_text or "",
        matches,
        permalink=permalink or "",
        author=author_key or "",
        platform=platform_code or None,
    )


@dataclass
class DryRunReport:
    scanned: int = 0
    unchanged: int = 0
    with_changes: int = 0
    losing_all: int = 0
    gaining_from_empty: int = 0
    replacements: int = 0
    # brand_slug -> counters
    existing_tags: Counter = field(default_factory=Counter)
    new_tags: Counter = field(default_factory=Counter)
    additions: Counter = field(default_factory=Counter)
    removals: Counter = field(default_factory=Counter)
    unchanged_tags: Counter = field(default_factory=Counter)
    sample_deltas: list[BrandDelta] = field(default_factory=list)
    # category exemplars (first match wins)
    examples: dict[str, BrandDelta] = field(default_factory=dict)
    mention_snippets: dict[str, str] = field(default_factory=dict)


def _snippet(text: str, n: int = 120) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _classify_example(delta: BrandDelta, content: str, permalink: str) -> str | None:
    """Assign a human-facing example category for the dry-run report."""
    blob = f"{content} {permalink}".lower()
    rem = set(delta.removals)
    det = set(delta.detected)
    exist = set(delta.existing)

    if delta.loses_all_brands and "cgv" in rem and any(
        x in blob for x in ("korea", "seoul", "hàn quốc", "han quoc", ".co.kr", "starnewskorea")
    ):
        return "stale_cgv_korea_foreign_removed"
    if delta.loses_all_brands and rem and not any(
        s in blob for s in ("cgv", "lotte cinema", "galaxy cinema", "galaxy cine", "rạp galaxy")
    ):
        # keyword-only / content without brand token — old tags would go away
        return "keyword_only_false_positive_removed"
    if delta.loses_all_brands and rem:
        return "unrelated_or_stale_untagged"
    if "cgv" in det and "menas" in blob:
        return "valid_cgv_menas_mall_remains"
    if "cgv" in det and ("liberty citypoint" in blob or "liberty" in blob and "citypoint" in blob):
        return "valid_cgv_liberty_citypoint_remains"
    if "cgv" in det and any(x in blob for x in ("việt nam", "viet nam", "vietnam", "tp.hcm", "hà nội", "ha noi")):
        return "valid_cgv_vietnam_remains"
    if "lotte" in det and any(x in blob for x in ("việt nam", "viet nam", "vietnam", "hà nội", "ha noi")):
        return "valid_lotte_vietnam_remains"
    if "glx" in det and any(x in blob for x in ("galaxy cinema", "galaxy cine", "rạp galaxy")):
        return "valid_galaxy_vietnam_remains"
    if delta.has_change and rem and not det:
        return "stale_tag_removed"
    if delta.is_replacement:
        return "brand_replacement"
    if not delta.has_change and exist:
        return "unchanged_tagged"
    return None


def accumulate_delta(report: DryRunReport, delta: BrandDelta, content: str = "", permalink: str = "") -> None:
    report.scanned += 1
    for s in delta.existing:
        report.existing_tags[s] += 1
    for s in delta.detected:
        report.new_tags[s] += 1
    for s in delta.additions:
        report.additions[s] += 1
    for s in delta.removals:
        report.removals[s] += 1
    for s in delta.unchanged:
        report.unchanged_tags[s] += 1

    if not delta.has_change:
        report.unchanged += 1
    else:
        report.with_changes += 1
        if len(report.sample_deltas) < 50:
            report.sample_deltas.append(delta)
            report.mention_snippets[delta.mention_id] = _snippet(content)

    if delta.loses_all_brands:
        report.losing_all += 1
    if delta.gains_from_empty:
        report.gaining_from_empty += 1
    if delta.is_replacement:
        report.replacements += 1

    cat = _classify_example(delta, content, permalink)
    if cat and cat not in report.examples:
        report.examples[cat] = delta
        report.mention_snippets[delta.mention_id] = _snippet(content)


def format_brand_table(report: DryRunReport) -> str:
    brands = sorted(set(COMPETITIVE_SLUGS) | set(report.existing_tags) | set(report.new_tags))
    lines = [
        f"{'brand':10} {'existing':>10} {'new':>10} {'additions':>10} {'removals':>10} {'unchanged':>10}",
        "-" * 64,
    ]
    for b in brands:
        lines.append(
            f"{b:10} {report.existing_tags[b]:10} {report.new_tags[b]:10} "
            f"{report.additions[b]:10} {report.removals[b]:10} {report.unchanged_tags[b]:10}"
        )
    return "\n".join(lines)


def print_report(report: DryRunReport, *, examples: int = 3) -> None:
    print("=== mention_brands rebuild DRY-RUN ===")
    print(f"total mentions scanned:     {report.scanned}")
    print(f"mentions with changes:      {report.with_changes}")
    print(f"mentions unchanged:         {report.unchanged}")
    print(f"mentions losing all tags:   {report.losing_all}")
    print(f"mentions gaining tags:      {report.gaining_from_empty}")
    print(f"mentions with replacement:  {report.replacements}")
    print()
    print(format_brand_table(report))
    print()
    print("--- example categories ---")
    wanted = [
        "stale_cgv_korea_foreign_removed",
        "keyword_only_false_positive_removed",
        "valid_cgv_vietnam_remains",
        "valid_lotte_vietnam_remains",
        "valid_galaxy_vietnam_remains",
        "valid_cgv_menas_mall_remains",
        "valid_cgv_liberty_citypoint_remains",
        "unrelated_or_stale_untagged",
        "brand_replacement",
        "stale_tag_removed",
        "unchanged_tagged",
    ]
    for key in wanted:
        delta = report.examples.get(key)
        if not delta:
            print(f"[{key}] (no example found in scanned set)")
            continue
        snip = report.mention_snippets.get(delta.mention_id, "")
        print(
            f"[{key}] id={delta.mention_id[:8]}… "
            f"existing={list(delta.existing)} → detected={list(delta.detected)} "
            f"| {snip!r}"
        )
    if report.sample_deltas and examples > 0:
        print()
        print(f"--- first {min(examples, len(report.sample_deltas))} changed samples ---")
        for delta in report.sample_deltas[:examples]:
            snip = report.mention_snippets.get(delta.mention_id, "")
            print(
                f"  {delta.mention_id[:8]}… "
                f"{list(delta.existing)} → {list(delta.detected)} "
                f"(+{list(delta.additions)} -{list(delta.removals)}) {snip!r}"
            )


FETCH_SQL = """
SELECT
  m.mention_id::text,
  m.content_text,
  COALESCE(m.permalink, '') AS permalink,
  COALESCE(m.author_key, '') AS author_key,
  m.platform_code,
  COALESCE(m.metadata, '{}'::jsonb) AS metadata,
  COALESCE(
    array_agg(b.brand_slug::text ORDER BY b.brand_slug)
      FILTER (WHERE b.brand_slug IS NOT NULL),
    ARRAY[]::text[]
  ) AS brand_slugs
FROM mentions m
LEFT JOIN mention_brands mb ON mb.mention_id = m.mention_id
LEFT JOIN brands b ON b.brand_id = mb.brand_id
WHERE m.is_spam = FALSE
GROUP BY m.mention_id, m.content_text, m.permalink, m.author_key, m.platform_code, m.metadata
ORDER BY m.occurred_at DESC NULLS LAST, m.mention_id
"""


def run_dry_run(*, limit: int | None = None, example_count: int = 3) -> DryRunReport:
    """Scan mentions, compare brands, write nothing."""
    report = DryRunReport()
    sql = FETCH_SQL
    params: tuple = ()
    if limit is not None and limit > 0:
        sql = FETCH_SQL + "\nLIMIT %s"
        params = (limit,)

    with get_connection() as conn:
        # Best-effort read-only session; always rollback before exit.
        try:
            conn.set_session(readonly=True, autocommit=False)
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute(sql, params)
            while True:
                rows = cur.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    mention_id, content, permalink, author, platform, metadata, brand_slugs = row
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except json.JSONDecodeError:
                            metadata = {}
                    detected = detect_brands_for_mention(
                        content_text=content or "",
                        permalink=permalink or "",
                        author_key=author or "",
                        platform_code=platform or "",
                        metadata=metadata,
                    )
                    existing = list(brand_slugs or [])
                    delta = compare_brand_sets(existing, detected, mention_id=mention_id)
                    accumulate_delta(report, delta, content=content or "", permalink=permalink or "")
        conn.rollback()  # never persist; dry-run safety

    print_report(report, examples=example_count)
    print()
    print("DRY-RUN complete: NO DELETE / INSERT / UPDATE performed.")
    return report


def run_execute(*, limit: int | None = None) -> int:
    """Apply brand replacements. Gated — requires explicit --execute."""
    updated = 0
    sql = FETCH_SQL
    params: tuple = ()
    if limit is not None and limit > 0:
        sql = FETCH_SQL + "\nLIMIT %s"
        params = (limit,)

    with get_connection() as conn:
        with conn.cursor() as cur:
            brand_map = fetch_brand_map(cur)
            cur.execute(sql, params)
            rows = cur.fetchall()
            for row in rows:
                mention_id, content, permalink, author, platform, metadata, brand_slugs = row
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = {}
                detected = detect_brands_for_mention(
                    content_text=content or "",
                    permalink=permalink or "",
                    author_key=author or "",
                    platform_code=platform or "",
                    metadata=metadata,
                )
                delta = compare_brand_sets(brand_slugs or [], detected, mention_id=mention_id)
                if not delta.has_change:
                    continue
                cur.execute(
                    "DELETE FROM mention_brands WHERE mention_id = %s::uuid",
                    (mention_id,),
                )
                for slug in delta.detected:
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
                updated += 1
        # commit via get_connection context
    print(f"EXECUTE complete: mentions updated={updated}")
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Compare only; never write (recommended / default for STEP B).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Apply brand replacements (requires explicit flag; not for STEP B dry-run).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max mentions to scan")
    parser.add_argument("--examples", type=int, default=5, help="Changed-sample count to print")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.execute and args.dry_run:
        print("ERROR: pass only one of --dry-run or --execute", file=sys.stderr)
        return 2
    if args.execute:
        # Require explicit confirmation env to reduce accidental writes.
        import os

        if os.environ.get("MENTION_BRANDS_EXECUTE_CONFIRM") != "YES":
            print(
                "ERROR: Set MENTION_BRANDS_EXECUTE_CONFIRM=YES to unlock --execute.",
                file=sys.stderr,
            )
            return 3
        print("EXECUTE unlocked via MENTION_BRANDS_EXECUTE_CONFIRM=YES")
        updated = run_execute(limit=args.limit)
        print(f"EXECUTE finished mentions_updated={updated}")
        return 0
    # Default to dry-run when neither flag is passed
    run_dry_run(limit=args.limit, example_count=args.examples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
