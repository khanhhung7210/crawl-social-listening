from __future__ import annotations

import json
import os
from pathlib import Path

from social_listening.paths import DATA_DIR


SHARED_KEYWORD_CONFIG_FILE = DATA_DIR / "shared" / "social_keywords.json"


def load_keyword_payload(path: Path | None = None) -> dict:
    env_path = str(os.getenv("SOCIAL_KEYWORD_CONFIG_FILE") or os.getenv("KEYWORD_CONFIG_FILE") or "").strip()
    keyword_file = path or (Path(env_path) if env_path else SHARED_KEYWORD_CONFIG_FILE)
    if not keyword_file.exists():
        raise FileNotFoundError(f"Keyword config file not found: {keyword_file}")

    payload = json.loads(keyword_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected object payload in {keyword_file}")
    return payload


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


def collect_search_terms(payload: dict, include_hashtags: bool = True) -> list[str]:
    terms: list[str] = []
    keys = ["keywords", "sub_keywords"]
    if include_hashtags:
        keys.append("hashtags")

    for key in keys:
        for term in collect_keyword_values(payload, key):
            if term not in terms:
                terms.append(term)
    return terms


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
