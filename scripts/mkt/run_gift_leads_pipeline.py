#!/usr/bin/env python3
"""Gift lead gen crawl + classify (Facebook / Threads).

Sets SOCIAL_LISTENING_PROCESS=gift_leads so only process-tagged gift keywords run.

  PYTHONPATH=src python3 scripts/mkt/run_gift_leads_pipeline.py
  PYTHONPATH=src python3 scripts/mkt/run_gift_leads_pipeline.py --skip-crawl
  PYTHONPATH=src python3 scripts/mkt/run_gift_leads_pipeline.py --platforms facebook
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PIPELINE = PROJECT_ROOT / "scripts" / "mkt" / "run_full_pipeline.py"
CLASSIFY = PROJECT_ROOT / "scripts" / "mkt" / "classify" / "classify_gift_leads.py"
SEED = PROJECT_ROOT / "scripts" / "mkt" / "seed_gift_leads_config.py"


def run(cmd: list[str], env: dict[str, str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platforms",
        nargs="+",
        default=["facebook", "threads"],
        choices=["facebook", "threads", "instagram", "tiktok"],
    )
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--days", type=int, default=180)
    args = parser.parse_args()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    env["SOCIAL_LISTENING_PROCESS"] = "gift_leads"
    env["KEYWORD_PROCESS"] = "gift_leads"

    if not args.skip_seed:
        code = run([sys.executable, str(SEED)], env)
        if code != 0:
            return code

    if not args.skip_crawl:
        for platform in args.platforms:
            code = run(
                [sys.executable, str(PIPELINE), platform],
                env,
            )
            if code != 0:
                print(f"pipeline {platform} exited {code}", flush=True)

    classify_cmd = [sys.executable, str(CLASSIFY), "--days", str(args.days)]
    if len(args.platforms) == 1:
        classify_cmd.extend(["--platform", args.platforms[0]])
    return run(classify_cmd, env)


if __name__ == "__main__":
    raise SystemExit(main())
