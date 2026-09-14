"""Source B pipeline: validate → normalize → sentiment (pre-import enrichment)."""

from __future__ import annotations

from typing import Any

from social_listening.processing.contract import ProcessingResult
from social_listening.processing.normalize import normalize_count, normalize_text, pick_text
from social_listening.processing.sentiment import (
    apply_news_neutral,
    apply_sentiment_batch,
)
from social_listening.processing.validate import validate_keyword_item


def _normalize_comment_fields(comment: dict[str, Any]) -> tuple[dict[str, Any], str, float | None]:
    c = dict(comment)
    text = pick_text(c.get("text"), c.get("comment_text"), c.get("message"))
    c["text"] = text
    c["comment_text"] = text
    if "like_count" in c:
        c["like_count"] = normalize_count(c.get("like_count"))
    rating = c.get("rating")
    try:
        rating_num = float(rating) if rating is not None and rating != "" else None
    except (TypeError, ValueError):
        rating_num = None
    return c, text, rating_num


def process_keyword_item(item: dict[str, Any], platform: str) -> ProcessingResult:
    """
    Enrich one Source A keyword-mention record for importer.

    Does not write to Postgres — importer performs incremental upsert.
    Sentiment uses the shared Source B provider (PhoBERT by default),
    batched across the post + its comments for one forward pass group.
    """
    errors = validate_keyword_item(item, platform)
    if errors:
        return ProcessingResult(item=item, platform=platform, ok=False, errors=errors)

    out = dict(item)
    text = pick_text(out.get("post_text"), out.get("text"), out.get("content"), out.get("body_text"))
    out["post_text"] = text
    if out.get("text") is not None:
        out["text"] = text

    for key in ("like_count", "comment_count", "share_count", "view_count"):
        if key in out:
            out[key] = normalize_count(out.get(key))
    stats = out.get("stats") if isinstance(out.get("stats"), dict) else None
    if stats is not None:
        stats = dict(stats)
        for key in ("like_count", "comment_count", "share_count", "view_count", "digg_count", "play_count"):
            if key in stats:
                stats[key] = normalize_count(stats.get(key))
        out["stats"] = stats

    comments_in = out.get("comments") or []
    normalized_comments: list[dict[str, Any]] = []
    comment_texts: list[str] = []
    comment_ratings: list[float | None] = []
    if isinstance(comments_in, list):
        for raw in comments_in:
            if not isinstance(raw, dict):
                continue
            c, c_text, c_rating = _normalize_comment_fields(raw)
            normalized_comments.append(c)
            comment_texts.append(c_text)
            comment_ratings.append(c_rating)

    # News headlines are not audience sentiment — force neutral, skip model.
    if str(platform).lower() == "news":
        out = apply_news_neutral(out)
        out["comments"] = [apply_news_neutral(c) for c in normalized_comments]
    else:
        payloads = [(out, text)] + list(zip(normalized_comments, comment_texts))
        ratings = [None] + comment_ratings
        enriched = apply_sentiment_batch(payloads, ratings=ratings)
        out = enriched[0]
        out["comments"] = enriched[1:]

    warnings: list[str] = []
    if not text.strip():
        warnings.append("empty_post_text")

    return ProcessingResult(item=out, platform=platform, ok=True, warnings=warnings)
