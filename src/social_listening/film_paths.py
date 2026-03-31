from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from social_listening.keyword_config import load_keyword_payload
from social_listening.paths import DATA_DIR


def film_slug() -> str:
    payload = load_keyword_payload()
    title = str(payload.get("film_title") or "").strip() or "default_film"
    normalized = unicodedata.normalize("NFD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "default_film"


def platform_raw_dir(platform: str) -> Path:
    return DATA_DIR / platform / "raw" / film_slug()


def platform_processed_dir(platform: str) -> Path:
    return DATA_DIR / platform / "processed" / film_slug()
