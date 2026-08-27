#!/usr/bin/env python3
"""Crawl + classify đủ data cho Heatmap Buzz theo Khu Vực (Screens + Buzz region + Intent).

Pipeline:
  1) crawl_region_screens.py  → film_region_screens.json (+ optional seed DB)
  2) classify_mention_region.py → mentions.metadata.dis_region
  3) classify_mention_intent.py → mentions.intent (want_to_see, …)
  4) recompute_daily_film_metrics.py

Buzz theo vùng vẫn lấy từ mentions đã crawl (MXH/news); script này không thay pipeline social.

Ví dụ:
  PYTHONPATH=src python3 scripts/distribution/crawl/crawl_heatmap_data.py --all-active --seed-db
  PYTHONPATH=src python3 scripts/distribution/crawl/crawl_heatmap_data.py --film the_odyssey --skip-screens
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
DIS = PROJECT_ROOT / "scripts" / "distribution"


def _dis_script(name: str) -> Path:
    for folder in ("", "crawl", "classify", "metrics"):
        path = (DIS / folder / name) if folder else (DIS / name)
        if path.is_file():
            return path
    raise FileNotFoundError(f"Missing distribution script: {name}")


def run(script: str, *args: str) -> None:
    cmd = [sys.executable, str(_dis_script(script)), *args]
    print(f"\n>>> {' '.join(cmd)}")
    env = {**dict(os.environ), "PYTHONPATH": str(PROJECT_ROOT / "src")}
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", default="", help="Film slug")
    parser.add_argument("--all-active", action="store_true")
    parser.add_argument("--date", default="", help="Ngày suất chiếu YYYY-MM-DD")
    parser.add_argument("--chain", choices=("galaxy", "all"), default="galaxy")
    parser.add_argument("--metric", choices=("showtimes", "cinemas"), default="showtimes")
    parser.add_argument("--seed-db", action="store_true", help="Seed region_screens vào films.metadata")
    parser.add_argument("--skip-screens", action="store_true")
    parser.add_argument("--skip-region", action="store_true")
    parser.add_argument("--skip-intent", action="store_true")
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    film_args: list[str] = []
    if args.film:
        film_args = ["--film", args.film]
    elif args.all_active:
        film_args = ["--all-active"]
    else:
        film_args = ["--all-active"]

    if not args.skip_screens:
        screen_args = [
            *film_args,
            "--chain",
            args.chain,
            "--metric",
            args.metric,
        ]
        if args.date:
            screen_args += ["--date", args.date]
        if args.seed_db:
            screen_args.append("--seed-db")
        run("crawl_region_screens.py", *screen_args)
    elif args.seed_db:
        run("seed_films.py")

    if not args.skip_region:
        region_args: list[str] = []
        if args.film:
            region_args = ["--film-slug", args.film]
        run("classify_mention_region.py", *region_args)

    if not args.skip_intent:
        intent_args: list[str] = []
        if args.film:
            intent_args = ["--film-slug", args.film]
        run("classify_mention_intent.py", *intent_args)

    if not args.skip_metrics:
        run("recompute_daily_film_metrics.py")

    print("\nDone — refresh Distribution → Heatmap Buzz theo Khu Vực.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
