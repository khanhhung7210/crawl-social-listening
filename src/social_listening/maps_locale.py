"""Force Google Maps UI + review text to Vietnamese (avoid Google Translate)."""

from __future__ import annotations

import os
import re
from urllib.parse import unquote


def maps_hl() -> str:
    return (os.getenv("GOOGLE_MAPS_HL") or "vi").strip() or "vi"


def maps_url_with_hl(url: str, hl: str | None = None) -> str:
    text = str(url or "").strip()
    if not text:
        return text
    lang = (hl or maps_hl()).strip() or "vi"
    text = re.sub(r"([?&])hl=[^&]*", r"\1", text)
    text = re.sub(r"\?&+", "?", text).rstrip("&").rstrip("?")
    joiner = "&" if "?" in text else "?"
    return f"{text}{joiner}hl={lang}"


def is_galaxy_cinema_place_url(url: str) -> bool:
    path = unquote(url or "").lower()
    if "maps/place/" not in path:
        return False
    place_name = path.split("/maps/place/", 1)[-1].split("/data=", 1)[0]
    if "galaxy" not in place_name:
        return False
    if any(tok in place_name for tok in ("tourist", "cgv", "lotte", "bhd", "cinestar")):
        return False
    return True
