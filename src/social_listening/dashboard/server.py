from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from social_listening.dashboard.analytics import build_dashboard_report
from social_listening.dashboard.repository import JsonDashboardRepository, MongoDashboardRepository, PostgresDashboardRepository
from social_listening.keyword_config import film_title as shared_film_title

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_DASHBOARD_JSON_FILE = Path(__file__).resolve().parents[3] / "data" / "dashboard" / "meili_dashboard.json"


def create_app(repository=None):
    repo = repository or build_repository()
    fallback_repo = JsonDashboardRepository(DEFAULT_DASHBOARD_JSON_FILE) if DEFAULT_DASHBOARD_JSON_FILE.exists() else None

    def app(environ, start_response):
        try:
            path = environ.get("PATH_INFO", "/")
            method = environ.get("REQUEST_METHOD", "GET").upper()

            if path == "/" and method == "GET":
                return respond_file(start_response, STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/") and method == "GET":
                relative = path[len("/static/") :]
                target = (STATIC_DIR / relative).resolve()
                if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
                    return respond_json(start_response, {"error": "Not found"}, status="404 Not Found")
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                return respond_file(start_response, target, content_type)
            if path == "/api/films" and method == "GET":
                active_repo = repo
                try:
                    films = active_repo.get_available_films()
                except Exception:
                    if fallback_repo is None or active_repo is fallback_repo:
                        raise
                    active_repo = fallback_repo
                    films = active_repo.get_available_films()
                return respond_json(start_response, {"films": films})
            if path == "/api/report" and method == "GET":
                params = parse_qs(environ.get("QUERY_STRING", ""))
                active_repo = repo
                try:
                    available_films = active_repo.get_available_films()
                except Exception:
                    if fallback_repo is None or active_repo is fallback_repo:
                        raise
                    active_repo = fallback_repo
                    available_films = active_repo.get_available_films()
                explicit_title = first_param(params, "film_title")
                requested_title = explicit_title or (shared_film_title() if available_films else "")
                if not explicit_title and available_films and requested_title not in available_films:
                    requested_title = available_films[0]
                if not requested_title and available_films:
                    requested_title = available_films[0]
                try:
                    report = active_repo.get_dashboard_payload(requested_title)
                except Exception:
                    if fallback_repo is None or active_repo is fallback_repo:
                        raise
                    active_repo = fallback_repo
                    available_films = active_repo.get_available_films()
                    if not explicit_title and available_films and requested_title not in available_films:
                        requested_title = available_films[0]
                    if not requested_title and available_films:
                        requested_title = available_films[0]
                    report = active_repo.get_dashboard_payload(requested_title)
                if report is None:
                    sentiment_rows = active_repo.get_sentiment_rows(requested_title)
                    social_rows = active_repo.get_social_rows(requested_title)
                    report = build_dashboard_report(requested_title, sentiment_rows, social_rows, available_films)
                    if not available_films:
                        report["warning"] = "No film_title data found in CRM.tblSentiment or CRM.tblSocial"
                return respond_json(start_response, report)
            if path == "/api/source-config" and method == "GET":
                return respond_json(start_response, repo.get_source_config())
            if path == "/api/source-config" and method == "POST":
                payload = read_json_body(environ)
                sources = payload.get("sources") if isinstance(payload, dict) else []
                if not isinstance(sources, list):
                    return respond_json(start_response, {"error": "sources must be a list"}, status="400 Bad Request")
                saved = repo.save_source_config(payload if isinstance(payload, dict) else {"sources": sources})
                return respond_json(start_response, saved)
            if path == "/health" and method == "GET":
                return respond_json(start_response, {"ok": True})
            if method not in {"GET", "POST"}:
                return respond_json(start_response, {"error": "Method not allowed"}, status="405 Method Not Allowed")
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


def build_repository():
    source = str(os.getenv("DASHBOARD_SOURCE") or "").strip().lower()
    env_path = str(os.getenv("DASHBOARD_DATA_FILE") or "").strip()
    json_path = Path(env_path).expanduser() if env_path else DEFAULT_DASHBOARD_JSON_FILE
    if source in {"postgres", "pg"}:
        return PostgresDashboardRepository(
            database=os.getenv("PGDATABASE", "meili_dashboard"),
            schema=os.getenv("PGSCHEMA", "meili_dashboard"),
            brand_slug=os.getenv("DASHBOARD_BRAND_SLUG", "meili-mi-bo-dai-loan"),
            psql_bin=os.getenv("PSQL_BIN", "psql"),
        )
    if source in {"json"} and json_path.exists():
        return JsonDashboardRepository(json_path)
    if source in {"mongo"}:
        return MongoDashboardRepository(db_name=os.getenv("MONGO_DB", "CRM"))
    try:
        return PostgresDashboardRepository(
            database=os.getenv("PGDATABASE", "meili_dashboard"),
            schema=os.getenv("PGSCHEMA", "meili_dashboard"),
            brand_slug=os.getenv("DASHBOARD_BRAND_SLUG", "meili-mi-bo-dai-loan"),
            psql_bin=os.getenv("PSQL_BIN", "psql"),
        )
    except Exception:
        pass
    if json_path.exists():
        return JsonDashboardRepository(json_path)
    return MongoDashboardRepository(db_name=os.getenv("MONGO_DB", "CRM"))


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


def read_json_body(environ) -> dict:
    try:
        content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
    except ValueError:
        content_length = 0
    body = environ.get("wsgi.input").read(content_length) if content_length > 0 else b"{}"
    if not body:
        return {}
    payload = json.loads(body.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}
