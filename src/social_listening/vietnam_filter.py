"""Vietnam cinema market relevance filter for social listening.

Brand detection and market scope are separate concerns:
  detect_competitive_brands(text)  → which brands are mentioned
  is_vietnam_relevant(...)         → whether content belongs to Vietnam cinema market

Do NOT treat competitor names (CGV, Lotte, Megabox…) as proof of Vietnam market.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

MarketScope = Literal["vietnam", "foreign", "unrelated", "ambiguous"]

# VN-owned domains / handles — always in scope
VN_OWNED_HANDLES = re.compile(
    r"""
    (galaxycine\.vn|cgvcinemasvietnam|lottecinemavn|bhdstarcineplex|
    betacinemas|cinestar\.vn|encorefilmsvn|universalpicturesvn|
    facebook\.com/.{0,40}(galaxycinema|cgvvietnam|lottecinema\.vn))
    """,
    re.I | re.VERBOSE,
)

# Foreign-market publisher domains (article about that market even if written in Vietnamese)
FOREIGN_PUBLISHER = re.compile(
    r"""
    (cineplay\.co\.kr|koreatimes\.co\.kr|koreajoongangdaily\.joins\.com|
    japantimes\.co\.jp|variety\.com|hollywoodreporter\.com)
    """,
    re.I | re.VERBOSE,
)

# Strong Vietnam cinema / market context
VN_MARKET = re.compile(
    r"""
    \b(việt\s*nam|viet\s*nam|vietnam|
    (?<![-a-z/])vn(?![-a-z0-9])|
    saigon|sài\s*gòn|sai\s*gon|
    hà\s*nội|ha\s*noi|hanoi|
    đà\s*nẵng|da\s*nang|
    cần\s*thơ|can\s*tho|
    hải\s*phòng|hai\s*phong|
    bình\s*dương|binh\s*duong|
    đồng\s*nai|dong\s*nai|
    tp\.?\s*hcm|hcm\b|tphcm|hồ\s*chí\s*minh|ho\s*chi\s*minh|
    galaxycine\.vn|cgv\.vn|lottecinemavn|bhdstar|beta\s*cineplex|
    (galaxy|cgv|lotte|beta|bhd|cinestar|megabox)\s*(cinema|cineplex|cinemas)?\s*(việt|viet|vn)\b|
    cgv\s*cinemas\s*vietnam|cgvcinemasvietnam|
    rạp\s*(galaxy|cgv|lotte|beta|bhd|cinestar)\b|
    rap\s*(galaxy|cgv|lotte|beta|bhd|cinestar)\b|
    (galaxy|cgv|lotte|beta|bhd|cinestar)\s+(tại|tai)\s+
    thị\s*trường\s*(điện\s*ảnh\s*)?(việt|viet|vn)|
    phòng\s*vé\s*(việt|viet|vn)?|phong\s*ve|
    đặt\s*vé|dat\s*ve|xem\s*phim|chiếu\s*phim|chieu\s*phim|
    vé\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    ve\s*(galaxy|cgv|lotte|beta|bhd|cinestar)|
    tan\s*binh|tân\s*bình|nguyễn\s*trãi|nguyen\s*trai|
    sư\s*vạn\s*hạnh|su\s*van\s*hanh|vincom|aeon\s*mall
    )
    """,
    re.I | re.VERBOSE,
)

# Strong foreign cinema market (Korea, Japan, SEA…) — OUT unless Vietnam market also present
FOREIGN_MARKET = re.compile(
    r"""
    \b(hàn\s*quốc|han\s*quoc|korea|hàn\s*quốc|south\s*korea|north\s*korea|
    seoul|busan|hongdae|daegu|daegwallyeong|incheon|
    nhật\s*bản|nhat\s*ban|japan|tokyo|osaka|
    philippines|indonesia|malaysia|thailand|singapore|
    india|pakistan|egypt|uae|dubai|china|trung\s*quốc)\b|
    cgv\s*(korea|indonesia|china|philippines)|
    lotte\s*cinema\s*(korea|indonesia)|
    megabox\s+hongdae|
    tại\s+(các\s+)?rạp\s+(ở\s+)?hàn|
    ra\s+(mắt\s+)?(tại\s+)?rạp\s+hàn|
    khởi\s*chiếu\s+tại\s+hàn|
    phát\s*hành\s+(độc\s*quyền\s+)?tại\s+cgv\s+(sau|tại\s+hàn)|
    galaxy\s*cinema\s*egypt|galaxycinemaegypt|
    mumbai|delhi|karachi|cairo|alexandria
    """,
    re.I | re.VERBOSE,
)

# Non-cinema finance/tech noise (OUT when no cinema vocabulary)
NON_CINEMA_TOPICS = re.compile(
    r"""
    \b(bitcoin|crypto|ethereum|nvidia|microsoft|amazon|apple\s*inc|
    fed\b|lãi\s*suất|lai\s*suat|bitget|forex|stock\s*market|
    chứng\s*khoán|chung\s*khoan|giá\s*vàng|gia\s*vang)\b
    """,
    re.I | re.VERBOSE,
)

CINEMA_VOCAB = re.compile(
    r"""
    \b(phim|rạp|rap\b|cinema|cineplex|cgv|galaxy|lotte|beta|bhd|cinestar|
    megabox|chiếu\s*phim|chieu\s*phim|xem\s*phim|vé\s*phim|ve\s*phim|
    phòng\s*vé|phong\s*ve|box\s*office|khởi\s*chiếu|khoi\s*chieu)\b
    """,
    re.I | re.VERBOSE,
)

VN_DIACRITICS = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]"
)

ARABIC = re.compile(r"[\u0600-\u06FF]")
HANGUL = re.compile(r"[\uAC00-\uD7AF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
CJK = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")

VN_ASCII_HINTS = re.compile(
    r"\b(khong|ko\b|duoc|được|rap\b|ve\b|phim\b|hay\b|dat\s*ve|xem\s*phim|"
    r"lich\s*chieu|suat\s*chieu|cam\s*on|camon)\b",
    re.I,
)

FOREIGN_LATIN = re.compile(
    r"""
    \b(possiamo|sceneggiatura|karya\s+epos|sekarang\s+kita|
    assassin'?s?\s*creed|honda\s+odyssey|pelicula\b|cineforum)\b
    """,
    re.I | re.VERBOSE,
)

_STRICT_PLATFORMS = frozenset({"news"})


def _strip_accents(text: str) -> str:
    nk = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nk if unicodedata.category(ch) != "Mn")


def _blob(
    text: str | None = None,
    permalink: str | None = None,
    author: str | None = None,
) -> str:
    return " ".join([text or "", permalink or "", author or ""]).strip()


def classify_vietnam_cinema_market(
    text: str | None = None,
    permalink: str | None = None,
    author: str | None = None,
    platform: str | None = None,
) -> MarketScope:
    """Classify whether content belongs to the Vietnam cinema market."""
    blob = _blob(text, permalink, author)
    if not blob:
        return "ambiguous"

    plat = (platform or "").lower()
    if plat == "google_maps":
        plat = "google"

    if VN_OWNED_HANDLES.search(blob):
        return "vietnam"

    if FOREIGN_PUBLISHER.search(blob) and not VN_MARKET.search(blob):
        return "foreign"

    has_cinema = bool(CINEMA_VOCAB.search(blob))
    if NON_CINEMA_TOPICS.search(blob) and not has_cinema:
        return "unrelated"

    vn_market = bool(VN_MARKET.search(blob))
    foreign_market = bool(FOREIGN_MARKET.search(blob))

    if foreign_market and not vn_market:
        return "foreign"

    if vn_market:
        return "vietnam"

    if plat in _STRICT_PLATFORMS:
        return "ambiguous"

    if FOREIGN_LATIN.search(blob) and not VN_DIACRITICS.search(blob):
        return "foreign"

    foreign_script = bool(
        ARABIC.search(blob) or HANGUL.search(blob) or DEVANAGARI.search(blob) or CJK.search(blob)
    )
    if foreign_script and not VN_DIACRITICS.search(blob):
        return "foreign"

    # Social / Google Maps UGC: Vietnamese language + cinema context is enough when no foreign market.
    if plat in {"google"} and (VN_DIACRITICS.search(blob) or VN_ASCII_HINTS.search(_strip_accents(blob))):
        return "vietnam"

    if VN_DIACRITICS.search(blob) and has_cinema:
        return "vietnam"

    if VN_ASCII_HINTS.search(_strip_accents(blob)) and has_cinema:
        return "vietnam"

    return "ambiguous"


def is_vietnam_relevant(
    text: str | None = None,
    permalink: str | None = None,
    author: str | None = None,
    platform: str | None = None,
) -> bool:
    """Return True only when content belongs to the Vietnam cinema market."""
    return classify_vietnam_cinema_market(text, permalink, author, platform) == "vietnam"
