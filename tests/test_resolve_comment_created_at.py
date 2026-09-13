"""Google / comment publish-time resolution must not invent crawl time."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from social_listening.review_utils import resolve_comment_created_at


class ResolveCommentCreatedAtTest(unittest.TestCase):
    def test_prefers_relative_label(self) -> None:
        crawl = "2026-09-13T04:02:00+00:00"
        out = resolve_comment_created_at(crawl, "4 tháng trước", crawl)
        self.assertTrue(out.startswith("2026-05-"))

    def test_empty_when_only_crawl_iso(self) -> None:
        crawl = "2026-09-13T04:02:00+00:00"
        self.assertEqual(resolve_comment_created_at(crawl, "", crawl), "")
        self.assertEqual(resolve_comment_created_at(None, "", crawl), "")

    def test_keeps_real_absolute_iso(self) -> None:
        crawl = "2026-09-13T04:02:00+00:00"
        real = "2026-05-15T04:59:15+00:00"
        self.assertEqual(resolve_comment_created_at(real, "", crawl), datetime.fromisoformat(real).isoformat())


if __name__ == "__main__":
    unittest.main()
