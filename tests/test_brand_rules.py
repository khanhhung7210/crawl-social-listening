"""Unit tests for competitive brand include/exclude rules."""

from __future__ import annotations

import unittest

from social_listening.brand_rules import detect_competitive_brands


class BrandRulesTest(unittest.TestCase):
    def assertBrands(self, text: str, expect: list[str]) -> None:
        got = detect_competitive_brands(text)
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


if __name__ == "__main__":
    unittest.main()
