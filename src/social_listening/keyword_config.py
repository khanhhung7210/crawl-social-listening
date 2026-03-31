from __future__ import annotations

import json
from pathlib import Path

from social_listening.paths import DATA_DIR


SHARED_KEYWORD_CONFIG_FILE = DATA_DIR / "shared" / "social_keywords.json"


def load_keyword_payload(path: Path | None = None) -> dict:
    keyword_file = path or SHARED_KEYWORD_CONFIG_FILE
    if not keyword_file.exists():
        raise FileNotFoundError(f"Keyword config file not found: {keyword_file}")

    payload = json.loads(keyword_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected object payload in {keyword_file}")
    return payload


def collect_search_terms(payload: dict, include_hashtags: bool = True) -> list[str]:
    terms: list[str] = []
    keys = ["keywords", "sub_keywords"]
    if include_hashtags:
        keys.append("hashtags")

    for key in keys:
        values = payload.get(key) or []
        if not isinstance(values, list):
            continue
        for value in values:
            term = str(value or "").strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def film_title(path: Path | None = None) -> str:
    payload = load_keyword_payload(path)
    return str(payload.get("film_title") or "").strip()
