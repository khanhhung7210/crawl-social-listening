"""Source B — shared data processing (normalize / validate / sentiment / contract).

Source A (crawlers + platform format + keyword filter) produces
``*_keyword_mentions.json``. Source B turns that into DB-ready records without
owning Selenium / platform quirks.
"""

from __future__ import annotations

from social_listening.processing.contract import (
    COMMENT_DEDUP_KEYS,
    POST_DEDUP_KEYS,
    ProcessingResult,
)
from social_listening.processing.normalize import normalize_count, normalize_text
from social_listening.processing.pipeline import process_keyword_item
from social_listening.processing.sentiment import (
    SENTIMENT_PROVIDER_KEYWORDS,
    SENTIMENT_PROVIDER_PHOBERT,
    apply_sentiment,
    detect_mention_sentiment,
)

__all__ = [
    "COMMENT_DEDUP_KEYS",
    "POST_DEDUP_KEYS",
    "ProcessingResult",
    "SENTIMENT_PROVIDER_KEYWORDS",
    "SENTIMENT_PROVIDER_PHOBERT",
    "apply_sentiment",
    "detect_mention_sentiment",
    "normalize_count",
    "normalize_text",
    "process_keyword_item",
]
