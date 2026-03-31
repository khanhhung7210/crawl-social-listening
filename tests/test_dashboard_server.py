from __future__ import annotations

import io
import json
import unittest
from urllib.parse import urlsplit

from social_listening.dashboard.server import create_app


class FakeRepository:
    def __init__(self):
        self.report_calls = []

    def get_available_films(self):
        return ["THO OI !!"]

    def get_sentiment_rows(self, film_title=None):
        self.report_calls.append(("sentiment", film_title))
        return [{"platform": "facebook", "positive": 5, "negative": 1, "neutral": 4, "total_comments": 10, "buzz_score": 0.6}]

    def get_social_rows(self, film_title=None, limit=5000):
        self.report_calls.append(("social", film_title))
        return [
            {
                "platform": "facebook",
                "page_name": "Galaxy page",
                "post_text": "Review phim THO OI !!",
                "comments_": ["Phim hay quá", "Phim hơi chán"],
            }
        ]


class DashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()

    def call_app(self, path: str):
        status_headers = {}
        parts = urlsplit(path)

        def start_response(status, headers):
            status_headers["status"] = status
            status_headers["headers"] = headers

        app = create_app(repository=self.repository)
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": parts.path,
            "QUERY_STRING": parts.query,
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

    def test_report_endpoint_uses_query_string_film_title(self):
        status, headers, body = self.call_app("/api/report?film_title=THO%20OI%20!!")
        self.assertEqual(status, "200 OK")
        self.assertEqual(self.repository.report_calls[0], ("sentiment", "THO OI !!"))
        self.assertEqual(self.repository.report_calls[1], ("social", "THO OI !!"))


class EmptyRepository:
    def get_available_films(self):
        return []

    def get_sentiment_rows(self, film_title=None):
        return []

    def get_social_rows(self, film_title=None, limit=5000):
        return []


class DashboardEmptyStateTests(unittest.TestCase):
    def test_report_endpoint_returns_warning_when_no_films_found(self):
        status_headers = {}

        def start_response(status, headers):
            status_headers["status"] = status
            status_headers["headers"] = headers

        app = create_app(repository=EmptyRepository())
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/report",
            "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(),
        }
        body = b"".join(app(environ, start_response))
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status_headers["status"], "200 OK")
        self.assertEqual(payload["film_title"], "")
        self.assertIn("warning", payload)


if __name__ == "__main__":
    unittest.main()
