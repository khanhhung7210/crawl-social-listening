from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.paths import DATA_DIR, ensure_dir


# Edit values here, then run:
# python3 threads_runner.py
TOKEN = "UM2ogYU6e2PnpMBY"
OUTPUT_ROOT = DATA_DIR / "threads" / "raw" / "threads_output"

# Same shape as the old script: group name -> list of keywords
KEYWORDS = {
    "main_keywords": [
        "Thỏ ơi",
    ],
    "sub_keywords": [],
    "film_keywords": [],
}

# Optional hashtags if you want raw hashtag JSON too
HASHTAGS: list[str] = []

BASE_URL = "https://ensembledata.com/apis"
# 1 = recent (not Top / relevance)
THREADS_SORTING_RECENT = 1


def slugify(text: str) -> str:
    text = text.lower()
    text = text.replace("*", "_KN_")
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    return text


def keyword_matches(text: str, keyword: str) -> bool:
    """Require the search keyword (or hashtag body) to appear in item text before save."""
    hay = (text or "").casefold()
    needle = (keyword or "").strip().casefold().lstrip("#")
    if not needle:
        return False
    return needle in hay


def _item_text(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    parts: list[str] = []
    for key in ("text", "caption", "content", "title", "body"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    # Nested common EnsembleData shapes
    for nest_key in ("post", "thread", "node", "item"):
        nested = item.get(nest_key)
        if isinstance(nested, dict):
            parts.append(_item_text(nested))
    return "\n".join(parts)


def filter_keyword_hits(payload: object, keyword: str) -> object:
    """Keep only items whose text matches the keyword (Recent search, then validate)."""
    if isinstance(payload, list):
        return [item for item in payload if keyword_matches(_item_text(item), keyword)]
    if not isinstance(payload, dict):
        return payload

    data = dict(payload)
    for key in ("data", "items", "results", "threads", "posts"):
        rows = data.get(key)
        if isinstance(rows, list):
            data[key] = [item for item in rows if keyword_matches(_item_text(item), keyword)]
            data["filtered_by_keyword"] = keyword
            data["sorting"] = THREADS_SORTING_RECENT
            return data
    return data


def search_keywords_grouped(keywords_dict: dict[str, list[str]], output_root: Path, token: str) -> None:
    endpoint = "/threads/keyword/search"

    for group_name, keyword_list in keywords_dict.items():
        out_dir = output_root / "keywords" / group_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for keyword in keyword_list:
            slug = slugify(keyword)
            filename = out_dir / f"keyword_{slug}.json"

            params = {
                "name": keyword,
                "sorting": THREADS_SORTING_RECENT,
                "token": token,
            }

            try:
                response = requests.get(BASE_URL + endpoint, params=params, timeout=30)
                response.raise_for_status()
                data = filter_keyword_hits(response.json(), keyword)
            except Exception as exc:
                print(f"[ERROR] keyword='{keyword}' group='{group_name}' error={exc}")
                continue

            filename.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[Keyword] '{keyword}' in '{group_name}' sorting=recent -> {filename}")


def search_hashtags(hashtags: list[str], output_root: Path, token: str) -> None:
    endpoint = "/threads/keyword/search"
    out_dir = output_root / "hashtags"
    out_dir.mkdir(parents=True, exist_ok=True)

    for hashtag in hashtags:
        slug = slugify(hashtag)
        filename = out_dir / f"hashtag_{slug}.json"

        params = {
            "name": hashtag,
            "sorting": THREADS_SORTING_RECENT,
            "token": token,
        }

        try:
            response = requests.get(BASE_URL + endpoint, params=params, timeout=30)
            response.raise_for_status()
            data = filter_keyword_hits(response.json(), hashtag)
        except Exception as exc:
            print(f"[ERROR] hashtag='{hashtag}' error={exc}")
            continue

        filename.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Hashtag] '{hashtag}' sorting=recent -> {filename}")


def main() -> int:
    token = TOKEN.strip()
    if not token:
        raise RuntimeError("Missing TOKEN.")

    ensure_dir(OUTPUT_ROOT)
    search_keywords_grouped(KEYWORDS, OUTPUT_ROOT, token)
    if HASHTAGS:
        search_hashtags(HASHTAGS, OUTPUT_ROOT, token)
    print(f"saved raw Threads JSON under {OUTPUT_ROOT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
