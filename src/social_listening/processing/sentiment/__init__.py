"""Sentiment as an independent Source B step (shared provider abstraction)."""

from __future__ import annotations

from typing import Any

from social_listening.processing.sentiment.provider import (
    SENTIMENT_LABELS,
    SENTIMENT_PROVIDER_HUMAN,
    SENTIMENT_PROVIDER_KEYWORDS,
    SENTIMENT_PROVIDER_NEWS_RULE,
    SENTIMENT_PROVIDER_PHOBERT,
    SENTIMENT_PROVIDER_RATING,
    SentimentPrediction,
    confidence_threshold,
    get_sentiment_provider,
    one_hot_prediction,
    reset_sentiment_provider_cache,
    set_sentiment_provider_override,
)
from social_listening.processing.sentiment.text_prep import prepare_sentiment_text

__all__ = [
    "SENTIMENT_LABELS",
    "SENTIMENT_PROVIDER_HUMAN",
    "SENTIMENT_PROVIDER_KEYWORDS",
    "SENTIMENT_PROVIDER_NEWS_RULE",
    "SENTIMENT_PROVIDER_PHOBERT",
    "SENTIMENT_PROVIDER_RATING",
    "SentimentPrediction",
    "apply_news_neutral",
    "apply_sentiment",
    "apply_sentiment_batch",
    "confidence_threshold",
    "detect_mention_sentiment",
    "get_sentiment_provider",
    "one_hot_prediction",
    "prepare_sentiment_text",
    "reset_sentiment_provider_cache",
    "set_sentiment_provider_override",
]


def _rating_override(rating: float | None) -> SentimentPrediction | None:
    if rating is None:
        return None
    try:
        stars = float(rating)
    except (TypeError, ValueError):
        return None
    if stars >= 4:
        return one_hot_prediction("positive", SENTIMENT_PROVIDER_RATING)
    if stars <= 2:
        return one_hot_prediction("negative", SENTIMENT_PROVIDER_RATING)
    return None


def detect_mention_sentiment(
    text: str,
    *,
    rating: float | None = None,
    provider: str | None = None,
) -> tuple[str | None, str]:
    """Return ``(label, provider_name)`` via the shared Source B provider."""
    pred = _predict_one(text, rating=rating, provider_name=provider)
    return pred.label, pred.provider


def _predict_one(
    text: str,
    *,
    rating: float | None = None,
    provider_name: str | None = None,
) -> SentimentPrediction:
    override = _rating_override(rating)
    if override is not None:
        return override

    if provider_name == SENTIMENT_PROVIDER_KEYWORDS:
        from social_listening.processing.sentiment.keywords_provider import (
            KeywordsSentimentProvider,
        )

        return KeywordsSentimentProvider().predict(text, rating=None)

    active = get_sentiment_provider()
    # Keywords provider accepts rating; PhoBERT does not (rating handled above).
    if hasattr(active, "predict") and active.name == SENTIMENT_PROVIDER_KEYWORDS:
        return active.predict(text, rating=None)  # type: ignore[call-arg]
    return active.predict(text)


def apply_news_neutral(payload: dict[str, Any]) -> dict[str, Any]:
    """Business rule: Google News headlines → neutral (no model call)."""
    out = dict(payload)
    out.update(one_hot_prediction("neutral", SENTIMENT_PROVIDER_NEWS_RULE).as_payload_fields())
    return out


def apply_sentiment(
    payload: dict[str, Any],
    text: str,
    *,
    rating: float | None = None,
    provider: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Attach sentiment fields onto a dict (post or comment mention payload).

    If ``sentiment_provider`` is already ``human`` and force is False, keep it.
    """
    existing_provider = str(payload.get("sentiment_provider") or "").strip().lower()
    if existing_provider == SENTIMENT_PROVIDER_HUMAN and not force:
        return payload

    pred = _predict_one(text, rating=rating, provider_name=provider)
    out = dict(payload)
    out.update(pred.as_payload_fields())
    return out


def apply_sentiment_batch(
    payloads_and_texts: list[tuple[dict[str, Any], str]],
    *,
    ratings: list[float | None] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """
    Batch-predict sentiment for many payloads (one model forward where possible).

    Preserves ``human`` rows unless ``force`` is True.
    Applies star-rating overrides without calling PhoBERT.
    """
    ratings = ratings or [None] * len(payloads_and_texts)
    if len(ratings) != len(payloads_and_texts):
        raise ValueError("ratings length must match payloads")

    results: list[dict[str, Any] | None] = [None] * len(payloads_and_texts)
    batch_indices: list[int] = []
    batch_texts: list[str] = []

    for i, ((payload, text), rating) in enumerate(zip(payloads_and_texts, ratings)):
        existing_provider = str(payload.get("sentiment_provider") or "").strip().lower()
        if existing_provider == SENTIMENT_PROVIDER_HUMAN and not force:
            results[i] = dict(payload)
            continue
        override = _rating_override(rating)
        if override is not None:
            out = dict(payload)
            out.update(override.as_payload_fields())
            results[i] = out
            continue
        batch_indices.append(i)
        batch_texts.append(text)

    if batch_texts:
        provider = get_sentiment_provider()
        if provider.name == SENTIMENT_PROVIDER_KEYWORDS and hasattr(provider, "predict_batch"):
            preds = provider.predict_batch(batch_texts)  # type: ignore[call-arg]
        else:
            preds = provider.predict_batch(batch_texts)
        for idx, pred in zip(batch_indices, preds):
            payload, _text = payloads_and_texts[idx]
            out = dict(payload)
            out.update(pred.as_payload_fields())
            results[idx] = out

    return [r if r is not None else dict(payloads_and_texts[i][0]) for i, r in enumerate(results)]
