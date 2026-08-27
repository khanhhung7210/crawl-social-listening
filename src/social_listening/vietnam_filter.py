"""Vietnam relevance filter for cinema social listening.

Drops foreign Galaxy/CGV chains and non-VN language noise while keeping
Vietnamese (with/without diacritics) and VN cinema context.
"""

from __future__ import annotations

import re
import unicodedata

# Strong foreign Galaxy / cinema signals
FOREIGN_NEGATIVE = re.compile(
    r"""
    galaxycinemaegypt|galaxy\s*cinema\s*egypt|cairo|alexandria|
    galaxycinemas?\s*(india|pakistan|dubai|uae|bahrain|kuwait|qatar|saudi)|
    mumbai|delhi|karachi|lahore|dubai|abu\s*dhabi|
    #galaxycinemaegypt|#cgvindia|#cgvkorea|
    cgv\s*(korea|indonesia|china)|
    영화|シネマ|سينما|سينما|티켓
    """,
    re.I | re.VERBOSE,
)

# Non-Latin scripts that usually mean foreign cinema chatter (unless VN kept separately)
ARABIC = re.compile(r"[\u0600-\u06FF]")
HANGUL = re.compile(r"[\uAC00-\uD7AF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
CJK = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")

VN_DIACRITICS = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]"
)

# Vietnamese cinema / market context (ascii + common spellings)
VN_CONTEXT = re.compile(
    r"""
    \b(vietnam|việt\s*nam|viet\s*nam|vn\b|saigon|sài\s*gòn|sai\s*gon|
    hanoi|hà\s*nội|ha\s*noi|đà\s*nẵng|da\s*nang|cần\s*thơ|can\s*tho|
    tp\.?\s*hcm|hcm\b|tphcm|hồ\s*chí\s*minh|ho\s*chi\s*minh|
    galaxycine\.vn|cgv\.vn|lottecinemavn|bhdstar|beta\s*cineplex|
    rạp\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    rap\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    (galaxy|cgv|lotte|beta|bhd|cinestar)\s*(cinema|cineplex|cinemas)?\s*(việt|viet|vn)|
    cgv\s*cinemas\s*vietnam|cgvcinemasvietnam|
    đặt\s*vé|dat\s*ve|xem\s*phim|chiếu\s*phim|chieu\s*phim|
    vé\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    ve\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    #rapgalaxy|#galaxycinema|#cgvvietnam|
    tan\s*binh|tân\s*bình|nguyễn\s*trãi|nguyen\s*trai|
    sư\s*vạn\s*hạnh|su\s*van\s*hanh|vincom|aeon\s*mall\s*(bình|binh|tân|tan)|
    phòng\s*vé|phong\s*ve|rạp\s*chiếu|rap\s*chieu
    )
    """,
    re.I | re.VERBOSE,
)

VN_OWNED_HANDLES = re.compile(
    r"""
    (galaxycine\.vn|cgvcinemasvietnam|lottecinemavn|bhdstarcineplex|
    betacinemas|cinestar\.vn|encorefilmsvn|universalpicturesvn|
    facebook\.com/.{0,40}(galaxycinema|cgvvietnam|lottecinema\.vn))
    """,
    re.I | re.VERBOSE,
)

# Common VN function words without diacritics (help keep ascii VN comments)
VN_ASCII_HINTS = re.compile(
    r"\b(khong|ko\b|duoc|được|voi|voi\b|nhe|nha|oi\b|qua\b|nay|hom\s*nay|"
    r"rap\b|ve\b|phim\b|hay\b|te\b|xin\b|cam\s*on|camon|thanks\s*ad|"
    r"ib\b|inbox|dat\s*ve|xem\s*gi|lich\s*chieu|suat\s*chieu)\b",
    re.I,
)

# Latin foreign chatter (IT/ID/ES…) without VN signal — common Odyssey noise
FOREIGN_LATIN = re.compile(
    r"""
    \b(possiamo|sceneggiatura|difetti|nella|musica\s+di\s+grande|
    ora\s+passiamo|karya\s+epos|sekarang\s+kita|beralih\s+ke|
    i\s+la\s+galigo|epos\s+bugis|assassin'?s?\s+creed|
    honda\s+odyssey|homer(?:ic)?\b|odissea\b|pelicula\b|
    film\s+italiano|cineforum)\b
    """,
    re.I | re.VERBOSE,
)


def _strip_accents(text: str) -> str:
    nk = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nk if unicodedata.category(ch) != "Mn")


def is_vietnam_relevant(
    text: str | None = None,
    permalink: str | None = None,
    author: str | None = None,
    platform: str | None = None,
) -> bool:
    """Return True if mention looks Vietnam-market relevant."""
    blob = " ".join([text or "", permalink or "", author or ""])
    if not blob.strip():
        return False

    # Always keep VN news / owned domains
    if VN_OWNED_HANDLES.search(blob):
        return True
    if (platform or "").lower() in {"news", "google"} and VN_CONTEXT.search(blob):
        return True

    if FOREIGN_NEGATIVE.search(blob):
        return False
    if FOREIGN_LATIN.search(blob) and not VN_DIACRITICS.search(blob) and not VN_CONTEXT.search(blob):
        return False

    # Heavy foreign script without VN context → drop
    foreign_script = bool(
        ARABIC.search(blob) or HANGUL.search(blob) or DEVANAGARI.search(blob) or CJK.search(blob)
    )
    if foreign_script and not VN_DIACRITICS.search(blob) and not VN_CONTEXT.search(blob):
        return False

    if VN_DIACRITICS.search(blob):
        return True
    if VN_CONTEXT.search(blob):
        return True
    if VN_ASCII_HINTS.search(_strip_accents(blob)):
        return True

    # Brand-only English "#galaxycinema" with no VN signal → drop (often foreign chain)
    return False
