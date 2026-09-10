"""Unit tests for competitive brand include/exclude rules."""

from __future__ import annotations

import unittest

from social_listening.brand_rules import detect_competitive_brands


class BrandRulesTest(unittest.TestCase):
    def assertBrands(
        self,
        text: str,
        expect: list[str],
        *,
        matches: list[str] | None = None,
        permalink: str = "",
    ) -> None:
        got = detect_competitive_brands(text, matches, permalink=permalink)
        self.assertEqual(got, expect, msg=f"text={text!r}")

    def test_glx_includes(self) -> None:
        self.assertBrands("Went to Galaxy Cinema yesterday", ["glx"])
        self.assertBrands("rạp galaxy ngon", ["glx"])
        self.assertBrands("galaxy cine Nguyễn Du", ["glx"])
        self.assertBrands("#galaxycinema", ["glx"])
        self.assertBrands("#galaxymovie", ["glx"])
        for branch in [
            "galaxy nguyễn du",
            "galaxy tân bình",
            "galaxy quang trung",
            "galaxy sư vạn hạnh",
            "galaxy mipec long biên",
            "galaxy đà nẵng",
            "galaxy nha trang",
            "galaxy cần thơ",
            "galaxy long xuyên",
            "galaxy bmt",
        ]:
            self.assertBrands(branch, ["glx"])

    def test_glx_excludes(self) -> None:
        self.assertBrands("Galaxy Cinema Jaipur", [])
        self.assertBrands("Galaxy Avenue mall", [])
        self.assertBrands("Samsung Galaxy Note", [])
        self.assertBrands("galaxy s24 ultra", [])
        self.assertBrands("galaxy buds pro", [])
        self.assertBrands("follow rapgalaxy", [])
        self.assertBrands("galaxy cinema ấn độ", [])
        self.assertBrands("galaxy cinema india", [])

    def test_cgv(self) -> None:
        self.assertBrands("cgv royal city", ["cgv"])
        self.assertBrands("#cgv", ["cgv"])
        self.assertBrands("cgv landmark 81", ["cgv"])

    def test_lotte(self) -> None:
        self.assertBrands("lotte cinema gò vấp", ["lotte"])
        self.assertBrands("lotte cinema west lake", ["lotte"])
        self.assertBrands("lotte cinema đống đa", ["lotte"])
        self.assertBrands("lotte mart sale", [])
        self.assertBrands("lotte hotel booking", [])
        self.assertBrands("lotte tower view", [])
        self.assertBrands("lotte", [])

    def test_bhd(self) -> None:
        self.assertBrands("bhd star bitexco", ["bhd"])
        self.assertBrands("bhd cineplex", ["bhd"])
        self.assertBrands("bhd only", [])
        self.assertBrands("rạp bhd chiều nay", ["bhd"])
        self.assertBrands("vé bhd suất chiếu", ["bhd"])

    def test_beta(self) -> None:
        self.assertBrands("beta cinemas", ["beta"])
        self.assertBrands("beta xuân thuỷ", ["beta"])
        self.assertBrands("beta thanh xuân", ["beta"])
        self.assertBrands("beta biên hòa", ["beta"])
        self.assertBrands("beta gia lai", ["beta"])
        self.assertBrands("rạp beta gần nhà", ["beta"])
        self.assertBrands("beta version release", [])
        self.assertBrands("phiên bản beta app", [])
        self.assertBrands("beta test game", [])
        self.assertBrands("chỉ nói beta thôi", [])

    def test_cinestar(self) -> None:
        self.assertBrands("cinestar park city", ["cinestar"])
        self.assertBrands("cinestar", ["cinestar"])
        self.assertBrands("cinestar quốc thanh", ["cinestar"])

    def test_multi_brand_scoped_exclude(self) -> None:
        # Lotte mart exclude must not wipe CGV in same text
        self.assertBrands("cgv và lotte mart", ["cgv"])

    def test_foreign_market_no_competitor_tags(self) -> None:
        self.assertBrands("CGV Korea khai trương rạp mới tại Seoul", [])
        self.assertBrands("Lotte Cinema mở rạp tại Hàn Quốc", [])
        self.assertBrands("Megabox Hongdae tổ chức sự kiện", [])
        self.assertBrands("CGV Philippines ra mắt phim mới", [])
        cineplay = (
            "'InuYasha' lần đầu ra rạp tại Hàn Quốc. CGV phát hành độc quyền. "
            "Megabox Hongdae tổ chức sự kiện. Lotte Cinema ra mắt."
        )
        self.assertBrands(
            cineplay,
            [],
            permalink="https://www.cineplay.co.kr/vi-vn/articles/29500",
        )

    def test_vietnam_competitor_tags_kept(self) -> None:
        self.assertBrands("CGV Việt Nam mở rộng hệ thống rạp tại TP.HCM", ["cgv"])
        self.assertBrands("Lotte Cinema Việt Nam khai trương rạp tại Hà Nội", ["lotte"])
        self.assertBrands("Galaxy Cinema khai trương rạp mới tại Bình Dương", ["glx"])
        self.assertBrands(
            "CGV và Lotte Cinema cạnh tranh tại thị trường Việt Nam",
            ["cgv", "lotte"],
        )

    def test_keyword_match_does_not_imply_brand(self) -> None:
        self.assertBrands(
            "Ngạc nhiên cảnh quay như phim",
            [],
            matches=["Lotte Cinema", "CGV Cinemas"],
        )
        self.assertBrands(
            "Ngạc nhiên cảnh quay như phim Lotte catcher được chọn giải CGV hàng tháng - starnewskorea.com",
            [],
        )
        self.assertBrands(
            "Bitcoin Nvidia Fed giá dầu",
            [],
            matches=["Galaxy Cinema", "CGV"],
        )

    def test_galaxycine_vn_publisher_tags_glx(self) -> None:
        self.assertBrands(
            "Quà Tặng Mừng Quốc Khánh 2/9 – Tự Hào Việt Nam - galaxycine.vn",
            ["glx"],
            permalink="https://news.google.com/rss/articles/CBMiExample",
        )
        self.assertBrands(
            "[Review] The Odyssey: In Nolan We Trust? - galaxycine.vn",
            ["glx"],
        )
        # Phone content must not become GLX even if publisher string appears
        self.assertBrands("Samsung Galaxy Ultra ra mắt - galaxycine.vn", [])
        self.assertBrands("Galaxy Ultra đang bị vượt mặt", [])

    def test_soft_spam_does_not_wipe_explicit_brand(self) -> None:
        # "các suất chiếu" alone used to wipe all brands via spam exclude
        self.assertBrands(
            "Beta Cinemas Trần Quang Khải hưởng ứng Tuần phim với các suất chiếu miễn phí",
            ["beta"],
        )
        self.assertBrands(
            "CGV Việt Nam mở các suất chiếu đặc biệt cuối tuần",
            ["cgv"],
        )
        self.assertBrands(
            "Galaxy Cinema thông báo các suất chiếu IMAX tuần này",
            ["glx"],
        )
        # Soft spam without explicit brand still suppresses tagging
        self.assertBrands(
            "Xem ngay các suất chiếu hấp dẫn tại rạp gần nhà",
            [],
            matches=["Beta Cinemas", "Galaxy Cinema"],
        )

    def test_hard_spam_still_wipes(self) -> None:
        self.assertBrands(
            "Pass vé Galaxy Cinema số lượng lớn rẻ hơn giá rạp",
            [],
        )
        self.assertBrands(
            "Tuyển dụng part-time tại CGV Việt Nam",
            [],
        )

    def test_venue_names_and_hashtags_kept(self) -> None:
        self.assertBrands("CGV Menas Mall giá vé 70K", ["cgv"])
        self.assertBrands("Lịch chiếu tại CGV Liberty Citypoint", ["cgv"])
        self.assertBrands("Valentine Sweetbox #cgv #cgvvietnam", ["cgv"])
        self.assertBrands("MUA 01 VÉ NHẬN TRANH BHD Star Hà Nội", ["bhd"])

    def test_bare_lotte_still_requires_cinema_phrase(self) -> None:
        # Intentionally unchanged: bare Lotte is too ambiguous (Mart/Hotel/etc.)
        self.assertBrands("Vé xem phim Lotte chỉ từ 79K", [])
        self.assertBrands("Vé xem phim Lotte Cinema chỉ từ 79K", ["lotte"])
        self.assertBrands("lotte mart sale", [])

    def test_foreign_and_unrelated_still_out(self) -> None:
        self.assertBrands("CGV Korea khai trương tại Seoul", [])
        self.assertBrands(
            "Park Eun-bin đi xem phim - starnewskorea.com",
            [],
            matches=["rạp CGV"],
        )
        self.assertBrands(
            "Houston Dynamo 1-0 Los Angeles Galaxy - Vietnam.vn",
            [],
            matches=["galaxy đà nẵng"],
        )
        self.assertBrands(
            "Caritas hỗ trợ vùng lũ - cgvdt.vn",
            [],
            matches=["CGV Việt Nam"],
        )
        self.assertBrands(
            "Bitget Bitcoin Nvidia Fed giá dầu",
            [],
            matches=["beta gia lai"],
        )


if __name__ == "__main__":
    unittest.main()
