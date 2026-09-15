"""Unit tests for Distribution film detection + intent/sentiment v1.1."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from social_listening.film_classify import classify_intent, detect_sentiment
from social_listening.film_rules import (
    _build_detect_config,
    clear_alias_cache,
    detect_film_slugs,
    film_relevant_for_slug,
    match_is_core_identifier,
    normalize,
)

_SCRIPTS_DIS = Path(__file__).resolve().parents[1] / "scripts" / "dis"
if str(_SCRIPTS_DIS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIS))



class FilmSentimentTest(unittest.TestCase):
    def test_praise(self) -> None:
        self.assertEqual(detect_sentiment("Phim này quá hay luôn"), "positive")
        self.assertEqual(detect_sentiment("diễn xuất tốt cảm động quá"), "positive")

    def test_criticize(self) -> None:
        self.assertEqual(detect_sentiment("phí tiền chán quá"), "negative")
        self.assertEqual(detect_sentiment("kịch bản lê thê thất vọng"), "negative")

    def test_nhung_priority(self) -> None:
        self.assertEqual(
            detect_sentiment("Diễn viên diễn ổn nhưng kịch bản hơi dở"),
            "negative",
        )
        self.assertEqual(
            detect_sentiment("Mở đầu hơi nhạt nhưng càng xem càng hay"),
            "positive",
        )

    def test_neutral(self) -> None:
        self.assertEqual(detect_sentiment("Mai đi với bạn"), "neutral")


class FilmIntentTest(unittest.TestCase):
    def test_want_to_see(self) -> None:
        self.assertEqual(classify_intent("Cuối tuần đi xem Nghỉ Hè sợ Nghỉ Hưu"), "want_to_see")
        self.assertEqual(classify_intent("Săn vé The Odyssey luôn"), "want_to_see")
        self.assertEqual(classify_intent("Nghe nói hay để dành cuối tuần coi"), "want_to_see")

    def test_negation(self) -> None:
        self.assertEqual(classify_intent("Không xem đâu chán lắm"), "not_interested")
        self.assertEqual(classify_intent("Khỏi xem phim này"), "not_interested")

    def test_watched(self) -> None:
        self.assertEqual(classify_intent("Đã xem rồi hay quá"), "watched_praise")
        self.assertEqual(classify_intent("Xem xong thất vọng phí tiền"), "watched_criticize")

    def test_sentiment_alone_not_wom(self) -> None:
        """Chỉ 'hay/dở' không đủ — tránh khen/chê ảo trên post IG lạ."""
        self.assertIsNone(classify_intent("Phim này quá hay luôn"))
        self.assertIsNone(classify_intent("phí tiền chán quá"))


class FilmDetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clear_alias_cache()

    def test_nghi_he_core(self) -> None:
        slugs = detect_film_slugs("Trailer Nghỉ Hè sợ Nghỉ Hưu mới ra")
        self.assertIn("nghi_he_so_nghi_huu", slugs)

    def test_nghi_he_hashtag(self) -> None:
        slugs = detect_film_slugs("Hóng #NghiHeSoNghiHuu quá")
        self.assertIn("nghi_he_so_nghi_huu", slugs)

    def test_am_needs_context(self) -> None:
        self.assertNotIn("am_chuoi_phim_ngan_linh_di", detect_film_slugs("tôi bị ám ảnh"))
        self.assertIn(
            "am_chuoi_phim_ngan_linh_di",
            detect_film_slugs("Xem trailer phim Ám chuỗi phim ngắn"),
        )

    def test_odyssey_ambiguous(self) -> None:
        self.assertNotIn("the_odyssey", detect_film_slugs("reading Odyssey at school today"))
        self.assertIn("the_odyssey", detect_film_slugs("The Odyssey trailer ra rạp"))
        self.assertIn("the_odyssey", detect_film_slugs("#Odyssey Nolan movie review"))

    def test_odyssey_excludes(self) -> None:
        self.assertNotIn(
            "the_odyssey",
            detect_film_slugs("Honda Odyssey trailer sale at dealership"),
        )
        self.assertNotIn(
            "the_odyssey",
            detect_film_slugs("Assassin's Creed Odyssey game review trailer"),
        )
        self.assertNotIn(
            "the_odyssey",
            detect_film_slugs("Reading Homer The Odyssey in class trailer"),
        )

    def test_minion_with_context(self) -> None:
        self.assertIn("minion", detect_film_slugs("đưa trẻ đi xem phim Minions"))
        self.assertNotIn("minion", detect_film_slugs("đổi avatar minion sticker"))

    def test_spider_core(self) -> None:
        slugs = detect_film_slugs("Spider-Man Brand New Day trailer")
        self.assertIn("nguoi_nhen_khoi_dau_moi", slugs)

    def test_spider_franchise_guard(self) -> None:
        # Old Spider-Man chatter without "Khởi Đầu Mới" / Brand New Day
        self.assertNotIn(
            "nguoi_nhen_khoi_dau_moi",
            detect_film_slugs("Nhớ Spider-Man No Way Home quá"),
        )
        self.assertIn(
            "nguoi_nhen_khoi_dau_moi",
            detect_film_slugs("Người Nhện phần mới Khởi Đầu Mới trailer"),
        )

    def test_cross_film_not_confused(self) -> None:
        slugs = detect_film_slugs("#Odyssey Christopher Nolan movie trailer")
        self.assertIn("the_odyssey", slugs)
        self.assertNotIn("nghi_he_so_nghi_huu", slugs)

    def test_am_soft_exclude(self) -> None:
        self.assertNotIn(
            "am_chuoi_phim_ngan_linh_di",
            detect_film_slugs("tôi bị ám ảnh về chuyện cũ"),
        )
        self.assertIn(
            "am_chuoi_phim_ngan_linh_di",
            detect_film_slugs("Ám chuỗi phim ngắn linh dị trailer"),
        )

    def test_dear_you_aliases(self) -> None:
        self.assertIn("thu_tinh_gui_ngoai", detect_film_slugs("Đi xem Thư Tình Gửi Ngoại cuối tuần"))
        self.assertIn("thu_tinh_gui_ngoai", detect_film_slugs("Bức Thư Gửi Bà Ngoại đáng xem quá"))
        self.assertIn("thu_tinh_gui_ngoai", detect_film_slugs("Dear You trailer #DearYou"))

    def test_conan_movie29_guard(self) -> None:
        self.assertNotIn(
            "conan_thien_than_sa_nga_tren_xa_lo",
            detect_film_slugs("Đọc manga Conan chương mới"),
        )
        self.assertNotIn(
            "conan_thien_than_sa_nga_tren_xa_lo",
            detect_film_slugs("Xem lại Conan Movie 28"),
        )
        self.assertIn(
            "conan_thien_than_sa_nga_tren_xa_lo",
            detect_film_slugs("Conan Movie 29 trailer Thiên Thần Sa Ngã"),
        )
        self.assertIn(
            "conan_thien_than_sa_nga_tren_xa_lo",
            detect_film_slugs("Quái Xế Đen trong Conan phần mới"),
        )


class FilmDiscoveryKeywordRelevanceTest(unittest.TestCase):
    """CASE A–D: title vs person discovery keywords must not auto-assign film_id."""

    SLUG = "nghi_he_so_nghi_huu"
    TITLE = "Nghỉ Hè Sợ Nghỉ Hưu"
    PERSON = "Huỳnh Lập"

    @classmethod
    def setUpClass(cls) -> None:
        clear_alias_cache()
        cls._cfg = _build_detect_config(
            cls.SLUG,
            title=cls.TITLE,
            aliases=[
                "Nghỉ Hè Sợ Nghỉ Hưu",
                "#NghiHeSoNghiHuu",
                "#PhimHuynhLap2026",
                "#HuynhLap",  # person hashtag — must be demoted to discovery
            ],
            payload={
                "core_keywords": [cls.TITLE],
                "keywords": [cls.TITLE, cls.PERSON],
                "hashtags": ["#NghiHeSoNghiHuu", "#HuynhLap"],
                "discovery_keywords": [cls.PERSON],
            },
        )

    def setUp(self) -> None:
        clear_alias_cache()
        self._patcher = patch(
            "social_listening.film_rules.load_film_detect_configs",
            return_value=[self._cfg],
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        clear_alias_cache()

    def test_case_a_title_keyword_mentions_film(self) -> None:
        """CASE A: film title keyword + content mentions film → ACCEPT."""
        text = "Trailer Nghỉ Hè Sợ Nghỉ Hưu mới ra rạp cuối tuần này"
        slugs = detect_film_slugs(text, [self.TITLE])
        self.assertIn(self.SLUG, slugs)
        self.assertTrue(film_relevant_for_slug(text, self.SLUG))

    def test_case_b_person_keyword_and_film_in_text(self) -> None:
        """CASE B: person discovery keyword but text also names the film → ACCEPT."""
        text = "Huỳnh Lập đóng chính Nghỉ Hè Sợ Nghỉ Hưu, trailer hay quá"
        slugs = detect_film_slugs(text, [self.PERSON])
        self.assertIn(self.SLUG, slugs)
        self.assertTrue(film_relevant_for_slug(text, self.SLUG))

    def test_case_c_person_keyword_other_film_only(self) -> None:
        """CASE C: person keyword hit about another Huỳnh Lập film → REJECT."""
        text = "Xem lại phim Nhà Gia Tiên của Huỳnh Lập vẫn hay và cảm động"
        slugs = detect_film_slugs(text, [self.PERSON])
        self.assertNotIn(self.SLUG, slugs)
        self.assertFalse(film_relevant_for_slug(text, self.SLUG))

    def test_case_d_person_keyword_general_only(self) -> None:
        """CASE D: person keyword hit with no film connection → REJECT."""
        text = "Huỳnh Lập sống tình cảm lắm luôn, nhìn món quà là biết"
        slugs = detect_film_slugs(text, [self.PERSON])
        self.assertNotIn(self.SLUG, slugs)
        self.assertFalse(film_relevant_for_slug(text, self.SLUG))

    def test_person_hashtag_alone_rejected(self) -> None:
        text = "Chú Đông Hùng bưng anh Huỳnh Lập cái 1 #HuynhLap #DongHung"
        self.assertNotIn(self.SLUG, detect_film_slugs(text, [self.PERSON, "#HuynhLap"]))

    def test_path_keyword_person_not_core(self) -> None:
        self.assertFalse(match_is_core_identifier(self.PERSON, self.SLUG))
        self.assertTrue(match_is_core_identifier(self.TITLE, self.SLUG))
        self.assertFalse(match_is_core_identifier("#HuynhLap", self.SLUG))
        self.assertTrue(match_is_core_identifier("#NghiHeSoNghiHuu", self.SLUG))

    def test_path_plus_keyword_rejects_person_discovery(self) -> None:
        from import_film_mentions import resolve_films_for_text

        film_map = {self.SLUG: "film-uuid"}
        # Empty text + person crawl keyword under film folder → must skip
        detected, method = resolve_films_for_text("", [self.PERSON], self.SLUG, film_map)
        self.assertEqual(detected, [])
        self.assertEqual(method, "skip-path")
        # Title crawl keyword under film folder → accept (core match folded into detect)
        detected, method = resolve_films_for_text("", [self.TITLE], self.SLUG, film_map)
        self.assertEqual([s.lower() for s in detected], [self.SLUG])
        self.assertIn(method, {"path+keyword", "path+alias"})


class DbCoreKeywordsNotMergedTest(unittest.TestCase):
    def test_build_keeps_person_out_of_core(self) -> None:
        cfg = _build_detect_config(
            "nghi_he_so_nghi_huu",
            title="Nghỉ Hè Sợ Nghỉ Hưu",
            aliases=["#HuynhLap", "#NghiHeSoNghiHuu"],
            payload={
                "core_keywords": ["Nghỉ Hè Sợ Nghỉ Hưu", "Huỳnh Lập"],
                "keywords": ["Nghỉ Hè Sợ Nghỉ Hưu", "Huỳnh Lập"],
            },
        )
        self.assertIsNotNone(cfg)
        assert cfg is not None
        self.assertIn("nghi he so nghi huu", cfg.core_norms)
        self.assertNotIn("huynh lap", cfg.core_norms)
        self.assertNotIn("#huynhlap", cfg.core_norms)
        modes = {normalize(r): m for r, _, m in cfg.terms}
        self.assertEqual(modes.get("huynh lap"), "discovery")
        self.assertEqual(modes.get("#huynhlap"), "discovery")


if __name__ == "__main__":
    unittest.main()
