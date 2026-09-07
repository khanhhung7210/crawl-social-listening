"""Brand keyword / exclude rules for Galaxy cinema social listening (VN market).

Source of truth for competitive SoV tagging. Keep import + dashboard + purge aligned.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Cinema context (BHD / Beta bare-token rescue)
# ---------------------------------------------------------------------------

CINEMA_CONTEXT_RE = re.compile(
    r"(?:"
    r"r[aạ]p|"
    r"xem\s*phim|"
    r"\bv[eé]\b|"
    r"su[aấ]t\s*chi[eế]u|"
    r"ph[oò]ng\s*chi[eế]u|"
    r"l[iị]ch\s*chi[eế]u|"
    r"[đd][aặ]t\s*v[eé]|"
    r"\bimax\b|\b4dx\b|\bscreenx\b|"
    r"\bcinema\b|\bcinemas\b|\bcineplex\b"
    r")",
    re.I,
)

# ---------------------------------------------------------------------------
# Competitive / tagging patterns (strict — used for SoV + mention_brands)
# ---------------------------------------------------------------------------

GLX_BRANCHES: list[str] = [
    "galaxy nguyễn du",
    "galaxy nguyen du",
    "galaxy tân bình",
    "galaxy tan binh",
    "galaxy kinh dương vương",
    "galaxy kinh duong vuong",
    "galaxy quang trung",
    "galaxy sư vạn hạnh",
    "galaxy su van hanh",
    "galaxy mipec long biên",
    "galaxy mipec long bien",
    "galaxy hn centre",
    "galaxy hanoi centre",
    "galaxy hà nội centre",
    "galaxy ha noi centre",
    "galaxy hà nội",
    "galaxy ha noi",
    "galaxy đà nẵng",
    "galaxy da nang",
    "galaxy bmt",
    "galaxy buôn mê",
    "galaxy buon me",
    "galaxy nha trang",
    "galaxy cần thơ",
    "galaxy can tho",
    "galaxy long xuyên",
    "galaxy long xuyen",
]

CGV_BRANCHES: list[str] = [
    "cgv royal city",
    "cgv bà triệu",
    "cgv ba trieu",
    "cgv thụy khuê",
    "cgv thuy khue",
    "cgv lương yên",
    "cgv luong yen",
    "cgv vincom",
    "cgv aeon",
    "cgv landmark 81",
    "cgv landmark",
    "cgv sư vạn hạnh",
    "cgv su van hanh",
    "cgv crescent mall",
]

LOTTE_BRANCHES: list[str] = [
    "lotte cinema west lake",
    "lotte cinema cantavil",
    "lotte cinema landmark",
    "lotte cinema gò vấp",
    "lotte cinema go vap",
    "lotte cinema đống đa",
    "lotte cinema dong da",
    "lotte cinema nam sài gòn",
    "lotte cinema nam sai gon",
    "lotte west lake",
    "lotte cantavil",
    "lotte landmark",
]

BHD_BRANCHES: list[str] = [
    "bhd star bitexco",
    "bhd star icon68",
    "bhd star icon 68",
    "bhd star vincom thảo điền",
    "bhd star vincom thao dien",
    "bhd star 3/2",
    "bhd star phạm hùng",
    "bhd star pham hung",
]

BETA_BRANCHES: list[str] = [
    "beta xuân thuỷ",
    "beta xuân thủy",
    "beta xuan thuy",
    "beta tây sơn",
    "beta tay son",
    "beta aeon smart city",
    "beta aeon",
    "beta thanh xuân",
    "beta thanh xuan",
    "beta gia lai",
    "beta biên hòa",
    "beta bien hoa",
]

CINESTAR_BRANCHES: list[str] = [
    "cinestar sinh viên",
    "cinestar sinh vien",
    "cinestar park city",
    "cinestar hai bà trưng",
    "cinestar hai ba trung",
    "cinestar quốc thanh",
    "cinestar quoc thanh",
]

# Foreign cinema market — suppress competitor tags when content is clearly non-VN.
FOREIGN_CINEMA_MARKET_RE = re.compile(
    r"""
    \b(hàn\s*quốc|han\s*quoc|korea|south\s*korea|
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
    galaxy\s*cinema\s*egypt|galaxycinemaegypt|
    starnews?korea|\.co\.kr\b
    """,
    re.I | re.VERBOSE,
)

VN_CINEMA_MARKET_RE = re.compile(
    r"""
    \b(việt\s*nam|viet\s*nam|vietnam|
    (?<![-a-z/])vn(?![-a-z0-9])|
    hà\s*nội|ha\s*noi|hanoi|
    tp\.?\s*hcm|hcm\b|tphcm|hồ\s*chí\s*minh|ho\s*chi\s*minh|
    đà\s*nẵng|da\s*nang|cần\s*thơ|can\s*tho|
    bình\s*dương|binh\s*duong|đồng\s*nai|dong\s*nai|
    hải\s*phòng|hai\s*phong|
    saigon|sài\s*gòn|sai\s*gon)\b|
    thị\s*trường\s*(điện\s*ảnh\s*)?(việt|viet|vn)|
    cgv\s*(vietnam|việt\s*nam|viet\s*nam)|
    lotte\s*cinema\s*(việt\s*nam|viet\s*nam|vietnam)|
    galaxy\s*cinema\s*(việt\s*nam|viet\s*nam|vietnam)|
    tại\s+(hà\s*nội|ha\s*noi|hanoi|tp\.?\s*hcm|tphcm|việt\s*nam|vietnam|
             đà\s*nẵng|da\s*nang|cần\s*thơ|can\s*tho|bình\s*dương|binh\s*duong)
    """,
    re.I | re.VERBOSE,
)

FOREIGN_PUBLISHER_RE = re.compile(
    r"cineplay\.co\.kr|koreatimes\.co\.kr|koreajoongangdaily\.joins\.com|starnews?korea",
    re.I,
)

COMPETITIVE_PATTERNS: dict[str, list[str]] = {
    "glx": [
        "galaxy cinema",
        "galaxy cine",
        "rạp galaxy",
        "rap galaxy",
        "#galaxycinema",
        "#galaxymovie",
        *GLX_BRANCHES,
    ],
    "cgv": [
        "cgv cinemas",
        "cgv cinema",
        "cgv vietnam",
        "cgv việt nam",
        "cgv viet nam",
        "rạp cgv",
        "rap cgv",
        "#cgvcinemas",
        "#cgvvietnam",
        "#cgv",
        "cgv",
        *CGV_BRANCHES,
    ],
    "lotte": [
        "lotte cinema",
        "lotte cinemas",
        "lotte cine",
        "rạp lotte cinema",
        "rap lotte cinema",
        "#lottecinema",
        *LOTTE_BRANCHES,
    ],
    "beta": [
        "beta cinemas",
        "beta cineplex",
        "rạp beta",
        "rap beta",
        "#betacinemas",
        *BETA_BRANCHES,
    ],
    "bhd": [
        "bhd star",
        "bhd cineplex",
        "bhd star cineplex",
        "#bhdstar",
        *BHD_BRANCHES,
    ],
    "cinestar": [
        "cinestar",
        "cine star",
        "rạp cinestar",
        "rap cinestar",
        "#cinestar",
        *CINESTAR_BRANCHES,
    ],
}

# Broader crawl discovery patterns (may be looser; tagging still uses competitive + excludes)
BRAND_PATTERNS: list[tuple[str, list[str]]] = [
    ("glx", COMPETITIVE_PATTERNS["glx"] + ["vé galaxy", "ve galaxy", "đặt vé galaxy", "dat ve galaxy"]),
    ("cgv", COMPETITIVE_PATTERNS["cgv"] + ["vé cgv", "ve cgv", "đặt vé cgv"]),
    ("lotte", COMPETITIVE_PATTERNS["lotte"] + ["vé lotte cinema", "đặt vé lotte cinema"]),
    ("beta", COMPETITIVE_PATTERNS["beta"] + ["vé beta cinemas", "vé beta cineplex"]),
    ("bhd", COMPETITIVE_PATTERNS["bhd"] + ["vé bhd star"]),
    ("cinestar", COMPETITIVE_PATTERNS["cinestar"] + ["vé cinestar"]),
]

# ---------------------------------------------------------------------------
# Hard excludes (if matched → do not tag / do not import as organic buzz)
# ---------------------------------------------------------------------------

# Brand-scoped hard excludes (match brand + exclude → drop that brand only)
GLX_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(samsung|galaxy\s*(note|a\d*|s\d*|ultra|tab|watch|buds?|z(?:\s*(?:fold|flip))?))\b",
        re.I,
    ),
    re.compile(r"\b(jaipur|india|ấn\s*độ|an\s*do|naroda|avenue)\b", re.I),
    re.compile(r"\b(rapgalaxy|rvpgalaxy|rxpgalaxy)\b", re.I),
    re.compile(r"#rapgalaxy\b", re.I),
    re.compile(r"galaxycinemaegypt|galaxy\s*cinema\s*egypt", re.I),
]

# Ticket-scalper / recruiting / GDTG spam — drop all brand tagging.
# Soft phrases alone are common in legit cinema promos; they only suppress tagging
# when no explicit competitive brand signal is present.
SPAM_HARD_PHRASES: list[str] = [
    "tuyển dụng",
    "part-time",
    "parttime",
    "part time",
    "giao dịch trung gian",
    "gdtg",
    "hú mình (chủ nhóm)",
    "admin (chủ nhóm)",
    "book vé rạp galaxy",
    "rẻ hơn giá rạp",
    "giảm giá đến 30%",
    "pass vé",
    "pass gấp",
    "cần pass",
    "nhượng lại vé",
    "số lượng lớn",
    "tất cả các phim",
    "tất cả các rạp",
    "áp dụng cho tất cả",
]

# Generic cinema wording that appears in both spam and legitimate schedules/promos.
SPAM_SOFT_PHRASES: list[str] = [
    "các suất chiếu",
]

# Backward-compatible union (tests / callers that iterate the flat list).
SPAM_EXCLUDE_PHRASES: list[str] = SPAM_HARD_PHRASES + SPAM_SOFT_PHRASES

# Explicit competitive brand signals — soft spam must not wipe these alone.
EXPLICIT_CINEMA_BRAND_RE = re.compile(
    r"(?:"
    r"galaxy\s*cinema|galaxy\s*cine|r[aạ]p\s*galaxy|#galaxycinema|#galaxymovie|galaxycine\.vn|"
    r"\bcgv\b|#cgv|cgv\s*cinemas?|r[aạ]p\s*cgv|"
    r"lotte\s*cinema|#lottecinema|"
    r"beta\s*cinemas|beta\s*cineplex|r[aạ]p\s*beta|#betacinemas|"
    r"bhd\s*star|bhd\s*cineplex|#bhdstar|"
    r"\bcinestar\b|#cinestar|r[aạ]p\s*cinestar"
    r")",
    re.I,
)

# Official Galaxy Cinema VN site — publisher/domain proof for GLX (not crawl keywords).
GLX_OWNED_PUBLISHER_RE = re.compile(r"galaxycine\.vn\b", re.I)

LOTTE_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"lotte\s*(mart|hotel|duty\s*free|department\s*store|shopping|supermarket|tower)\b",
        re.I,
    ),
]

BETA_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bbeta\s*(version|test|tester|release|male)\b", re.I),
    re.compile(r"phiên\s*bản\s*beta|phien\s*ban\s*beta", re.I),
    re.compile(
        r"\bbeta\b.{0,40}\b(phone|app|software|game|android|ios|apk|update|build)\b|"
        r"\b(phone|app|software|game|android|ios|apk|update|build)\b.{0,40}\bbeta\b",
        re.I,
    ),
]

# Backward-compatible flat list (union) for callers that only need a bool
EXCLUDE_PATTERNS: list[re.Pattern[str]] = (
    GLX_EXCLUDE_PATTERNS + LOTTE_EXCLUDE_PATTERNS + BETA_EXCLUDE_PATTERNS
)

MEDIA_LISTING_ACCOUNTS: set[str] = {
    "encorefilmsvn",
    "universalpicturesvn",
    "phimsapchieu",
    "lichchieuphim",
    "movielichchieu",
    "cgvcinemasvietnam",
    "galaxycinema",
    "galaxycine",
    "galaxy_cinema",
    "galaxycinemavn",
}

OWNED_ACCOUNT_KEYS: set[str] = {
    "galaxycinema",
    "galaxy_cinema",
    "galaxycinemavn",
    "galaxycine",
    "cgvcinemasvietnam",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def strip_accents(text: str) -> str:
    nk = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nk if unicodedata.category(ch) != "Mn")


def hits_exclude(text: str, permalink: str = "", author: str = "") -> bool:
    """True if any brand-scoped hard exclude fires (legacy helper)."""
    blob = normalize(" ".join([text or "", permalink or "", author or ""]))
    return any(p.search(blob) for p in EXCLUDE_PATTERNS)


def hits_spam_exclude(text: str, permalink: str = "", author: str = "") -> bool:
    """True if text looks like ticket-resale / recruiting / GDTG spam.

    Soft phrases (e.g. ``các suất chiếu``) alone do not suppress tagging when an
    explicit competitive brand signal is present — those phrases appear in
    legitimate cinema schedules/promos.
    """
    blob = normalize(" ".join([text or "", permalink or "", author or ""]))
    if not blob:
        return False
    if any(phrase in blob for phrase in SPAM_HARD_PHRASES):
        return True
    if any(phrase in blob for phrase in SPAM_SOFT_PHRASES):
        return not bool(EXPLICIT_CINEMA_BRAND_RE.search(blob))
    return False


def _has_glx_ok(blob: str) -> bool:
    """Galaxy Cinema competitive match, including owned publisher galaxycine.vn."""
    if _glx_excluded(blob):
        return False
    if any(p in blob for p in COMPETITIVE_PATTERNS["glx"]):
        return True
    # Official VN site as publisher/source (body may omit "Galaxy Cinema").
    return bool(GLX_OWNED_PUBLISHER_RE.search(blob))


def _blob_has_any(blob: str, patterns: list[str]) -> bool:
    return any(p in blob for p in patterns)


def _glx_excluded(blob: str) -> bool:
    return any(p.search(blob) for p in GLX_EXCLUDE_PATTERNS)


def _has_lotte_cinema(blob: str) -> bool:
    if "#lottecinema" in blob:
        return True
    if re.search(r"lotte\s*(cinema|cinemas|cine)\b", blob):
        return True
    if _blob_has_any(blob, LOTTE_BRANCHES):
        return True
    return False


def _has_lotte_non_cinema(blob: str) -> bool:
    if "lotte" not in blob:
        return False
    if _has_lotte_cinema(blob):
        # Still drop lotte if hard non-cinema product sits next to "lotte …"
        # but keep when cinema keyword is present (e.g. "lotte cinema gần lotte mart").
        return False
    if any(p.search(blob) for p in LOTTE_EXCLUDE_PATTERNS):
        return True
    return True  # bare "lotte" without cinema → reject


def _has_beta_exclude(blob: str) -> bool:
    return any(p.search(blob) for p in BETA_EXCLUDE_PATTERNS)


def _has_beta_ok(blob: str) -> bool:
    if _has_beta_exclude(blob):
        return False
    if re.search(r"beta\s*(cinemas|cineplex)|r[aạ]p\s*beta|#betacinemas", blob):
        return True
    if _blob_has_any(blob, BETA_BRANCHES):
        return True
    if re.search(r"\bbeta\b", blob) and CINEMA_CONTEXT_RE.search(blob):
        return True
    return False


def _has_bhd_ok(blob: str) -> bool:
    if re.search(r"bhd\s*star|bhd\s*cineplex|#bhdstar", blob):
        return True
    if _blob_has_any(blob, BHD_BRANCHES):
        return True
    # Bare "bhd" only with cinema context
    if re.search(r"\bbhd\b", blob) and CINEMA_CONTEXT_RE.search(blob):
        return True
    return False


def _build_brand_blob(
    text: str,
    permalink: str = "",
    author: str = "",
) -> str:
    """Brand tagging uses content only — crawl keyword matches are not brand proof."""
    return normalize(" ".join([text or "", permalink or "", author or ""]))


def _has_foreign_cinema_market(blob: str) -> bool:
    return bool(FOREIGN_CINEMA_MARKET_RE.search(blob) or FOREIGN_PUBLISHER_RE.search(blob))


def _has_vn_cinema_market(blob: str) -> bool:
    return bool(VN_CINEMA_MARKET_RE.search(blob))


def _foreign_blocks_competitors(blob: str) -> bool:
    """Foreign cinema market blocks competitor tags unless VN market is explicit."""
    if not _has_foreign_cinema_market(blob):
        return False
    return not _has_vn_cinema_market(blob)


def _has_cgv_ok(blob: str) -> bool:
    if not re.search(r"\bcgv\b|#cgv", blob):
        return False
    if _foreign_blocks_competitors(blob):
        return False
    if _blob_has_any(blob, CGV_BRANCHES):
        return True
    if re.search(r"cgv\s*(cinemas?|vietnam|việt\s*nam|viet\s*nam)|r[aạ]p\s*cgv|#cgvvietnam", blob):
        return True
    if re.search(r"#cgv\b", blob):
        return True
    return bool(re.search(r"\bcgv\b", blob))


def detect_competitive_brands(
    text: str,
    matches: list[str] | None = None,
    *,
    permalink: str = "",
    author: str = "",
    platform: str | None = None,
) -> list[str]:
    """Return brand slugs that fairly match content (SoV / import tagging).

    ``matches`` is ignored for tagging — keyword crawl hits are not valid brand mentions.
    """
    _ = matches  # crawl discovery only; kept for call-site compatibility
    if hits_spam_exclude(text, permalink, author):
        return []
    blob = _build_brand_blob(text, permalink, author)
    if not blob:
        return []

    found: list[str] = []
    for slug, patterns in COMPETITIVE_PATTERNS.items():
        if slug == "glx":
            if not _has_glx_ok(blob):
                continue
            found.append(slug)
            continue

        if slug == "lotte":
            if _has_lotte_non_cinema(blob):
                continue
            if not _has_lotte_cinema(blob):
                continue
            if _foreign_blocks_competitors(blob):
                continue
            found.append(slug)
            continue

        if slug == "beta":
            if not _has_beta_ok(blob):
                continue
            if _foreign_blocks_competitors(blob):
                continue
            found.append(slug)
            continue

        if slug == "bhd":
            if not _has_bhd_ok(blob):
                continue
            if _foreign_blocks_competitors(blob):
                continue
            found.append(slug)
            continue

        if slug == "cgv":
            if not _has_cgv_ok(blob):
                continue
            found.append(slug)
            continue

        if slug == "cinestar":
            if _foreign_blocks_competitors(blob):
                continue
            if not (
                _blob_has_any(blob, CINESTAR_BRANCHES)
                or re.search(r"r[aạ]p\s*cinestar|#cinestar", blob)
                or re.search(r"\bcinestar\b", blob)
            ):
                continue
            found.append(slug)
            continue

        if any(p in blob for p in patterns):
            if _foreign_blocks_competitors(blob):
                continue
            found.append(slug)

    out: list[str] = []
    for s in found:
        if s not in out:
            out.append(s)
    return out


def detect_brands(
    text: str,
    matches: list[str] | None = None,
    *,
    permalink: str = "",
    author: str = "",
    platform: str | None = None,
) -> list[str]:
    """Legacy broader detect — prefer competitive for DB tagging."""
    brands = detect_competitive_brands(
        text,
        matches,
        permalink=permalink,
        author=author,
        platform=platform,
    )
    return brands or ["others"]


# SQL fragment for Postgres ILIKE competitive keep filters (dashboard / purge).
# Approximates Python rules; import tagging remains the strict source of truth.
COMPETITIVE_KEYWORD_SQL = """
  (
    (b.brand_slug = 'glx' AND (
      m.content_text ILIKE '%galaxy cinema%'
      OR m.content_text ILIKE '%galaxy cine%'
      OR m.content_text ILIKE '%rạp galaxy%'
      OR m.content_text ILIKE '%rap galaxy%'
      OR m.content_text ILIKE '%#galaxycinema%'
      OR m.content_text ILIKE '%#galaxymovie%'
      OR m.content_text ILIKE '%galaxy nguyễn du%'
      OR m.content_text ILIKE '%galaxy nguyen du%'
      OR m.content_text ILIKE '%galaxy tân bình%'
      OR m.content_text ILIKE '%galaxy tan binh%'
      OR m.content_text ILIKE '%galaxy kinh dương%'
      OR m.content_text ILIKE '%galaxy kinh duong%'
      OR m.content_text ILIKE '%galaxy quang trung%'
      OR m.content_text ILIKE '%galaxy sư vạn hạnh%'
      OR m.content_text ILIKE '%galaxy su van hanh%'
      OR m.content_text ILIKE '%galaxy mipec%'
      OR m.content_text ILIKE '%galaxy hn centre%'
      OR m.content_text ILIKE '%galaxy hanoi centre%'
      OR m.content_text ILIKE '%galaxy hà nội%'
      OR m.content_text ILIKE '%galaxy ha noi%'
      OR m.content_text ILIKE '%galaxy đà nẵng%'
      OR m.content_text ILIKE '%galaxy da nang%'
      OR m.content_text ILIKE '%galaxy bmt%'
      OR m.content_text ILIKE '%galaxy buôn mê%'
      OR m.content_text ILIKE '%galaxy buon me%'
      OR m.content_text ILIKE '%galaxy nha trang%'
      OR m.content_text ILIKE '%galaxy cần thơ%'
      OR m.content_text ILIKE '%galaxy can tho%'
      OR m.content_text ILIKE '%galaxy long xuyên%'
      OR m.content_text ILIKE '%galaxy long xuyen%'
    )
    AND m.content_text NOT ILIKE '%rapgalaxy%'
    AND m.content_text NOT ILIKE '%rvpgalaxy%'
    AND m.content_text NOT ILIKE '%rxpgalaxy%'
    AND m.content_text NOT ILIKE '%jaipur%'
    AND m.content_text NOT ILIKE '%india%'
    AND m.content_text NOT ILIKE '%ấn độ%'
    AND m.content_text NOT ILIKE '%naroda%'
    AND m.content_text NOT ILIKE '%avenue%'
    AND m.content_text NOT ILIKE '%samsung%'
    AND m.content_text NOT ILIKE '%galaxy note%'
    AND m.content_text NOT ILIKE '%galaxy tab%'
    AND m.content_text NOT ILIKE '%galaxy watch%'
    AND m.content_text NOT ILIKE '%galaxy bud%'
    AND m.content_text NOT ILIKE '%galaxy z fold%'
    AND m.content_text NOT ILIKE '%galaxy z flip%'
    )
    OR (b.brand_slug = 'cgv' AND (
      m.content_text ILIKE '%cgv%'
      OR m.content_text ILIKE '%#cgv%'
    ))
    OR (b.brand_slug = 'lotte' AND (
      m.content_text ILIKE '%lotte cinema%'
      OR m.content_text ILIKE '%lotte cinemas%'
      OR m.content_text ILIKE '%lotte cine%'
      OR m.content_text ILIKE '%#lottecinema%'
    )
    AND m.content_text NOT ILIKE '%lotte mart%'
    AND m.content_text NOT ILIKE '%lotte hotel%'
    AND m.content_text NOT ILIKE '%lotte duty free%'
    AND m.content_text NOT ILIKE '%lotte department%'
    AND m.content_text NOT ILIKE '%lotte tower%'
    )
    OR (b.brand_slug = 'beta' AND (
      m.content_text ILIKE '%beta cinemas%'
      OR m.content_text ILIKE '%beta cineplex%'
      OR m.content_text ILIKE '%rạp beta%'
      OR m.content_text ILIKE '%rap beta%'
      OR m.content_text ILIKE '%#betacinemas%'
      OR m.content_text ILIKE '%beta xuân th%'
      OR m.content_text ILIKE '%beta xuan thuy%'
      OR m.content_text ILIKE '%beta tây sơn%'
      OR m.content_text ILIKE '%beta tay son%'
      OR m.content_text ILIKE '%beta aeon%'
      OR m.content_text ILIKE '%beta thanh xu%'
      OR m.content_text ILIKE '%beta gia lai%'
      OR m.content_text ILIKE '%beta biên hòa%'
      OR m.content_text ILIKE '%beta bien hoa%'
      OR (
        m.content_text ~* '\\ybeta\\y'
        AND m.content_text ~* '(r[aạ]p|xem\\s*phim|v[eé]|su[aấ]t\\s*chi[eế]u|ph[oò]ng\\s*chi[eế]u|l[iị]ch\\s*chi[eế]u|[đd][aặ]t\\s*v[eé]|imax|4dx|screenx|cinema|cineplex)'
      )
    )
    AND m.content_text NOT ILIKE '%beta version%'
    AND m.content_text NOT ILIKE '%beta test%'
    AND m.content_text NOT ILIKE '%beta male%'
    AND m.content_text NOT ILIKE '%phiên bản beta%'
    AND m.content_text NOT ILIKE '%phien ban beta%'
    )
    OR (b.brand_slug = 'bhd' AND (
      m.content_text ILIKE '%bhd star%'
      OR m.content_text ILIKE '%bhd cineplex%'
      OR m.content_text ILIKE '%#bhdstar%'
      OR (
        m.content_text ~* '\\ybhd\\y'
        AND m.content_text ~* '(r[aạ]p|xem\\s*phim|v[eé]|su[aấ]t\\s*chi[eế]u|ph[oò]ng\\s*chi[eế]u|l[iị]ch\\s*chi[eế]u|[đd][aặ]t\\s*v[eé]|imax|4dx|screenx|cinema|cineplex)'
      )
    ))
    OR (b.brand_slug = 'cinestar' AND (
      m.content_text ILIKE '%cinestar%'
      OR m.content_text ILIKE '%cine star%'
      OR m.content_text ILIKE '%rạp cinestar%'
      OR m.content_text ILIKE '%#cinestar%'
    ))
  )
"""


























































