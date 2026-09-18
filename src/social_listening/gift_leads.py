"""Gift lead gen — keyword clusters + lead classification.

Crawl = bắt rộng theo cluster GIFT_LEAD_GEN.
Classify = chỉ giữ bài có Gift context + Demand/Buy intent
(loại noise kiểu "Quà Tết năm nay đẹp quá ❤️").

Process name: gift_leads
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

PROCESS_NAME = "gift_leads"

# -----------------------------------------------------------------------------
# Clusters (source of truth for crawl seed)
# -----------------------------------------------------------------------------

CLUSTER_GIFT_INTENT: list[str] = [
    "tặng quà",
    "mua quà tặng",
    "mua quà",
    "quà tặng",
    "quà doanh nghiệp",
    "quà công ty",
    "quà khách hàng",
    "quà đối tác",
    "quà nhân viên",
    "quà cuối năm",
    "quà Tết",
    "quà Tet",
    "quà Tết doanh nghiệp",
    "quà tri ân",
    "quà biếu",
    "quà biếu khách hàng",
    "quà biếu đối tác",
    "quà sự kiện",
]

CLUSTER_BULK_ORDER: list[str] = [
    "mua số lượng lớn",
    "đặt số lượng lớn",
    "đặt quà số lượng lớn",
    "cần số lượng lớn",
    "đặt nhiều",
    "mua nhiều",
    "đặt hàng số lượng lớn",
    "đơn hàng số lượng lớn",
    "quà số lượng lớn",
    "tặng nhiều người",
    "tặng khách hàng",
    "tặng đối tác",
    "tặng nhân viên",
]

CLUSTER_PRODUCT: list[str] = [
    "hộp quà",
    "hộp quà tặng",
    "hộp quà doanh nghiệp",
    "hộp quà Tết",
    "set quà",
    "set quà tặng",
    "combo quà",
    "giỏ quà",
    "giỏ quà Tết",
    "giỏ quà doanh nghiệp",
]

# Business context — dùng classify/boost, KHÔNG crawl đơn lẻ (quá rộng).
CLUSTER_BUSINESS: list[str] = [
    "doanh nghiệp",
    "công ty",
    "khách hàng",
    "đối tác",
    "nhân viên",
    "phòng hcns",
    "hr ",
]

# Cụm ưu tiên crawl (ý định mua/đặt rõ).
PRIORITY_PHRASES: list[str] = [
    "cần quà Tết cho nhân viên",
    "công ty cần đặt quà cuối năm",
    "tìm hộp quà doanh nghiệp",
    "đặt quà số lượng lớn",
    "cần mua quà tặng khách hàng",
    "cần đặt quà tặng",
    "xin báo giá quà",
    "báo giá hộp quà",
    "báo giá giỏ quà",
    "đặt quà doanh nghiệp",
    "tìm nơi đặt quà",
]

# ASCII / không dấu variants hay gặp trên MXH.
ASCII_ALIASES: dict[str, list[str]] = {
    "quà Tết": ["qua tet", "quà tet"],
    "quà cuối năm": ["qua cuoi nam"],
    "quà tặng": ["qua tang"],
    "quà doanh nghiệp": ["qua doanh nghiep"],
    "quà công ty": ["qua cong ty"],
    "quà khách hàng": ["qua khach hang"],
    "quà đối tác": ["qua doi tac"],
    "quà nhân viên": ["qua nhan vien"],
    "quà biếu": ["qua bieu"],
    "hộp quà": ["hop qua"],
    "giỏ quà": ["gio qua"],
    "set quà": ["set qua"],
    "số lượng lớn": ["so luong lon"],
    "doanh nghiệp": ["doanh nghiep"],
    "công ty": ["cong ty"],
    "đối tác": ["doi tac"],
    "nhân viên": ["nhan vien"],
    "khách hàng": ["khach hang"],
}


def _with_aliases(terms: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        candidates = [term, *ASCII_ALIASES.get(term, [])]
        for item in candidates:
            key = item.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _kw(value: str, *, cluster: str, priority: int) -> dict:
    return {
        "value": value,
        "processes": [PROCESS_NAME],
        "match": "contains",
        "cluster": cluster,
        "priority": priority,
    }


def build_crawl_keywords() -> list[dict]:
    """Broad crawl terms for listening_queries (process gift_leads)."""
    items: list[dict] = []
    for term in _with_aliases(PRIORITY_PHRASES):
        items.append(_kw(term, cluster="priority_phrase", priority=1))
    for term in _with_aliases(CLUSTER_GIFT_INTENT):
        items.append(_kw(term, cluster="gift_intent", priority=2))
    for term in _with_aliases(CLUSTER_BULK_ORDER):
        items.append(_kw(term, cluster="bulk_order", priority=2))
    for term in _with_aliases(CLUSTER_PRODUCT):
        items.append(_kw(term, cluster="product", priority=3))

    # Dedupe by lower value, keep highest priority (lowest number).
    best: dict[str, dict] = {}
    for item in items:
        key = str(item["value"]).lower()
        prev = best.get(key)
        if prev is None or int(item["priority"]) < int(prev["priority"]):
            best[key] = item
    return sorted(best.values(), key=lambda x: (int(x["priority"]), str(x["value"]).lower()))


GIFT_LEAD_KEYWORDS: list[dict] = build_crawl_keywords()

# -----------------------------------------------------------------------------
# Classification: gift context + demand intent (not vanity mention)
# -----------------------------------------------------------------------------

GIFT_CONTEXT_TERMS: list[str] = _with_aliases(
    [
        *CLUSTER_GIFT_INTENT,
        *CLUSTER_PRODUCT,
        "quà",
        "qua tang",
        "qua tet",
        "qua cuoi nam",
    ]
)

DEMAND_TERMS: list[str] = _with_aliases(
    [
        *CLUSTER_BULK_ORDER,
        "cần đặt",
        "can dat",
        "cần mua",
        "can mua",
        "xin báo giá",
        "xin bao gia",
        "báo giá",
        "bao gia",
        "đặt quà",
        "dat qua",
        "mua quà",
        "mua qua",
        "đặt sỉ",
        "dat si",
        "mua sỉ",
        "mua si",
        "tìm nơi đặt",
        "tim noi dat",
        "tìm hộp quà",
        "tim hop qua",
        "đặt hàng",
        "dat hang",
        "order",
        "inbox đặt",
        "ib đặt",
    ]
)

BUSINESS_TERMS: list[str] = _with_aliases(CLUSTER_BUSINESS)

YEAR_END_TERMS: list[str] = _with_aliases(
    [
        "quà cuối năm",
        "quà Tết",
        "hộp quà Tết",
        "giỏ quà Tết",
        "set quà Tết",
        "quà Tết doanh nghiệp",
    ]
)

# Cinema / brand SL noise — không phải gift buyer lead.
CINEMA_NOISE_TERMS: list[str] = _with_aliases(
    [
        "galaxy cinema",
        "galaxycine",
        "cgv",
        "lotte cinema",
        "bhd star",
        "bhd cineplex",
        "cinestar",
        "beta cineplex",
        "đặt vé",
        "dat ve",
        "giá vé",
        "gia ve",
        "suất chiếu",
        "suat chieu",
        "fan screening",
        "movie merch",
        "quà tặng movie",
        "rap chiếu",
        "rạp chiếu",
    ]
)

# Supplier / seller ads (bán quà) — chưa phải buyer lead.
SUPPLIER_NOISE_TERMS: list[str] = _with_aliases(
    [
        "xưởng",
        "xuong",
        "cung cấp quà",
        "cung cap qua",
        "sỉ lẻ quà",
        "si le qua",
        "nhận order quà",
        "nhan order qua",
        "in ấn quà",
        "in an qua",
        "bao bì & in",
        "chuyên cung cấp",
        "chuyen cung cap",
    ]
)

MIN_LEAD_SCORE = 5.0

# Bài chỉ khen/đẹp/xem — không phải lead dù có "quà Tết".
VANITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(đẹp quá|dep qua|xinh quá|yêu thích|yeu thich|năm nay đẹp|nam nay dep)"),
    re.compile(r"(lookbook|review món|unbox|mở hộp|mo hop).{0,20}(đẹp|dep|xinh)"),
]

BUY_SIGNAL_PATTERNS: list[tuple[str, float]] = [
    (r"\bcần\s+(đặt|mua|báo\s*giá|quà)", 3.0),
    (r"\bxin\s+báo\s*giá", 3.0),
    (r"\bbáo\s*giá", 2.0),
    (r"\b(đặt|dat|mua)\s+(sỉ|si|số lượng|so luong|nhiều|nhieu)", 3.0),
    (r"\bsố lượng lớn|so luong lon", 3.0),
    (r"\btặng\s+(nhân viên|nhan vien|đối tác|doi tac|khách hàng|khach hang)", 2.5),
    (r"\bliên\s*hệ.{0,24}(đặt|mua)", 1.5),
    (r"\b(inbox|ib)\s+(đặt|mua|giá)", 2.0),
    (r"\b\d+\s*(hộp|hop|giỏ|gio|set|suất|suat)\b", 2.0),
]

PHONE_RE = re.compile(
    r"(?:\+?84|0)(?:\s|\.|-)?(?:3|5|7|8|9)\d(?:[\s.\-]?\d){7,8}"
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
ZALO_RE = re.compile(r"zalo\s*[:\-]?\s*((?:\+?84|0)\d[\d\s.\-]{7,12})", re.I)


@dataclass
class GiftLeadMatch:
    intent_tag: str
    signal_score: float
    matched_keywords: list[str]
    entity_type: str
    contact_phone: str | None
    contact_email: str | None
    contact_zalo: str | None
    clusters_hit: list[str]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def extract_contacts(text: str) -> tuple[str | None, str | None, str | None]:
    blob = text or ""
    phone = None
    m = PHONE_RE.search(blob)
    if m:
        phone = re.sub(r"[\s.\-]", "", m.group(0))
    email = None
    em = EMAIL_RE.search(blob)
    if em:
        email = em.group(0)
    zalo = None
    zm = ZALO_RE.search(blob)
    if zm:
        zalo = re.sub(r"[\s.\-]", "", zm.group(1))
    return phone, email, zalo


def detect_entity_type(text: str) -> str:
    blob = normalize(text)
    if any(h in blob for h in BUSINESS_TERMS):
        return "business"
    return "unknown"


def _hits(blob: str, terms: Iterable[str]) -> list[str]:
    found: list[str] = []
    for term in terms:
        needle = term.lower().strip()
        if needle and needle in blob:
            found.append(term)
    return found


def looks_like_vanity_gift_post(blob: str) -> bool:
    """True when gift is mentioned as aesthetic/praise without buy intent."""
    if any(re.search(p, blob) for p in VANITY_PATTERNS):
        demand = _hits(blob, DEMAND_TERMS)
        if not demand and not any(re.search(p, blob) for p, _ in BUY_SIGNAL_PATTERNS):
            return True
    return False


def resolve_intent_tag(blob: str, gift_hits: list[str], demand_hits: list[str]) -> str:
    business = bool(_hits(blob, BUSINESS_TERMS)) or any(
        t for t in gift_hits if any(x in t.lower() for x in ("doanh nghiệp", "doanh nghiep", "công ty", "cong ty", "đối tác", "doi tac", "nhân viên", "nhan vien", "khách hàng", "khach hang"))
    )
    year_end = bool(_hits(blob, YEAR_END_TERMS))
    bulk = bool(_hits(blob, _with_aliases(CLUSTER_BULK_ORDER))) or any(
        "số lượng" in t.lower() or "so luong" in t.lower() or "nhiều" in t.lower() or "nhieu" in t.lower()
        for t in demand_hits
    )

    if business and (gift_hits or demand_hits):
        return "corporate_gift"
    if year_end:
        return "year_end_gift"
    if bulk:
        return "bulk_order"
    return "buy_gift"


def looks_like_cinema_noise(blob: str, author: str = "") -> bool:
    hay = f"{blob} {normalize(author)}"
    return bool(_hits(hay, CINEMA_NOISE_TERMS))


def looks_like_supplier_ad(blob: str) -> bool:
    return bool(_hits(blob, SUPPLIER_NOISE_TERMS))


def match_gift_intent(text: str, *, author_name: str = "") -> GiftLeadMatch | None:
    """Lead chỉ khi có gift context AND demand/buy signal (không cinema/supplier noise)."""
    blob = normalize(text)
    if not blob:
        return None

    if looks_like_cinema_noise(blob, author_name):
        return None

    gift_context = _hits(blob, _with_aliases([*CLUSTER_GIFT_INTENT, *CLUSTER_PRODUCT]))
    # Phrases like "đặt quà" / "mua quà" also count as gift context.
    if not gift_context:
        soft_gift = _hits(
            blob,
            _with_aliases(
                [
                    "đặt quà",
                    "mua quà",
                    "cần quà",
                    "quà số lượng",
                    "qua so luong",
                    "tặng quà",
                    "quà tặng",
                    "hộp quà",
                    "giỏ quà",
                    "set quà",
                    "combo quà",
                ]
            ),
        )
        gift_context = soft_gift

    if not gift_context:
        return None

    demand_hits = _hits(blob, DEMAND_TERMS)
    pattern_boost = 0.0
    for pattern, boost in BUY_SIGNAL_PATTERNS:
        if re.search(pattern, blob):
            pattern_boost += boost
            demand_hits.append(f"re:{pattern}")

    if not demand_hits and pattern_boost <= 0:
        return None

    if looks_like_vanity_gift_post(blob) and pattern_boost < 2.0:
        return None

    if looks_like_supplier_ad(blob) and pattern_boost < 3.0 and not _hits(blob, BUSINESS_TERMS):
        # Seller catalog without buyer wording
        if not any(x in blob for x in ("cần đặt", "can dat", "xin báo giá", "xin bao gia", "cần mua", "can mua")):
            return None

    clusters_hit: list[str] = ["gift_intent_or_product"]
    if _hits(blob, _with_aliases(CLUSTER_BULK_ORDER)):
        clusters_hit.append("bulk_order")
    if _hits(blob, BUSINESS_TERMS):
        clusters_hit.append("business")

    intent = resolve_intent_tag(blob, gift_context, demand_hits)
    score = 2.0 * len(set(x.lower() for x in gift_context))
    score += 2.5 * min(3, len({d for d in demand_hits if not str(d).startswith("re:")}))
    score += pattern_boost
    if "business" in clusters_hit:
        score += 2.0
    if "bulk_order" in clusters_hit:
        score += 2.0

    phone, email, zalo = extract_contacts(text)
    if phone or email or zalo:
        score += 1.5

    if score < MIN_LEAD_SCORE:
        return None

    matched = sorted(
        set(gift_context + [d for d in demand_hits if not str(d).startswith("re:")])
    )
    return GiftLeadMatch(
        intent_tag=intent,
        signal_score=round(score, 2),
        matched_keywords=matched,
        entity_type=detect_entity_type(text),
        contact_phone=phone,
        contact_email=email,
        contact_zalo=zalo,
        clusters_hit=clusters_hit,
    )


def gift_keyword_values() -> list[str]:
    return [str(item["value"]) for item in GIFT_LEAD_KEYWORDS]


def keyword_table_rows() -> list[dict[str, str]]:
    """Rows for docs / seed review: keyword | cluster | priority | match | example."""
    examples = {
        "gift_intent": "Công ty cần quà tặng khách hàng cuối năm",
        "bulk_order": "Cần đặt quà số lượng lớn cho 200 nhân viên",
        "product": "Tìm hộp quà doanh nghiệp báo giá",
        "priority_phrase": "Cần mua quà tặng khách hàng, xin báo giá",
        "business": "(classify boost, không crawl đơn)",
    }
    rows: list[dict[str, str]] = []
    for item in GIFT_LEAD_KEYWORDS:
        cluster = str(item.get("cluster") or "")
        rows.append(
            {
                "keyword": str(item["value"]),
                "cluster": cluster,
                "priority": str(item.get("priority") or ""),
                "match": str(item.get("match") or "contains"),
                "example": examples.get(cluster, ""),
            }
        )
    return rows
