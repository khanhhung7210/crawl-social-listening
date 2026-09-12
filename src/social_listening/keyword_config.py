from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from social_listening.paths import DATA_DIR

logger = logging.getLogger(__name__)

SHARED_KEYWORD_CONFIG_FILE = DATA_DIR / "shared" / "social_keywords.json"


def _config_source() -> str:
    """Return config source mode: db | file | auto."""
    return str(os.getenv("SOCIAL_CONFIG_SOURCE") or "auto").strip().lower()


def _is_distribution_profile() -> bool:
    profile = (os.getenv("SOCIAL_LISTENING_PROFILE") or "mkt").strip().lower()
    slug = (os.getenv("SOCIAL_FILM_SLUG") or "").strip()
    return profile in {"dis", "distribution", "film"} or bool(slug)


def _load_from_file() -> dict:
    env_path = str(os.getenv("SOCIAL_KEYWORD_CONFIG_FILE") or os.getenv("KEYWORD_CONFIG_FILE") or "").strip()
    keyword_file = Path(env_path) if env_path else SHARED_KEYWORD_CONFIG_FILE
    if not keyword_file.exists():
        raise FileNotFoundError(f"Keyword config file not found: {keyword_file}")

    payload = json.loads(keyword_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected object payload in {keyword_file}")
    return payload


def _load_from_db() -> dict:
    from social_listening.config.db_source import load_keyword_payload_from_db

    return load_keyword_payload_from_db()


def load_keyword_payload(path: Path | None = None) -> dict:
    """Load keyword config.

    Priority:
    1. Explicit ``path`` argument
    2. ``SOCIAL_CONFIG_SOURCE=db`` → Postgres (MKT or DIS via SOCIAL_FILM_SLUG)
    3. ``SOCIAL_CONFIG_SOURCE=file`` → ``SOCIAL_KEYWORD_CONFIG_FILE`` / shared JSON
    4. ``SOCIAL_CONFIG_SOURCE=auto`` (default) → DB when listening_queries exist,
       else file fallback for local/dev bootstrap only
    """
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"Keyword config file not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected object payload in {path}")
        return payload

    source = _config_source()
    if source == "file":
        return _load_from_file()

    if source == "db":
        return _load_from_db()

    if source == "auto":
        return _load_auto()

    raise RuntimeError(
        f"Invalid SOCIAL_CONFIG_SOURCE={source!r}. Use one of: auto, db, file"
    )


def _load_auto() -> dict:
    from social_listening.config.db_source import (
        DbConfigEmptyError,
        DbConnectionError,
        marketing_listening_queries_exist,
    )

    if _is_distribution_profile():
        try:
            return _load_from_db()
        except DbConfigEmptyError:
            logger.warning(
                "SOCIAL_CONFIG_SOURCE=auto: no film listening_queries in DB; "
                "falling back to keyword file"
            )
            return _load_from_file()
        except DbConnectionError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "SOCIAL_CONFIG_SOURCE=auto: distribution DB keyword config failed"
            ) from exc

    try:
        if marketing_listening_queries_exist():
            return _load_from_db()
    except DbConnectionError:
        raise RuntimeError(
            "SOCIAL_CONFIG_SOURCE=auto: Postgres is unreachable; "
            "refusing to fall back to social_keywords.json. "
            "Set SOCIAL_CONFIG_SOURCE=file for offline crawl."
        ) from None

    logger.warning(
        "SOCIAL_CONFIG_SOURCE=auto: no brand listening_queries in DB; "
        "falling back to %s",
        SHARED_KEYWORD_CONFIG_FILE,
    )
    return _load_from_file()


def uses_db_keyword_config() -> bool:
    """Return True when the next crawl would load keywords from Postgres."""
    source = _config_source()
    if source == "db":
        return True
    if source == "file":
        return False
    if _is_distribution_profile():
        try:
            from social_listening.config.db_source import marketing_listening_queries_exist

            _ = marketing_listening_queries_exist  # distribution always tries DB first
            return True
        except Exception:
            return False
    try:
        from social_listening.config.db_source import marketing_listening_queries_exist

        return marketing_listening_queries_exist()
    except Exception:
        return False


def resolve_active_process(payload: dict, process_name: str | None = None) -> str:
    explicit = str(process_name or "").strip()
    if explicit:
        return explicit

    env_process = str(os.getenv("SOCIAL_LISTENING_PROCESS") or os.getenv("KEYWORD_PROCESS") or "").strip()
    if env_process:
        return env_process

    return str(payload.get("active_process") or payload.get("process") or "").strip()


def collect_keyword_values(payload: dict, key: str, process_name: str | None = None) -> list[str]:
    return collect_config_values(payload, key, process_name=process_name)


def collect_config_values(
    payload: dict,
    key: str,
    process_name: str | None = None,
    value_fields: tuple[str, ...] = ("value", "keyword", "term", "name", "url", "query"),
) -> list[str]:
    values = payload.get(key) or []
    if not isinstance(values, list):
        return []

    active_process = resolve_active_process(payload, process_name)
    terms: list[str] = []
    for value in values:
        term = normalize_term_value(value, value_fields=value_fields)
        if not term or term in terms:
            continue
        if not is_term_enabled(value, active_process):
            continue
        terms.append(term)
    return terms


def collect_search_terms(payload: dict, include_hashtags: bool = True, include_competitors: bool = True) -> list[str]:
    terms: list[str] = []
    keys = [
        "keywords",
        "core_keywords",
        "sub_keywords",
        "branch_keywords",
        "listening_keywords",
        "boost_keywords",
    ]
    if include_hashtags:
        keys.append("hashtags")
    if include_competitors:
        keys.append("competitor_keywords")

    for key in keys:
        for term in collect_keyword_values(payload, key):
            if term not in terms:
                terms.append(term)
    return terms


# Crawl flush order: own brand first so GLX posts import before competitors finish.
BRAND_CRAWL_GROUP_ORDER = ("glx", "cgv", "lotte", "beta", "bhd", "cinestar", "other")


def classify_search_term_brand(term: str) -> str:
    """Map a search keyword to a cinema brand bucket for phased crawl/import."""
    normalized = str(term or "").strip().lower().lstrip("#")
    if not normalized:
        return "other"
    compact = normalized.replace(" ", "")
    glx_hints = (
        "galaxy",
        "galaxycinema",
        "galaxymovie",
        "cinechao",
        "cinechào",
        "đắmmình",
        "dammình",
        "ưuđãicine",
        "uudaicine",
        "chàosummer",
        "chaosummer",
    )
    if any(hint in compact or hint in normalized for hint in glx_hints):
        return "glx"
    if "cgv" in normalized:
        return "cgv"
    if "lotte" in normalized:
        return "lotte"
    if "beta" in normalized:
        return "beta"
    if "bhd" in normalized:
        return "bhd"
    if "cinestar" in normalized:
        return "cinestar"
    return "other"


def group_search_terms_by_brand(terms: list[str]) -> list[tuple[str, list[str]]]:
    """Preserve first-seen order within each brand; emit non-empty groups in BRAND_CRAWL_GROUP_ORDER."""
    buckets: dict[str, list[str]] = {key: [] for key in BRAND_CRAWL_GROUP_ORDER}
    seen: set[str] = set()
    for term in terms:
        text = str(term or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        buckets[classify_search_term_brand(text)].append(text)
    return [(brand, items) for brand, items in ((k, buckets[k]) for k in BRAND_CRAWL_GROUP_ORDER) if items]


def collect_exclude_terms(payload: dict) -> list[str]:
    """Spam / junk phrases — drop post/comment if text matches (not used for FB search)."""
    terms: list[str] = []
    for key in ("exclude_keywords", "spam_keywords"):
        for term in collect_keyword_values(payload, key):
            if term not in terms:
                terms.append(term)
    return terms


def matching_exclude_terms(text: str, exclude_terms: list[str]) -> list[str]:
    """Return exclude terms that match text (empty when clean)."""
    if not text or not exclude_terms:
        return []
    from social_listening.text_utils import contains_keyword

    return [term for term in exclude_terms if contains_keyword(text, term)]


def text_hits_exclude(text: str, exclude_terms: list[str]) -> bool:
    return bool(matching_exclude_terms(text, exclude_terms))


def film_title(path: Path | None = None) -> str:
    payload = load_keyword_payload(path)
    return str(payload.get("film_title") or "").strip()


def normalize_term_value(value, value_fields: tuple[str, ...] = ("value", "keyword", "term", "name")) -> str:
    if isinstance(value, dict):
        for field in value_fields:
            term = str(value.get(field) or "").strip()
            if term:
                return term
        return ""
    return str(value or "").strip()


def is_term_enabled(value, active_process: str) -> bool:
    if isinstance(value, dict):
        enabled = value.get("enabled")
        if enabled is False:
            return False

        processes = normalize_processes(value.get("processes", value.get("process")))
        if not processes:
            return True
        if not active_process:
            return False
        return active_process in processes or "*" in processes or "all" in processes
    return True


def normalize_processes(value) -> set[str]:
    if isinstance(value, str):
        process = value.strip()
        return {process} if process else set()
    if isinstance(value, list):
        return {str(item or "").strip() for item in value if str(item or "").strip()}
    return set()
