from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from social_listening.keyword_config import load_keyword_payload
from social_listening.paths import DATA_DIR


def film_slug() -> str:
    """Folder slug for raw/processed — ưu tiên field slug trong keyword JSON (khớp catalog)."""
    payload = load_keyword_payload()
    explicit = str(payload.get("film_slug") or payload.get("slug") or "").strip()
    if explicit:
        return re.sub(r"[^a-zA-Z0-9]+", "_", explicit.lower()).strip("_") or explicit.lower()

    title = str(payload.get("film_title") or "").strip() or "default_film"
    normalized = unicodedata.normalize("NFD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "default_film"


def platform_raw_dir(platform: str) -> Path:
    return DATA_DIR / platform / "raw" / film_slug()


def platform_processed_dir(platform: str) -> Path:
    return DATA_DIR / platform / "processed" / film_slug()
