"""Vietnamese sentence normalization for PhoBERT — keep diacritics.

This is sentiment-input prep only. Keyword / film / dedup matching still use
their own normalizers (which may strip accents on purpose).
"""

from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache

# ---------------------------------------------------------------------------
# Noise / format patterns
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_./]+")
_HASHTAG_KEEP_RE = re.compile(r"#(\w+)", re.UNICODE)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_EMOJI_RUN_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)
_LAUGH_RE = re.compile(
    r"(?:^|\s)(?:[:=;]-?[)(/\\DpP]{1,3}|[+]_+[+]|keke+|haha+|hihi+|kk{2,}|ajaj+)(?:\s|$)",
    re.IGNORECASE,
)
_ELONGATED_CHAR_RE = re.compile(r"(.)\1{2,}", re.UNICODE)
_PUNCT_RUN_RE = re.compile(r"([!?.,…])\1{1,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([!?.,;:…])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[「])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([)\]」])")
_MISSING_SPACE_AFTER_PUNCT_RE = re.compile(
    r"([!?.,;…])([^\s\d!?.,;:…])"  # không chèn space sau ':' (tránh ":)" → ": )")
)
_EMOTICON_SPACE_RE = re.compile(r":\s+([)(/pPD])")
_MULTISPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")

# Token teencode / lỗi gõ thường gặp → chính tả có dấu.
# Tránh map từ mơ hồ (do/qua/cung/that...) để không làm lệch nghĩa.
_TEENCODE_MAP: dict[str, str] = {
    # phủ định
    "khong": "không",
    "ko": "không",
    "kg": "không",
    "khg": "không",
    "hok": "không",
    "k0": "không",
    "hong": "không",
    "k": "không",
    # đại từ
    "mk": "mình",
    "mik": "mình",
    "tui": "tôi",
    "bn": "bạn",
    # động từ / trợ từ chat
    "dc": "được",
    "đc": "được",
    "đươc": "được",
    "duoc": "được",
    "vs": "với",
    "cx": "cũng",
    "nx": "nữa",
    "nua": "nữa",
    # không map "nay"→"này" (làm hỏng "hôm nay")
    "ntn": "như thế nào",
    "j": "gì",
    "bh": "bây giờ",
    "bâyh": "bây giờ",
    "bayh": "bây giờ",
    "ik": "đi",
    "thik": "thích",
    "thich": "thích",
    "wa": "quá",
    "wá": "quá",
    "qá": "quá",
    "z": "vậy",
    "zậy": "vậy",
    "zay": "vậy",
    "ak": "à",
    "àk": "à",
    "uh": "ừ",
    "uhm": "ừ",
    "uk": "ừ",
    "okie": "ok",
    "okela": "ok",
    "oke": "ok",
    "okay": "ok",
    "nt": "nói thật",
    "thâtt": "thật",
    "thatt": "thật",
    "rat": "rất",
    "rât": "rất",
    "rấtt": "rất",
    "hayy": "hay",
    "hayyy": "hay",
    "dinh": "đỉnh",
    "đỉn": "đỉnh",
    "xink": "xinh",
    "dep": "đẹp",
    "đep": "đẹp",
    "xau": "xấu",
    "tệe": "tệ",
    "chánn": "chán",
    "chan": "chán",
    "tuyet": "tuyệt",
    "tuyêt": "tuyệt",
    "camdong": "cảm động",
    "cảmđộng": "cảm động",
    "thatvong": "thất vọng",
    "thấtvọng": "thất vọng",
    "xemdc": "xem được",
    "roi": "rồi",
    "rùi": "rồi",
    "rui": "rồi",
}

# Cụm từ (áp dụng trước map token)
_PHRASE_FIXES: list[tuple[str, str]] = [
    (r"\bxuat\s+sac\b", "xuất sắc"),
    (r"\bcam\s+dong\b", "cảm động"),
    (r"\bthat\s+vong\b", "thất vọng"),
    (r"\bkhong\s+nen\b", "không nên"),
    (r"\bko\s+nen\b", "không nên"),
    (r"\bk\s+nen\b", "không nên"),
    (r"\bko\s+hay\b", "không hay"),
    (r"\bk\s+hay\b", "không hay"),
    (r"\bxem\s+dc\b", "xem được"),
    (r"\bxem\s+đc\b", "xem được"),
    (r"\bnoi\s+dung\b", "nội dung"),
    (r"\bdien\s+xuat\b", "diễn xuất"),
    (r"\bhinh\s+anh\b", "hình ảnh"),
    (r"\bket\s+phim\b", "kết phim"),
    (r"\bbo\s+ve\b", "bỏ về"),
    (r"\brat\s+hay\b", "rất hay"),
    (r"\brat\s+te\b", "rất tệ"),
    (r"\bqua\s+hay\b", "quá hay"),
    (r"\bqua\s+te\b", "quá tệ"),
    (r"\bcuc\s+hay\b", "cực hay"),
    (r"\bcuc\s+te\b", "cực tệ"),
    (r"\bnói\s+thât\b", "nói thật"),
    (r"\bnoi\s+that\b", "nói thật"),
    (r"\bbây\s+h\b", "bây giờ"),
    (r"\bbay\s+h\b", "bây giờ"),
    (r"\bnhung\s+ma\b", "nhưng mà"),
    (r"\bnhung\s+mà\b", "nhưng mà"),
    (r"\bnhung\b", "nhưng"),
    (r"\bhom\s+nay\b", "hôm nay"),
]


def _fix_encoding(text: str) -> str:
    try:
        import ftfy

        return ftfy.fix_text(text)
    except Exception:
        return text


def _collapse_elongation(text: str) -> str:
    # hayyyy → hayy (giữ nhấn nhẹ), !!!! → !!
    text = _ELONGATED_CHAR_RE.sub(r"\1\1", text)
    text = _PUNCT_RUN_RE.sub(r"\1\1", text)
    return text


def _format_sentence_spacing(text: str) -> str:
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_CLOSE_RE.sub(r"\1", text)
    text = _MISSING_SPACE_AFTER_PUNCT_RE.sub(r"\1 \2", text)
    text = _EMOTICON_SPACE_RE.sub(r":\1", text)
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("–", "-").replace("—", "-")
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


@lru_cache(maxsize=1)
def _teencode_token_re() -> re.Pattern[str]:
    keys = sorted((k for k in _TEENCODE_MAP if " " not in k), key=len, reverse=True)
    escaped = [re.escape(k) for k in keys]
    # Word-ish boundaries that work with Vietnamese letters
    return re.compile(rf"(?<![\wÀ-ỹ])({'|'.join(escaped)})(?![\wÀ-ỹ])", re.IGNORECASE)


def _apply_phrase_fixes(text: str) -> str:
    out = text
    for pattern, repl in _PHRASE_FIXES:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out


def _apply_teencode_fixes(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        fixed = _TEENCODE_MAP.get(raw.lower())
        if not fixed:
            return raw
        if raw.isupper() and len(raw) > 1:
            return fixed.upper()
        if raw[0].isupper():
            return fixed[:1].upper() + fixed[1:]
        return fixed

    return _teencode_token_re().sub(repl, text)


def _sentence_case_light(text: str) -> str:
    """Nếu cả câu IN HOA hét, hạ về chữ thường (giữ dấu)."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 8 and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.85:
        return text.lower()
    return text


def prepare_sentiment_text(text: str) -> str:
    """
    Format câu + chỉnh tả nhẹ (teencode / lỗi gõ) cho input PhoBERT.

    Giữ nguyên dấu tiếng Việt (NFC). Không strip accent.
    Matching / film / dedup dùng normalizer riêng — không dùng hàm này.
    """
    if text is None:
        return ""

    out = str(text)
    out = html.unescape(out)
    out = _fix_encoding(out)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = unicodedata.normalize("NFC", out)
    out = _ZERO_WIDTH_RE.sub("", out)
    out = _CTRL_RE.sub("", out)
    out = _HTML_TAG_RE.sub(" ", out)
    out = _URL_RE.sub(" ", out)
    out = _EMAIL_RE.sub(" ", out)
    out = _MENTION_RE.sub(" ", out)
    out = _HASHTAG_KEEP_RE.sub(r"\1", out)
    out = _LAUGH_RE.sub(" ", out)
    out = _EMOJI_RUN_RE.sub(" ", out)

    out = _collapse_elongation(out)
    out = _apply_phrase_fixes(out)
    out = _apply_teencode_fixes(out)
    out = _sentence_case_light(out)
    out = _format_sentence_spacing(out)
    out = unicodedata.normalize("NFC", out)
    return out.strip()
