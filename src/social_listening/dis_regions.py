"""Distribution heatmap regions — shared rules for crawl + classify + dashboard."""

from __future__ import annotations

import re
import unicodedata

DIS_REGIONS: list[str] = [
    "HCM",
    "HN",
    "Đà Nẵng",
    "Cần Thơ",
    "Hải Phòng",
    "Bình Dương",
    "Khác",
]

# Moveek region_id → DIS heatmap bucket
MOVEEK_REGION_TO_DIS: dict[int, str] = {
    1: "HCM",
    9: "HN",
    7: "Đà Nẵng",
    6: "Cần Thơ",
    10: "Hải Phòng",
    4: "Bình Dương",
}

# News outlet heuristics (same spirit as overview REGION_CASE)
NEWS_AUTHOR_REGION: list[tuple[str, str]] = [
    ("HCM", r"tuổi\s*trẻ|tuoitre|thanhnien|kenh14|soha|znews"),
    ("HN", r"vnexpress|dantri|vov|vietnam\.vn|cafef|baotintuc"),
]

CONTENT_REGION_PATTERNS: list[tuple[str, str]] = [
    ("HCM", r"hồ\s*chí\s*minh|tp\.?\s*hcm|sài\s*gòn|saigon|tphcm|quận\s*\d+|quan\s*\d+"),
    ("HN", r"hà\s*nội|ha\s*noi|hanoi"),
    ("Đà Nẵng", r"đà\s*nẵng|da\s*nang|danang"),
    ("Cần Thơ", r"cần\s*thơ|can\s*tho"),
    ("Hải Phòng", r"hải\s*phòng|hai\s*phong"),
    ("Bình Dương", r"bình\s*dương|binh\s*duong"),
]

# Cinema / district phrases that map to DIS regions
CINEMA_REGION_HINTS: list[tuple[str, str]] = [
    ("HCM", r"galaxy\s*(nguyễn\s*du|kinh\s*dương\s*vương|tan\s*binh|tân\s*bình|quang\s*trung|trung\s*chánh|huỳnh\s*tấn\s*phát|paragon|nguyễn\s*văn\s*quá|phạm\s*văn\s*đồng)|cgv\s*(crescent|landmark|hùng\s*vương|vincom.*thủ\s*đức|aeon.*tân\s*phú)|bhd\s*(bitexco|phạm\s*hùng|vincom.*thảo\s*điền)"),
    ("HN", r"galaxy\s*(mipec|nguyễn\s*trãi|tràng\s*thi)|cgv\s*(vincom.*bà\s*triệu|royal|indochina|aeon.*long\s*biên)|lotte\s*cinema\s*(west\s*lake|thăng\s*long|hà\s*đông)"),
    ("Đà Nẵng", r"đà\s*nẵng|da\s*nang|vincom\s*đà\s*nẵng"),
    ("Cần Thơ", r"cần\s*thơ|can\s*tho|ninh\s*kiều"),
    ("Hải Phòng", r"hải\s*phòng|hai\s*phong"),
    ("Bình Dương", r"bình\s*dương|binh\s*duong|aeon.*bình\s*dương|thuận\s*an|thủ\s*dầu\s*một"),
]


def normalize(text: str) -> str:
    blob = unicodedata.normalize("NFD", (text or "").lower())
    blob = "".join(ch for ch in blob if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", blob).strip()


def empty_region_counts() -> dict[str, int]:
    return {r: 0 for r in DIS_REGIONS}


def classify_region(content_text: str, author: str = "") -> str:
    """Infer DIS region from mention text / author (mirrors dashboard REGION_CASE + cinema hints)."""
    blob = f"{content_text or ''}\n{author or ''}"
    for region, pat in CONTENT_REGION_PATTERNS:
        if re.search(pat, blob, re.I):
            return region
    for region, pat in CINEMA_REGION_HINTS:
        if re.search(pat, blob, re.I):
            return region
    author_blob = author or ""
    for region, pat in NEWS_AUTHOR_REGION:
        if re.search(pat, author_blob, re.I):
            return region
    return "Khác"


def moveek_ids_for_dis(region: str) -> list[int]:
    return [mid for mid, name in MOVEEK_REGION_TO_DIS.items() if name == region]
