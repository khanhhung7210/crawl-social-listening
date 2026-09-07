#!/usr/bin/env python3
"""Consolidate raw_and_filtered export CSVs — dedupe, drop noise, normalize, one file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_rules import normalize, term_in_text  # noqa: E402

FILMS_DIR = PROJECT_ROOT / "data" / "distribution" / "films"
CATALOG_PATH = PROJECT_ROOT / "data" / "distribution" / "film_catalog.json"

OUTPUT_FIELDS = [
    "film_slug",
    "film_title",
    "platform",
    "mention_kind",
    "url",
    "author_name",
    "created_at",
    "text_content",
    "keyword_matches",
    "like_count",
    "comment_count",
    "view_count",
]

# Facebook crawl artifacts / spam
SPAM_RE = re.compile(
    r"membership\.makeviral|ets\.org|write a comment|see more see translation|"
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\u034f\u035f]|"
    r"r[\u034f\u035f]?[\s\u034f\u035f]?e[\u034f\u035f]?[\s\u034f\u035f]?o[\u034f\u035f]?[\s\u034f\u035f]?s",
    re.I,
)
PAGE_BIO_RE = re.compile(
    r"^\s*.+\.\s*\d[\d,\.]+\s+likes\s*[·•]\s*[\d,\.]+\s+talking about this",
    re.I,
)
UI_TAIL_RE = re.compile(
    r"\s*(see more|see translation|write a comment\.?\.?\.?)\s*$",
    re.I,
)


def load_film_meta(slug: str) -> dict[str, Any]:
    path = FILMS_DIR / f"{slug}.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    titles = load_catalog_titles()
    # Chỉ dùng tên phim + core/listening — không dùng cast/hashtag rộng
    title_terms = _uniq(
        [payload.get("film_title", "")]
        + list(payload.get("core_keywords") or [])
        + list(payload.get("listening_keywords") or [])
        + list(payload.get("sub_keywords") or [])
    )
    title_terms_norm: list[str] = []
    for t in title_terms:
        n = normalize(t)
        if not n or len(n) < 5:
            continue
        # Bỏ hashtag/diễn viên lẻ
        if n in {"#thutrang", "#tienluat", "#huynhlap", "huynh lap", "thu trang", "tien luat"}:
            continue
        title_terms_norm.append(n)
    return {
        "slug": slug,
        "title": titles.get(slug) or payload.get("film_title") or slug,
        "title_terms": title_terms_norm,
    }


def load_catalog_titles() -> dict[str, str]:
    if not CATALOG_PATH.exists():
        return {}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {str(f["slug"]): str(f.get("title") or f["slug"]) for f in data.get("films") or [] if f.get("slug")}


def _uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        t = str(v or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def has_film_title(text: str, meta: dict[str, Any]) -> bool:
    blob = normalize(text)
    if not blob:
        return False
    for term in meta["title_terms"]:
        if term_in_text(term, blob):
            return True
    return False


def clean_text(text: str) -> str:
    if not text:
        return ""
    s = str(text).strip()
    if s.startswith('{"') or s.startswith("{\""):
        m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
        if m:
            s = m.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
    s = SPAM_RE.sub(" ", s)
    s = re.sub(r"\s*0:\d{2}\s*/\s*\d+:\d{2}\s*", " ", s)
    s = re.sub(r"^[·•\s]+", "", s)
    s = UI_TAIL_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_noise(text: str, author: str = "") -> bool:
    if not text or len(text) < 8:
        return True
    if SPAM_RE.search(text) or SPAM_RE.search(author):
        return True
    if PAGE_BIO_RE.match(text):
        return True
    if re.fullmatch(r"[·•\s,:;!?.\-0-9]+", text):
        return True
    if text.lower() in {"see translation", "pages you follow", "top fan"}:
        return True
    return False


def author_looks_like_keyword(name: str, meta: dict[str, Any]) -> bool:
    n = normalize(name)
    if not n:
        return True
    if any(k in n for k in ("review", "trailer", "xem", "ve", "phim")):
        return True
    if has_film_title(name, meta):
        return True
    if n.startswith("#") or n.startswith("_"):
        return True
    return False


def normalize_author(name: str, meta: dict[str, Any]) -> str:
    name = (name or "").strip()
    if author_looks_like_keyword(name, meta):
        return ""
    return name


def row_key(row: dict) -> str:
    base = "|".join(
        [
            row.get("film_slug", ""),
            row.get("platform", ""),
            row.get("mention_kind", ""),
            row.get("url", ""),
            normalize(row.get("text_content", ""))[:160],
        ]
    )
    return hashlib.md5(base.encode()).hexdigest()


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def process_film(export_dir: Path, slug: str) -> tuple[list[dict], dict[str, int]]:
    meta = load_film_meta(slug)
    posts_raw = load_csv(export_dir / f"{slug}__ALL__filtered_posts.csv")
    comments_raw = load_csv(export_dir / f"{slug}__ALL__filtered_comments.csv")

    stats: dict[str, int] = {
        "posts_in": len(posts_raw),
        "comments_in": len(comments_raw),
        "posts_out": 0,
        "comments_out": 0,
    }

    kept_posts: list[dict] = []
    post_ids_ok: set[str] = set()

    for p in posts_raw:
        text = clean_text(p.get("text_content", ""))
        if is_noise(text):
            continue
        kw_match = str(p.get("post_keyword_match", "")).lower() == "true"
        title_hit = has_film_title(text, meta)
        kw_blob = normalize(str(p.get("post_keyword_matches") or p.get("search_keyword") or ""))
        kw_title_hit = any(term_in_text(t, kw_blob) for t in meta["title_terms"])
        if not (kw_match and (title_hit or kw_title_hit)):
            continue

        kw = p.get("post_keyword_matches") or p.get("search_keyword") or ""
        row = {
            "film_slug": slug,
            "film_title": meta["title"],
            "platform": p.get("platform", ""),
            "mention_kind": "post",
            "url": (p.get("url") or "").strip(),
            "author_name": normalize_author(p.get("author_name", ""), meta),
            "created_at": (p.get("created_at") or "").strip(),
            "text_content": text,
            "keyword_matches": kw if isinstance(kw, str) else "; ".join(kw),
            "like_count": p.get("like_count") or "",
            "comment_count": p.get("comment_count") or "",
            "view_count": p.get("view_count") or "",
        }
        kept_posts.append(row)
        if p.get("post_id"):
            post_ids_ok.add(p["post_id"])

    kept_comments: list[dict] = []
    for c in comments_raw:
        text = clean_text(c.get("text_content", ""))
        author = normalize_author(c.get("author_name", ""), meta)
        if is_noise(text, author):
            continue

        parent_ok = c.get("post_id") in post_ids_ok
        if parent_ok:
            # Post đã pass → lấy toàn bộ comment của post (chỉ bỏ noise/spam ở trên)
            pass
        else:
            kw_ok = str(c.get("keyword_match", "")).lower() == "true"
            title_ok = has_film_title(text, meta)
            if not (kw_ok or title_ok):
                continue

        kw = c.get("keyword_matches") or ""
        row = {
            "film_slug": slug,
            "film_title": meta["title"],
            "platform": c.get("platform", ""),
            "mention_kind": "comment",
            "url": (c.get("url") or "").strip(),
            "author_name": author,
            "created_at": (c.get("created_at") or "").strip(),
            "text_content": text,
            "keyword_matches": kw if isinstance(kw, str) else "; ".join(kw),
            "like_count": c.get("like_count") or "",
            "comment_count": "",
            "view_count": "",
        }
        kept_comments.append(row)

    all_rows = kept_posts + kept_comments
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in all_rows:
        k = row_key(row)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(row)

    stats["posts_out"] = sum(1 for r in deduped if r["mention_kind"] == "post")
    stats["comments_out"] = sum(1 for r in deduped if r["mention_kind"] == "comment")
    stats["deduped_out"] = len(deduped)
    return deduped, stats


def consolidate(export_dir: Path, films: list[str], out_path: Path) -> dict[str, Any]:
    all_rows: list[dict] = []
    summary: dict[str, Any] = {"source_dir": str(export_dir), "films": {}}

    for slug in films:
        rows, stats = process_film(export_dir, slug)
        summary["films"][slug] = stats
        all_rows.extend(rows)
        print(
            f"  {slug}: posts {stats['posts_in']}->{stats['posts_out']}, "
            f"comments {stats['comments_in']}->{stats['comments_out']}, "
            f"total {stats['deduped_out']}"
        )

    all_rows.sort(
        key=lambda r: (r["film_slug"], r["platform"], r.get("created_at") or ""),
        reverse=True,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    summary["total_rows"] = len(all_rows)
    summary["output_file"] = str(out_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "distribution" / "exports" / "raw_and_filtered_20260828_1521",
    )
    parser.add_argument("--film", action="append", default=["quy_tu_vuot_giau", "nghi_he_so_nghi_huu"])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    films = [f.strip() for f in args.film if f.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = args.output or (args.input_dir / f"films_clean_combined_{stamp}.csv")

    print(f"Consolidate from {args.input_dir}")
    summary = consolidate(args.input_dir, films, out_path)

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal: {summary['total_rows']} rows -> {out_path}")
    print(f"Summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
