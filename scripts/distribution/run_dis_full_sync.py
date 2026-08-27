#!/usr/bin/env python3
"""Đồng bộ đủ data Distribution: seed → news → screens → region/intent → metrics."""

from __future__ import annotations

import argparse
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
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True, env={**dict(__import__('os').environ), "PYTHONPATH": str(PROJECT_ROOT / "src")})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="Google News lookback")
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--skip-screens", action="store_true", help="Bỏ crawl suất chiếu Moveek")
    parser.add_argument("--chain", choices=("galaxy", "all"), default="galaxy")
    args = parser.parse_args()

    run("seed_films.py")
    if not args.skip_crawl:
        run("crawl_film_news.py", "--days", str(args.days), "--import-db")
    if not args.skip_screens:
        run(
            "crawl_region_screens.py",
            "--all-active",
            "--chain",
            args.chain,
            "--metric",
            "showtimes",
            "--seed-db",
        )
    run("classify_mention_region.py")
    run("classify_mention_intent.py")
    run("recompute_daily_film_metrics.py")
    print("\nDone — refresh Distribution dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
