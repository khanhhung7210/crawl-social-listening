"""Rule-based film intent + sentiment (Distribution v1.1).

Layers (after film detection):
  - Purchase intent: positive phrases with local negation window
  - Sentiment (khen/chê): clause split on nhưng/mà/tuy nhiên, then keyword match
"""

from __future__ import annotations

import re
import unicodedata

# --- Intent phrases -----------------------------------------------------------

POSITIVE_INTENT: list[str] = [
    "đi xem",
    "di xem",
    "săn vé",
    "san ve",
    "mua vé",
    "mua ve",
    "book vé",
    "book ve",
    "book ticket",
    "canh vé",
    "canh ve",
    "canh ngày",
    "canh ngay",
    "chờ ra rạp",
    "cho ra rap",
    "ra rạp",
    "ra rap",
    "must watch",
    "must see",
    "phải xem",
    "phai xem",
    "xem ngay",
    "ra rạp coi",
    "ra rap coi",
    "coi liền",
    "coi lien",
    "muốn xem",
    "muon xem",
    "sẽ xem",
    "se xem",
    "nên xem",
    "nen xem",
    "đáng xem",
    "dang xem",
    "đang hóng",
    "dang hong",
    "hóng phim",
    "hong phim",
    "hóng trailer",
    "hong trailer",
    "looking forward",
    "can't wait",
    "cant wait",
    "want to see",
    "cuối tuần coi",
    "cuoi tuan coi",
    "để dành coi",
    "de danh coi",
    "nghe nói hay",
    "nghe noi hay",
]

NEGATION_INTENT: list[str] = [
    "không xem",
    "khong xem",
    "khỏi xem",
    "khoi xem",
    "chưa chắc xem",
    "chua chac xem",
    "để coi đã",
    "de coi da",
    "không muốn xem",
    "khong muon xem",
    "skip",
    "bỏ qua",
    "bo qua",
    "không quan tâm",
    "khong quan tam",
    "not interested",
]

WATCHED_MARKERS: list[str] = [
    "đã xem",
    "da xem",
    "vừa xem",
    "vua xem",
    "xem xong",
    "coi xong",
    "xem rồi",
    "xem roi",
    "coi rồi",
    "coi roi",
    "ra về",
    "ra ve",
    "watched",
    "just watched",
    "after watching",
]

# --- Sentiment phrases (min length >= 3 after normalize; avoid "do"/"on") ------

POS_SENTIMENT: list[str] = [
    "hay quá",
    "hay qua",
    "quá hay",
    "qua hay",
    "rất hay",
    "rat hay",
    "đáng xem",
    "dang xem",
    "cảm động",
    "cam dong",
    "xúc động",
    "xuc dong",
    "diễn xuất tốt",
    "dien xuat tot",
    "kịch bản chắc",
    "kich ban chac",
    "xuất sắc",
    "xuat sac",
    "kiệt tác",
    "kiet tac",
    "đỉnh",
    "dinh",
    "tuyệt",
    "tuyet",
    "thích",
    "thich",
    "nên xem",
    "nen xem",
    "worth watching",
    "masterpiece",
    "amazing",
    "loved it",
    "hay",
    "ổn",
    "tot",
    "tốt",
]

NEG_SENTIMENT: list[str] = [
    "phí tiền",
    "phi tien",
    "thất vọng",
    "that vong",
    "gượng ép",
    "guong ep",
    "không đáng",
    "khong dang",
    "lê thê",
    "le the",
    "nhạt",
    "nhat",
    "chán",
    "chan",
    "dở",
    "te",
    "tệ",
    "boring",
    "disappointing",
    "overrated",
    "flop",
    "thảm họa",
    "tham hoa",
]

CLAUSE_SPLIT_RE = re.compile(
    r"[.!?;…]+|\n+|\s+(?:nhưng|nhung|tuy nhiên|tuy nhien|tuy|mà|ma|dù|du)\s+",
    re.IGNORECASE,
)

DEFAULT_CONTEXT: list[str] = [
    "rap",
    "chieu",
    "ve",
    "trailer",
    "phim",
    "review",
    "suat",
    "cinema",
    "movie",
    "film",
    "watch",
]


def normalize(text: str) -> str:
    blob = (text or "").lower().replace("đ", "d").replace("Đ", "d")
    blob = unicodedata.normalize("NFD", blob)
    blob = "".join(ch for ch in blob if unicodedata.category(ch) != "Mn")
    blob = re.sub(r"[^a-z0-9#\s]+", " ", blob)
    return re.sub(r"\s+", " ", blob).strip()


def _phrase_in(blob: str, phrase: str) -> bool:
    """Substring match; short single tokens require word boundaries."""
    p = normalize(phrase)
    if not p or not blob:
        return False
    if " " in p or len(p) >= 4 or p.startswith("#"):
        return p in blob
    return bool(re.search(rf"(?<![a-z0-9#]){re.escape(p)}(?![a-z0-9])", blob))


def _any_phrase(blob: str, phrases: list[str]) -> str | None:
    # Longer phrases first to prefer specific hits
    for phrase in sorted(phrases, key=lambda x: len(normalize(x)), reverse=True):
        if _phrase_in(blob, phrase):
            return phrase
    return None


def _negation_near(blob: str, phrase: str, window: int = 5) -> bool:
    """True if a negation keyword sits within ~window tokens before the phrase."""
    p = normalize(phrase)
    idx = blob.find(p)
    if idx < 0:
        return False
    before = blob[:idx].split()
    tail = before[-window:] if before else []
    vicinity = " ".join(tail + blob[idx : idx + len(p)].split()[:1])
    return any(_phrase_in(vicinity, neg) or neg in " ".join(tail) for neg in NEGATION_INTENT)


def has_movie_context(text: str, extra: list[str] | None = None) -> bool:
    blob = normalize(text)
    words = list(DEFAULT_CONTEXT)
    if extra:
        words.extend(normalize(w) for w in extra if w)
    return any(_phrase_in(blob, w) for w in words)


def split_clauses(text: str) -> list[str]:
    blob = text or ""
    parts = [p.strip() for p in CLAUSE_SPLIT_RE.split(blob) if p and p.strip()]
    return parts or [blob]


def detect_sentiment(text: str) -> str:
    """positive | negative | neutral — clause-aware, 'nhưng' clause wins when mixed."""
    clauses = split_clauses(text)
    labels: list[str] = []
    for clause in clauses:
        blob = normalize(clause)
        pos = _any_phrase(blob, POS_SENTIMENT)
        neg = _any_phrase(blob, NEG_SENTIMENT)
        if pos and neg:
            # Same clause both → prefer negative (typical "hay nhưng dở")
            labels.append("negative")
        elif neg:
            labels.append("negative")
        elif pos:
            labels.append("positive")
        else:
            labels.append("neutral")

    # Prefer last non-neutral clause (post-"nhưng" emphasis)
    for label in reversed(labels):
        if label != "neutral":
            return label
    return "neutral"


def classify_intent(text: str) -> str | None:
    """Return intent label or None if unclassified.

    Labels:
      want_to_see | watched_praise | watched_criticize | not_interested

    Order: not_interested → watched+sentiment → purchase intent →
    clear sentiment alone (WOM khen/chê without explicit "đã xem").
    """
    blob = normalize(text)
    if not blob:
        return None

    # Explicit not-interested / negation of watching
    if _any_phrase(blob, NEGATION_INTENT):
        hit = _any_phrase(blob, POSITIVE_INTENT)
        if not hit or _negation_near(blob, hit):
            return "not_interested"
        # e.g. "không hay nhưng vẫn muốn xem" — keep positive intent below
        # Fall through only when a clear positive intent sits outside negation.

    watched = bool(_any_phrase(blob, WATCHED_MARKERS))
    sentiment = detect_sentiment(text)

    if watched:
        if sentiment == "negative":
            return "watched_criticize"
        if sentiment == "positive":
            return "watched_praise"
        # Watched but no clear sentiment — leave unclassified for WOM panels
        return None

    hit = _any_phrase(blob, POSITIVE_INTENT)
    if hit and not _negation_near(blob, hit):
        return "want_to_see"

    return None
