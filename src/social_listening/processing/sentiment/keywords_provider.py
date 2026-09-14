"""Keyword / rating sentiment provider (fallback + rule overrides)."""

from __future__ import annotations

from social_listening.marketing_sentiment import detect_sentiment
from social_listening.processing.sentiment.provider import (
    SENTIMENT_LABELS,
    SENTIMENT_PROVIDER_KEYWORDS,
    SENTIMENT_PROVIDER_RATING,
    SentimentPrediction,
    one_hot_prediction,
)


class KeywordsSentimentProvider:
    name = SENTIMENT_PROVIDER_KEYWORDS

    def predict(self, text: str, *, rating: float | None = None) -> SentimentPrediction:
        if rating is not None:
            try:
                stars = float(rating)
            except (TypeError, ValueError):
                stars = None
            if stars is not None:
                if stars >= 4:
                    return one_hot_prediction("positive", SENTIMENT_PROVIDER_RATING)
                if stars <= 2:
                    return one_hot_prediction("negative", SENTIMENT_PROVIDER_RATING)
        label = detect_sentiment(text, rating=None)
        if label not in SENTIMENT_LABELS:
            label = "neutral"
        return one_hot_prediction(label, self.name)

    def predict_batch(
        self, texts: list[str], *, ratings: list[float | None] | None = None
    ) -> list[SentimentPrediction]:
        ratings = ratings or [None] * len(texts)
        if len(ratings) != len(texts):
            raise ValueError("ratings length must match texts")
        return [self.predict(t, rating=r) for t, r in zip(texts, ratings)]
