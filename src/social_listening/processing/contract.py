"""Common data contract between Source A (filtered JSON) and Source B."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Stable identity for incremental merge (never content-only).
POST_DEDUP_KEYS = ("platform_code", "external_post_id")
COMMENT_DEDUP_KEYS = ("post_id", "external_comment_id")

# Fields Source B expects after platform format + keyword filter.
COMMON_POST_FIELDS = (
    "platform",
    "post_id",  # external / native id
    "post_text",
    "post_url",
    "author",
    "author_name",
    "page_name",
    "posted_at",
    "created_at",
    "like_count",
    "comment_count",
    "share_count",
    "view_count",
    "comments",  # list of comment dicts
)


@dataclass
class ProcessingResult:
    """Enriched keyword-mention item ready for importer upsert."""

    item: dict[str, Any]
    platform: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
