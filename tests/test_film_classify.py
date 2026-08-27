"""Unit tests for Distribution film detection + intent/sentiment v1.1."""

from __future__ import annotations

import unittest

from social_listening.film_classify import classify_intent, detect_sentiment
from social_listening.film_rules import clear_alias_cache, detect_film_slugs


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


if __name__ == "__main__":
    unittest.main()
