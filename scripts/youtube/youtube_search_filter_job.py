from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
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
    accepted_terms = collect_search_terms(keyword_payload)
    if film_title:
        accepted_terms = [film_title, *accepted_terms]
    normalized_variants = {normalize_text(value) for value in accepted_terms if value}
    if not normalized_variants:
        raise RuntimeError("Missing film_title/keywords in shared keyword config")

    filtered: list[dict] = []
    seen: set[str] = set()

    for item in payload:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if normalize_text(keyword) not in normalized_variants:
            continue
        filtered.append(
            {
                **item,
                "filter_keyword": film_title or keyword,
                "filter_status": "selected_by_exact_title_variants",
            }
        )
        seen.add(url)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(filtered)} filtered youtube urls to {OUTPUT_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
