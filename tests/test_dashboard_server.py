from __future__ import annotations

import io
import json
import unittest

from social_listening.dashboard.server import create_app


class FakeRepository:
    def get_available_films(self):
        return ["THO OI !!"]

    def get_sentiment_rows(self, film_title=None):
        return [{"platform": "facebook", "positive": 5, "negative": 1, "neutral": 4, "total_comments": 10, "buzz_score": 0.6}]

    def get_social_rows(self, film_title=None, limit=5000):
        return [
            {
                "platform": "facebook",
                "page_name": "Galaxy page",
                "post_text": "Review phim THO OI !!",
                "comments_": ["Phim hay quá", "Phim hơi chán"],
            }
        ]


class DashboardServerTests(unittest.TestCase):
    def call_app(self, path: str):
        status_headers = {}

        def start_response(status, headers):
            status_headers["status"] = status
            status_headers["headers"] = headers

        app = create_app(repository=FakeRepository())
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(),
        }
        body = b"".join(app(environ, start_response))
        return status_headers["status"], dict(status_headers["headers"]), body

    def test_health_endpoint(self):
        status, headers, body = self.call_app("/health")
        self.assertEqual(status, "200 OK")
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body.decode("utf-8"))["ok"], True)

    def test_report_endpoint(self):
        status, headers, body = self.call_app("/api/report")
        self.assertEqual(status, "200 OK")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["film_title"], "THO OI !!")
        self.assertEqual(payload["totals"]["posts"], 1)


if __name__ == "__main__":
    unittest.main()
