from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import film_title
from social_listening.mongodb_sync import MongoSyncConfig, sync_json_file
from social_listening.film_paths import platform_processed_dir


def main() -> int:
    default_input = platform_processed_dir("threads") / "threads_grouped_parsed.json"
    input_file = Path(os.getenv("INPUT_FILE", str(default_input)))
    config = MongoSyncConfig(
        input_file=input_file,
        input_label=input_file.name,
        film_title=os.getenv("FILM_TITLE", film_title()),
    )
    return sync_json_file(config)


if __name__ == "__main__":
    raise SystemExit(main())
