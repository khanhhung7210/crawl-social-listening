#!/usr/bin/env python3
"""
Small real-crawler smoke test for freshness / coverage fixes.

Requires Chrome remote-debugging sessions already logged in:
  Threads  : 9222
  TikTok   : 9223
  Instagram: 9224
  Facebook : 9226

Usage (from social-listening root):
  PYTHONPATH=src \\
  CRAWL_LOOKBACK_DAYS=14 \\
  CRAWL_DISCOVERY_LIMIT=20 \\
  CRAWL_FINAL_LIMIT=5 \\
  FACEBOOK_KEYWORD_LIMIT=1 \\
  FACEBOOK_KEYWORD_RUNTIME_SECONDS=90 \\
  python scripts/shared/smoke_crawl_coverage.py [--platform facebook|tiktok|threads|instagram|all]

Success criteria (per platform):
  - Runner exits 0
  - Logs include keyword stats with discovered/new/stale/detail_success
  - Fresh coverage (if any) has content timestamps within lookback
  - Stale results are not counted as detail_success / coverage
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


ROOT = _project_root()
PLATFORMS = {
    "facebook": {
        "port": 9226,
        "script": "scripts/marketing/crawl/facebook/facebook_raw_runner.py",
    },
    "tiktok": {
        "port": 9223,
        "script": "scripts/marketing/crawl/tiktok/tiktok_search_runner.py",
    },
    "threads": {
        "port": 9222,
        "script": "scripts/marketing/crawl/threads/threads_crawl_runner.py",
    },
    "instagram": {
        "port": 9224,
        "script": "scripts/marketing/crawl/instagram/instagram_search_runner.py",
    },
}


def chrome_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_platform(name: str) -> int:
    cfg = PLATFORMS[name]
    print(f"\n=== SMOKE {name} @ :{cfg['port']} ===")
    if not chrome_ready(cfg["port"]):
        print(f"[SKIP] Chrome debugger not ready on {cfg['port']}")
        return 2

    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONUTF8": "1",
        "CRAWL_LOOKBACK_DAYS": os.getenv("CRAWL_LOOKBACK_DAYS", "14"),
        "CRAWL_DISCOVERY_LIMIT": os.getenv("CRAWL_DISCOVERY_LIMIT", "20"),
        "CRAWL_FINAL_LIMIT": os.getenv("CRAWL_FINAL_LIMIT", "5"),
        "FACEBOOK_KEYWORD_LIMIT": os.getenv("FACEBOOK_KEYWORD_LIMIT", "1"),
        "FACEBOOK_MAX_POSTS_PER_KEYWORD": os.getenv("FACEBOOK_MAX_POSTS_PER_KEYWORD", "5"),
        "FACEBOOK_KEYWORD_RUNTIME_SECONDS": os.getenv("FACEBOOK_KEYWORD_RUNTIME_SECONDS", "120"),
        "TIKTOK_MAX_VIDEOS": os.getenv("TIKTOK_MAX_VIDEOS", "5"),
        "TIKTOK_KEYWORD_RUNTIME_SECONDS": os.getenv("TIKTOK_KEYWORD_RUNTIME_SECONDS", "120"),
        "THREADS_MAX_URLS_PER_KEYWORD": os.getenv("THREADS_MAX_URLS_PER_KEYWORD", "5"),
        "THREADS_KEYWORD_RUNTIME_SECONDS": os.getenv("THREADS_KEYWORD_RUNTIME_SECONDS", "120"),
        "INSTAGRAM_MAX_POSTS": os.getenv("INSTAGRAM_MAX_POSTS", "5"),
        "INSTAGRAM_KEYWORD_RUNTIME_SECONDS": os.getenv("INSTAGRAM_KEYWORD_RUNTIME_SECONDS", "120"),
    }
    cmd = [sys.executable, str(ROOT / cfg["script"])]
    print(f"[{datetime.now().isoformat(timespec='seconds')}] RUN {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] EXIT {name} code={result.returncode}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        default="all",
        choices=["all", *PLATFORMS.keys()],
    )
    args = parser.parse_args()
    names = list(PLATFORMS) if args.platform == "all" else [args.platform]

    codes = {}
    for name in names:
        codes[name] = run_platform(name)

    print("\n=== SMOKE SUMMARY ===")
    for name, code in codes.items():
        label = {0: "OK", 2: "SKIPPED(no chrome)"}.get(code, f"FAIL({code})")
        print(f"  {name:10} {label}")

    # Skip (2) is not success; hard fail only on non-zero non-skip
    if any(code not in (0, 2) for code in codes.values()):
        return 1
    if all(code == 2 for code in codes.values()):
        print("All platforms skipped — start Chrome debug sessions and re-run.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
