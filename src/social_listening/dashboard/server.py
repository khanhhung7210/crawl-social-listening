from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from social_listening.dashboard.analytics import build_dashboard_report
from social_listening.dashboard.repository import MongoDashboardRepository
from social_listening.keyword_config import film_title as shared_film_title

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(repository: MongoDashboardRepository | None = None):
    repo = repository or MongoDashboardRepository(db_name=os.getenv("MONGO_DB", "CRM"))

    def app(environ, start_response):
        try:
            path = environ.get("PATH_INFO", "/")
            method = environ.get("REQUEST_METHOD", "GET").upper()
            if method != "GET":
                return respond_json(start_response, {"error": "Method not allowed"}, status="405 Method Not Allowed")

            if path == "/":
                return respond_file(start_response, STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                relative = path.removeprefix("/static/")
                target = (STATIC_DIR / relative).resolve()
                if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
                    return respond_json(start_response, {"error": "Not found"}, status="404 Not Found")
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return respond_file(start_response, target, content_type)
            if path == "/api/films":
                return respond_json(start_response, {"films": repo.get_available_films()})
            if path == "/api/report":
                params = parse_qs(environ.get("QUERY_STRING", ""))
                available_films = repo.get_available_films()
                explicit_title = first_param(params, "film_title")
                requested_title = explicit_title or (shared_film_title() if available_films else "")
                if not explicit_title and available_films and requested_title not in available_films:
                    requested_title = available_films[0]
                if not requested_title and available_films:
                    requested_title = available_films[0]
                sentiment_rows = repo.get_sentiment_rows(requested_title)
                social_rows = repo.get_social_rows(requested_title)
                report = build_dashboard_report(requested_title, sentiment_rows, social_rows, available_films)
                if not available_films:
                    report["warning"] = "No film_title data found in CRM.tblSentiment or CRM.tblSocial"
                return respond_json(start_response, report)
            if path == "/health":
                return respond_json(start_response, {"ok": True})
            return respond_json(start_response, {"error": "Not found"}, status="404 Not Found")
        except Exception as exc:
            return respond_json(
                start_response,
                {"error": str(exc), "type": exc.__class__.__name__},
                status="500 Internal Server Error",
            )

    return app


def run_dev_server(host: str = "127.0.0.1", port: int = 8787) -> int:
    app = create_app()
    with make_server(host, port, app) as server:
        print(f"dashboard listening on http://{host}:{port}")
        server.serve_forever()
    return 0


def respond_json(start_response, payload: dict, status: str = "200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def respond_file(start_response, path: Path, content_type: str):
    body = path.read_bytes()
    start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def first_param(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or [""]
    return str(values[0]).strip()
