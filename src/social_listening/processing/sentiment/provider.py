"""Shared sentiment provider abstraction for Source B."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

SENTIMENT_LABELS = frozenset({"positive", "negative", "neutral"})

SENTIMENT_PROVIDER_KEYWORDS = "keywords"
SENTIMENT_PROVIDER_PHOBERT = "phobert"
SENTIMENT_PROVIDER_HUMAN = "human"
SENTIMENT_PROVIDER_RATING = "rating"
SENTIMENT_PROVIDER_NEWS_RULE = "news_rule"

DEFAULT_PHOBERT_MODEL = "wonrax/phobert-base-vietnamese-sentiment"


@dataclass(frozen=True)
class SentimentPrediction:
    """Normalized sentiment output for Source B / DB consumers."""

    label: str
    provider: str
    negative_score: float
    neutral_score: float
    positive_score: float
    sentiment_confidence: float

    @property
    def sentiment_label(self) -> str:
        return self.label

    @property
    def sentiment_score(self) -> float:
        """DB column ``sentiment_score`` stores confidence (0–1)."""
        return self.sentiment_confidence

    def as_payload_fields(self) -> dict:
        return {
            "sentiment": self.label,
            "sentiment_label": self.label,
            "sentiment_provider": self.provider,
            "negative_score": self.negative_score,
            "neutral_score": self.neutral_score,
            "positive_score": self.positive_score,
            "sentiment_confidence": self.sentiment_confidence,
            "sentiment_score": self.sentiment_score,
        }


def one_hot_prediction(label: str, provider: str) -> SentimentPrediction:
    if label not in SENTIMENT_LABELS:
        label = "neutral"
    scores = {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
    scores[label] = 1.0
    return SentimentPrediction(
        label=label,
        provider=provider,
        negative_score=scores["negative"],
        neutral_score=scores["neutral"],
        positive_score=scores["positive"],
        sentiment_confidence=1.0,
    )


@runtime_checkable
class SentimentProvider(Protocol):
    name: str

    def predict(self, text: str) -> SentimentPrediction:
        ...

    def predict_batch(self, texts: list[str]) -> list[SentimentPrediction]:
        ...


_provider_override: SentimentProvider | None = None
_cached_provider: SentimentProvider | None = None


def reset_sentiment_provider_cache() -> None:
    """Clear process-level provider cache (tests / reprocess)."""
    global _cached_provider
    _cached_provider = None


def set_sentiment_provider_override(provider: SentimentProvider | None) -> None:
    """Inject a provider for tests; pass None to clear."""
    global _provider_override
    _provider_override = provider
    reset_sentiment_provider_cache()


def configured_provider_name() -> str:
    raw = (os.getenv("SENTIMENT_PROVIDER") or SENTIMENT_PROVIDER_PHOBERT).strip().lower()
    if raw in {SENTIMENT_PROVIDER_PHOBERT, SENTIMENT_PROVIDER_KEYWORDS}:
        return raw
    raise ValueError(
        f"unsupported SENTIMENT_PROVIDER={raw!r}; "
        f"expected {SENTIMENT_PROVIDER_PHOBERT!r} or {SENTIMENT_PROVIDER_KEYWORDS!r}"
    )


def confidence_threshold() -> float | None:
    """
    Optional ``SENTIMENT_CONFIDENCE_THRESHOLD`` (0–1).

    Default: unset — always keep the model's predicted label.
    When set, callers may document/use it; Source B does not silently
    rewrite labels unless explicitly enabled later.
    """
    raw = (os.getenv("SENTIMENT_CONFIDENCE_THRESHOLD") or "").strip()
    if not raw:
        return None
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"SENTIMENT_CONFIDENCE_THRESHOLD must be in [0,1], got {value}")
    return value


def get_sentiment_provider() -> SentimentProvider:
    global _cached_provider
    if _provider_override is not None:
        return _provider_override
    if _cached_provider is not None:
        return _cached_provider

    name = configured_provider_name()
    if name == SENTIMENT_PROVIDER_KEYWORDS:
        from social_listening.processing.sentiment.keywords_provider import (
            KeywordsSentimentProvider,
        )

        _cached_provider = KeywordsSentimentProvider()
        return _cached_provider

    allow_fallback = (os.getenv("SENTIMENT_ALLOW_KEYWORD_FALLBACK") or "1").strip() not in {
        "0",
        "false",
        "False",
        "no",
    }
    try:
        from social_listening.processing.sentiment.phobert_provider import (
            PhoBERTSentimentProvider,
        )

        _cached_provider = PhoBERTSentimentProvider()
        return _cached_provider
    except Exception as exc:
        if not allow_fallback:
            raise RuntimeError(
                "PhoBERT sentiment provider failed to load and "
                "SENTIMENT_ALLOW_KEYWORD_FALLBACK is disabled"
            ) from exc
        from social_listening.processing.sentiment.keywords_provider import (
            KeywordsSentimentProvider,
        )

        _cached_provider = KeywordsSentimentProvider()
        return _cached_provider
