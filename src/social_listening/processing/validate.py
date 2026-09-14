"""Light validation before merge/import."""

from __future__ import annotations

from typing import Any


def validate_keyword_item(item: dict[str, Any], platform: str) -> list[str]:
    """Return list of hard errors (empty = ok enough to attempt upsert)."""
    errors: list[str] = []
    if not platform or platform in {"processed", "raw", "data"}:
        errors.append("missing_platform")
    external = str(
        item.get("post_id") or item.get("id") or item.get("url") or item.get("post_url") or ""
    ).strip()
    if not external:
        errors.append("missing_external_post_id")
    return errors
