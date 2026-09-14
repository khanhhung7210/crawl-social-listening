"""Incremental merge helpers — identity keys and engagement change detection.

Actual SQL upserts stay in the importer; this module documents and tests the
merge rules so Source B never treats an existing post as a full delete/replace.
"""

from __future__ import annotations

from typing import Any

from social_listening.processing.normalize import normalize_count


def post_external_id(item: dict[str, Any]) -> str:
    return str(item.get("post_id") or item.get("id") or item.get("url") or item.get("post_url") or "").strip()


def comment_external_id(comment: dict[str, Any], *, fallback_hash: str = "") -> str:
    ext = str(comment.get("external_id") or comment.get("id") or "").strip()
    return ext or fallback_hash


def engagement_changed(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """True when like/comment/view/share counts differ (None-safe)."""
    for key in ("like_count", "comment_count", "view_count", "share_count"):
        a = normalize_count(existing.get(key))
        b = normalize_count(incoming.get(key))
        if a is None and b is None:
            continue
        if a != b:
            return True
    return False


def merge_decision(*, existed: bool, changed: bool, has_new_children: bool) -> str:
    """
    High-level merge outcome for tests/docs.

    Returns: insert | skip | update | update_and_insert_children
    """
    if not existed:
        return "insert"
    if changed and has_new_children:
        return "update_and_insert_children"
    if changed:
        return "update"
    if has_new_children:
        return "update_and_insert_children"
    return "skip"
