"""Distribution crawl filter — apply film_rules at keyword_filter stage (not just import)."""

from __future__ import annotations

import os

from social_listening.film_rules import film_relevant_for_slug


def is_distribution_crawl() -> bool:
    profile = (os.getenv("SOCIAL_LISTENING_PROFILE") or "mkt").strip().lower()
    if profile in {"dis", "distribution", "film"}:
        return True
    return bool((os.getenv("SOCIAL_FILM_SLUG") or "").strip())


def current_film_slug() -> str:
    slug = (os.getenv("SOCIAL_FILM_SLUG") or "").strip()
    if slug:
        return slug.lower().replace(" ", "_")
    from social_listening.film_paths import film_slug

    return film_slug()


def passes_film_relevance(text: str, keyword_matches: list[str] | None = None) -> bool:
    """True when post/comment text is about the current film (DIS only).

    Crawl keyword hits (#TinNguyen, #ThuTrang…) are intentionally ignored — they
    are too broad and caused cast-only noise in Distribution exports.
    """
    del keyword_matches
    if not is_distribution_crawl():
        return True
    slug = current_film_slug()
    if not slug:
        return True
    return film_relevant_for_slug(text or "", slug, strict=False)


def filter_distribution_comments(comments: list[dict]) -> list[dict]:
    """Drop comments that do not pass film relevance (cast-only / unrelated)."""
    if not is_distribution_crawl():
        return comments
    kept: list[dict] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = str(comment.get("text") or comment.get("comment_text") or "")
        matches = comment.get("keyword_matches")
        match_list = matches if isinstance(matches, list) else None
        if passes_film_relevance(text, match_list):
            kept.append(comment)
    return kept


def keep_distribution_record(
    post_text: str,
    post_keyword_matches: list[str],
    comments: list[dict],
) -> tuple[bool, list[dict]]:
    """Return (keep_post, filtered_comments) for keyword_filter jobs."""
    if not is_distribution_crawl():
        return True, comments

    post_ok = passes_film_relevance(post_text, post_keyword_matches)
    filtered = filter_distribution_comments(comments)
    if post_ok:
        return True, filtered
    if filtered:
        return True, filtered
    return False, []
