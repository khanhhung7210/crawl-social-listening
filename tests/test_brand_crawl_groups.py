"""Brand-phased Facebook crawl keyword grouping."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_listening.keyword_config import (
    classify_search_term_brand,
    collect_search_terms,
    group_search_terms_by_brand,
    load_keyword_payload,
)


def test_classify_search_term_brand():
    assert classify_search_term_brand("Galaxy Cinema") == "glx"
    assert classify_search_term_brand("rạp galaxy") == "glx"
    assert classify_search_term_brand("#galaxycinema") == "glx"
    assert classify_search_term_brand("rạp CGV") == "cgv"
    assert classify_search_term_brand("Lotte Cinema") == "lotte"
    assert classify_search_term_brand("Beta Cinemas") == "beta"
    assert classify_search_term_brand("BHD Star") == "bhd"
    assert classify_search_term_brand("Cinestar") == "cinestar"
    assert classify_search_term_brand("random promo") == "other"


def test_group_search_terms_by_brand_orders_glx_first():
    terms = [
        "rạp CGV",
        "Galaxy Cinema",
        "Lotte Cinema",
        "rạp galaxy",
        "vé CGV",
        "Beta Cinemas",
    ]
    groups = group_search_terms_by_brand(terms)
    assert [brand for brand, _ in groups] == ["glx", "cgv", "lotte", "beta"]
    assert groups[0][1] == ["Galaxy Cinema", "rạp galaxy"]
    assert groups[1][1] == ["rạp CGV", "vé CGV"]


def test_shared_keyword_file_groups_glx_before_competitors():
    payload = load_keyword_payload(ROOT / "data" / "shared" / "social_keywords.json")
    terms = collect_search_terms(payload)
    groups = group_search_terms_by_brand(terms)
    brands = [brand for brand, _ in groups]
    assert brands[0] == "glx"
    assert "cgv" in brands
    assert "lotte" in brands
    # Flattened order must put all glx before first cgv keyword
    flat = [term for brand, items in groups for term in items]
    first_cgv = next(i for i, t in enumerate(flat) if "cgv" in t.lower())
    assert all(classify_search_term_brand(t) == "glx" for t in flat[:first_cgv])
