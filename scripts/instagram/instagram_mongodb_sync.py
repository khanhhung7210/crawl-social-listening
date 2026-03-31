from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import film_title
from social_listening.film_paths import platform_processed_dir
from social_listening.mongodb_sync import MongoSyncConfig, sync_json_file
from social_listening.paths import DATA_DIR


def main() -> int:
    config = MongoSyncConfig(
        input_file=Path(os.getenv("INPUT_FILE", str(platform_processed_dir("instagram") / "instagram_keyword_mentions.json"))),
        input_label="instagram_keyword_mentions.json",
        film_title=os.getenv("FILM_TITLE", film_title()),
    )
    return sync_json_file(config)


if __name__ == "__main__":
    raise SystemExit(main())
