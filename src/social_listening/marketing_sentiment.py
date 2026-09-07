"""Keyword sentiment for Marketing mentions (cinema competitive listening).

Clause-aware, Vietnamese negation window before sentiment keywords.
"""

from __future__ import annotations

import re
import unicodedata

POS_WORDS: list[str] = [
    "ngon",
    "tốt",
    "tot",
    "hay",
    "đỉnh",
    "dinh",
    "ổn",
    "on",
    "thích",
    "thich",
    "ok",
    "xuất sắc",
    "xuat sac",
]

NEG_WORDS: list[str] = [
    "tệ",
    "te",
    "dở",
    "do",
    "xấu",
    "xau",
    "lỗi",
    "loi",
    "thất vọng",
    "that vong",
    "kém",
    "kem",
    "chán",
    "chan",
]

# Longer phrases first when scanning the token window before a keyword.
NEGATION_PHRASES: tuple[str, ...] = (
    "khong he",
    "khong phai",
    "chang phai",
    "khong co",
    "khong lam",
)

NEGATION_TOKENS: frozenset[str] = frozenset({"khong", "chua", "chang", "ko", "chn"})

CLAUSE_SPLIT_RE = re.compile(
    r"[.!?;…]+|\n+|\s+(?:nhưng|nhung|tuy nhiên|tuy nhien|tuy|mà|ma|dù|du)\s+",
    re.IGNORECASE,
)


def normalize_sentiment_text(text: str) -> str:
    blob = (text or "").lower().replace("đ", "d").replace("Đ", "d")
    blob = unicodedata.normalize("NFD", blob)
    blob = "".join(ch for ch in blob if unicodedata.category(ch) != "Mn")
    blob = re.sub(r"[^a-z0-9#\s]+", " ", blob)
    return re.sub(r"\s+", " ", blob).strip()


def split_clauses(text: str) -> list[str]:
    parts = [p.strip() for p in CLAUSE_SPLIT_RE.split(text or "") if p and p.strip()]
    return parts or [text or ""]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    p = normalize_sentiment_text(phrase)
    if " " in p or len(p) >= 4 or p.startswith("#"):
        return re.compile(re.escape(p))
    return re.compile(rf"(?<![a-z0-9#]){re.escape(p)}(?![a-z0-9])")


def _is_spurious_neg_hit(blob: str, start: int) -> bool:
    """Skip 'do' when it comes from 'sau đó' (normalized 'sau do'), not 'dở'."""
    prefix = blob[max(0, start - 5) : start]
    return prefix.endswith("sau ") or prefix.endswith("sau")


def _find_hits(blob: str, words: list[str], *, polarity: str = "") -> list[tuple[int, int]]:
    """Return non-overlapping (start, end) spans, preferring longer phrases."""
    patterns = [(w, _phrase_pattern(w)) for w in sorted(words, key=lambda x: len(normalize_sentiment_text(x)), reverse=True)]
    occupied: list[tuple[int, int]] = []
    hits: list[tuple[int, int]] = []

    for _word, pat in patterns:
        for m in pat.finditer(blob):
            start, end = m.start(), m.end()
            if polarity == "negative" and _is_spurious_neg_hit(blob, start):
                continue
            if any(not (end <= s or start >= e) for s, e in occupied):
                continue
            occupied.append((start, end))
            hits.append((start, end))

    return sorted(hits, key=lambda t: t[0])


def _negation_count_before(blob: str, match_start: int) -> int:
    before = blob[:match_start].strip()
    if not before:
        return 0

    tokens = before.split()
    window = tokens[-6:]
    if not window:
        return 0

    count = 0
    i = 0
    while i < len(window):
        if i + 1 < len(window):
            pair = f"{window[i]} {window[i + 1]}"
            if pair in NEGATION_PHRASES:
                count += 1
                i += 2
                continue
        if window[i] in NEGATION_TOKENS:
            count += 1
        i += 1
    return count


def _flip_polarity(polarity: str) -> str:
    if polarity == "positive":
        return "negative"
    if polarity == "negative":
        return "positive"
    return "neutral"


def _effective_label(blob: str, start: int, base: str) -> str:
    if _negation_count_before(blob, start) % 2 == 1:
        return _flip_polarity(base)
    return base


def _clause_sentiment(clause: str) -> str:
    blob = normalize_sentiment_text(clause)
    if not blob:
        return "neutral"

    pos_score = 0
    neg_score = 0

    for start, _end in _find_hits(blob, POS_WORDS, polarity="positive"):
        label = _effective_label(blob, start, "positive")
        if label == "positive":
            pos_score += 1
        elif label == "negative":
            neg_score += 1

    for start, _end in _find_hits(blob, NEG_WORDS, polarity="negative"):
        label = _effective_label(blob, start, "negative")
        if label == "negative":
            neg_score += 1
        elif label == "positive":
            pos_score += 1

    if neg_score > pos_score:
        return "negative"
    if pos_score > neg_score:
        return "positive"
    return "neutral"


def detect_sentiment(text: str) -> str:
    """Return positive | negative | neutral for marketing mention text."""
    clauses = split_clauses(text)
    labels = [_clause_sentiment(c) for c in clauses]

    # Prefer last non-neutral clause (text after "nhưng" often carries the verdict).
    for label in reversed(labels):
        if label != "neutral":
            return label
    return "neutral"
