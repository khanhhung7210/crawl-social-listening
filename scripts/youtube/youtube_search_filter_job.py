from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.text_utils import normalize_text


INPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results.json"
OUTPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "youtube" / "raw" / "youtube_search_results.json"


def main() -> int:
    input_file = INPUT_FILE if INPUT_FILE.exists() else LEGACY_INPUT_FILE
    if not input_file.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(input_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("youtube_search_results.json must be a JSON array")

    keyword_payload = load_keyword_payload()
    film_title = str(keyword_payload.get("film_title") or "").strip()
    if not film_title:
        raise RuntimeError("Missing film_title in shared keyword config")

    normalized_title = normalize_text(film_title)
    filtered: list[dict] = []
    seen: set[str] = set()

    for item in payload:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if normalize_text(keyword) != normalized_title:
            continue
        filtered.append({**item, "filter_keyword": film_title, "filter_status": "selected_by_film_title"})
        seen.add(url)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(filtered)} filtered youtube urls to {OUTPUT_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
