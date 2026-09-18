#!/usr/bin/env python3
"""Unit checks for gift lead clusters + demand gate.

  PYTHONPATH=src python3 tests/test_gift_leads.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_listening.gift_leads import (  # noqa: E402
    GIFT_LEAD_KEYWORDS,
    match_gift_intent,
)
from social_listening.keyword_config import is_term_enabled  # noqa: E402


def test_corporate_lead():
    m = match_gift_intent(
        "Công ty em cần đặt quà cuối năm cho nhân viên, xin báo giá ạ. LH 0901234567"
    )
    assert m is not None
    assert m.intent_tag in {"corporate_gift", "year_end_gift"}
    assert m.entity_type == "business"
    assert m.contact_phone is not None
    assert m.signal_score >= 5


def test_bulk_lead():
    m = match_gift_intent("Cần đặt quà số lượng lớn cho khách hàng")
    assert m is not None
    assert m.intent_tag in {"bulk_order", "corporate_gift", "buy_gift"}


def test_product_with_demand():
    m = match_gift_intent("Tìm hộp quà doanh nghiệp, báo giá giúp mình")
    assert m is not None


def test_reject_vanity_tet_post():
    assert match_gift_intent("Quà Tết năm nay đẹp quá ❤️") is None


def test_reject_product_without_demand():
    assert match_gift_intent("Giỏ quà này xinh quá mọi người ơi") is None


def test_reject_cinema_noise():
    assert (
        match_gift_intent(
            "Quà tặng movie 29 conan",
            author_name="Galaxy Cinema Việt Nam",
        )
        is None
    )
    assert (
        match_gift_intent(
            "⚡ VÉ FAN SCREENING tại CGV — có quà tặng",
            author_name="cgv royal city",
        )
        is None
    )


def test_crawl_keywords_cover_clusters():
    clusters = {str(item.get("cluster")) for item in GIFT_LEAD_KEYWORDS}
    assert "gift_intent" in clusters
    assert "bulk_order" in clusters
    assert "product" in clusters
    assert "priority_phrase" in clusters
    values = {str(item["value"]).lower() for item in GIFT_LEAD_KEYWORDS}
    assert "công ty" not in values
    assert "doanh nghiệp" not in values


def test_strict_process():
    assert is_term_enabled("Galaxy Cinema", "gift_leads") is False
    sample = next(item for item in GIFT_LEAD_KEYWORDS if item.get("cluster") == "gift_intent")
    assert is_term_enabled(sample, "gift_leads")
    assert is_term_enabled(sample, "") is False


if __name__ == "__main__":
    test_corporate_lead()
    test_bulk_lead()
    test_product_with_demand()
    test_reject_vanity_tet_post()
    test_reject_product_without_demand()
    test_reject_cinema_noise()
    test_crawl_keywords_cover_clusters()
    test_strict_process()
    print(f"ok keywords={len(GIFT_LEAD_KEYWORDS)}")
