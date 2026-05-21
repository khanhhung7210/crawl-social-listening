from __future__ import annotations

import re
from urllib.parse import urlparse, unquote

from social_listening.keyword_config import collect_config_values, collect_search_terms
from social_listening.text_utils import normalize_text


DEFAULT_FNB_POSITIVE_TERMS = [
    "mì bò",
    "mi bo",
    "đài loan",
    "dai loan",
    "sủi cảo",
    "sui cao",
    "bánh bao",
    "bao kẹp",
    "mi sui cao",
    "món ăn",
    "quán ăn",
    "ăn",
    "food",
    "restaurant",
    "delivery",
    "review",
    "đánh giá",
    "chi nhánh",
    "địa chỉ",
    "menu",
    "ship",
    "grabfood",
    "shopeefood",
    "google maps",
]

DEFAULT_FNB_NEGATIVE_TERMS = [
    "rezero",
    "re:zero",
    "anime",
    "episode",
    "season",
    "waifu",
    "cosplay",
    "edit anime",
    "anime edit",
    "outfit",
    "ootd",
    "váy",
    "vay",
    "makeup",
    "trainee",
    "idol",
    "shop quần áo",
    "shop thời trang",
]

DEFAULT_GENERIC_BRAND_TERMS = ["meili", "#meili", "美丽"]
COMMON_BRANCH_SLUG_TOKENS = {
    "meili",
    "mi",
    "bo",
    "dai",
    "loan",
    "banh",
    "bao",
    "kep",
    "sui",
    "cao",
    "mi-sui-cao",
    "mi-bo-dai-loan",
}


def evaluate_fnb_relevance(item: dict, keyword_payload: dict) -> dict:
    platform = str(item.get("platform") or "").strip().lower()
    text_parts = [
        str(item.get("post_text") or ""),
        str(item.get("page_name") or ""),
        str((item.get("stats") or {}).get("address") or ""),
        str(item.get("post_url") or ""),
    ]
    for comment in item.get("comments") or []:
        if isinstance(comment, dict):
            text_parts.append(str(comment.get("text") or ""))
    for menu_item in item.get("menu_items") or []:
        if isinstance(menu_item, dict):
            text_parts.append(str(menu_item.get("name") or ""))
            text_parts.append(str(menu_item.get("description") or ""))

    combined_text = normalize_text(" ".join(part for part in text_parts if part))

    positive_terms = unique_terms(DEFAULT_FNB_POSITIVE_TERMS + collect_config_values(keyword_payload, "fnb_positive_terms"))
    negative_terms = unique_terms(DEFAULT_FNB_NEGATIVE_TERMS + collect_config_values(keyword_payload, "fnb_negative_terms"))
    branch_terms = unique_terms(
        collect_config_values(keyword_payload, "branch_terms") + derive_branch_terms_from_urls(keyword_payload)
    )
    search_terms = unique_terms(collect_search_terms(keyword_payload, include_hashtags=True))

    generic_terms = {normalize_text(term) for term in DEFAULT_GENERIC_BRAND_TERMS}
    explicit_brand_terms = [
        normalize_text(term)
        for term in search_terms
        if normalize_text(term) and normalize_text(term) not in generic_terms and " " in normalize_text(term)
    ]

    positive_hits = find_hits(combined_text, positive_terms)
    negative_hits = find_hits(combined_text, negative_terms)
    branch_hits = find_hits(combined_text, branch_terms)
    explicit_brand_hits = [term for term in explicit_brand_terms if term and term in combined_text]
    generic_brand_hits = [term for term in generic_terms if term and term in combined_text]

    score = 0
    score += min(len(positive_hits), 4) * 2
    score += min(len(branch_hits), 2) * 3
    score += min(len(explicit_brand_hits), 2) * 4
    score += 3 if platform in {"google_maps", "shopeefood"} else 0
    score += 1 if generic_brand_hits else 0
    score -= min(len(negative_hits), 3) * 4

    # Social noise guard: bare Meili mention without food/store signals is not relevant.
    has_food_or_store_signal = bool(positive_hits or branch_hits or explicit_brand_hits or platform in {"google_maps", "shopeefood"})
    is_relevant = score >= 3 and has_food_or_store_signal and not (generic_brand_hits and not has_food_or_store_signal)

    return {
        "is_relevant_fnb": is_relevant,
        "relevance_score": score,
        "positive_hits": positive_hits,
        "negative_hits": negative_hits,
        "branch_hits": branch_hits,
        "explicit_brand_hits": explicit_brand_hits,
        "generic_brand_hits": generic_brand_hits,
    }


def derive_branch_terms_from_urls(keyword_payload: dict) -> list[str]:
    derived: list[str] = []
    for key in ("shopeefood_urls", "google_maps_urls"):
        for raw_url in collect_config_values(keyword_payload, key):
            parsed = urlparse(raw_url)
            path = unquote(parsed.path or "").strip("/")
            if not path:
                continue
            tail = path.split("/")[-1]
            cleaned = normalize_text(tail.replace("-", " "))
            if not cleaned:
                continue
            tokens = [token for token in cleaned.split() if token and token not in COMMON_BRANCH_SLUG_TOKENS]
            if len(tokens) >= 2:
                derived.append(" ".join(tokens))
    return unique_terms(derived)


def find_hits(text: str, terms: list[str]) -> list[str]:
    hits: list[str] = []
    for raw_term in terms:
        term = normalize_text(raw_term)
        if not term:
            continue
        if term in text and term not in hits:
            hits.append(term)
    return hits


def unique_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(value)
    return terms
