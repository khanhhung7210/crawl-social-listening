#!/usr/bin/env python3
"""Source B only: process existing *_keyword_mentions.json → Postgres (no crawl).

Use after Source A (--only-crawl) saved filtered files, or to retry processing.

Examples:
  PYTHONPATH=src python3 scripts/source_b/run_source_b.py --film galaxy_cinema
  PYTHONPATH=src python3 scripts/source_b/run_source_b.py --file data/facebook/processed/galaxy_cinema/facebook_keyword_mentions.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
IMPORT = PROJECT_ROOT / "scripts" / "shared" / "import_keyword_mentions.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", default="galaxy_cinema")
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()

    cmd = [sys.executable, str(IMPORT)]
    if args.file:
        cmd.extend(["--file", str(args.file)])
    else:
        cmd.extend(["--film", args.film])
        if args.root:
            cmd.extend(["--root", str(args.root)])

    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(PROJECT_ROOT / "src")}
    print(f"[source-b] {' '.join(cmd)}", flush=True)
    return int(__import__("subprocess").call(cmd, cwd=str(PROJECT_ROOT), env=env))


if __name__ == "__main__":
    raise SystemExit(main())
