"""Sentiment metadata helpers for importers (scores → DB fields)."""

from __future__ import annotations

from typing import Any


def sentiment_fields_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Extract DB-ready sentiment columns + metadata fragment from a processed item."""
    payload = payload or {}
    label = payload.get("sentiment")
    provider = payload.get("sentiment_provider")
    confidence = payload.get("sentiment_confidence")
    if confidence is None:
        confidence = payload.get("sentiment_score")
    scores = {
        "negative_score": payload.get("negative_score"),
        "neutral_score": payload.get("neutral_score"),
        "positive_score": payload.get("positive_score"),
        "sentiment_confidence": confidence,
    }
    # Drop empties so we don't wipe metadata with nulls
    scores = {k: float(v) for k, v in scores.items() if v is not None}
    meta: dict[str, Any] = {}
    if scores:
        meta["sentiment_scores"] = scores
    return {
        "sentiment": label,
        "sentiment_provider": provider,
        "sentiment_score": float(confidence) if confidence is not None else None,
        "metadata_scores": meta,
    }
