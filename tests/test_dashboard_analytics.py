from __future__ import annotations

import unittest

from social_listening.dashboard.analytics import build_dashboard_report, detect_sentiment


class DashboardAnalyticsTests(unittest.TestCase):
    def test_detect_sentiment(self) -> None:
        self.assertEqual(detect_sentiment("Phim này hay quá và rất đáng xem"), "positive")
        self.assertEqual(detect_sentiment("Phim quá tệ và rất chán"), "negative")
        self.assertEqual(detect_sentiment("Mình vừa xem xong"), "neutral")

    def test_build_dashboard_report(self) -> None:
        sentiment_rows = [
            {"platform": "facebook", "positive": 10, "negative": 4, "neutral": 6, "total_comments": 20, "buzz_score": 0.7},
            {"platform": "youtube", "positive": 6, "negative": 2, "neutral": 2, "total_comments": 10, "buzz_score": 0.8},
        ]
        social_rows = [
            {
                "platform": "facebook",
                "page_name": "Galaxy page",
                "post_text": "Trailer phim Thỏ ơi ra rạp",
                "comments_": ["Phim hay quá", "Phim tệ thật", "Đợi xem trailer"],
            },
            {
                "platform": "youtube",
                "page_name": "Fan review",
                "post_text": "Review phim Thỏ ơi",
                "comments_": ["Xem ổn áp", "Diễn viên tốt", "Hơi chán đoạn cuối"],
            },
        ]

        report = build_dashboard_report("THO OI !!", sentiment_rows, social_rows, ["THO OI !!"])

        self.assertEqual(report["film_title"], "THO OI !!")
        self.assertEqual(report["totals"]["posts"], 2)
        self.assertEqual(report["sentiment_overview"]["total"], 30)
        self.assertTrue(report["top_sources"])
        self.assertTrue(report["platform_breakdown"])
        self.assertTrue(report["sentiment_by_topic"])


if __name__ == "__main__":
    unittest.main()
