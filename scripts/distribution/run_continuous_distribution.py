#!/usr/bin/env python3
"""Continuous Distribution crawl: hết keyword phim → nghỉ → chạy lại.

Treo 1 terminal / platform. Ctrl+C để dừng.

Examples:
  PYTHONPATH=src python3 scripts/distribution/run_continuous_distribution.py \\
    --film 28_years_later_the_bone_temple --platform tiktok --import-db

  PYTHONPATH=src python3 scripts/distribution/run_continuous_distribution.py \\
    --all-active --platform facebook --import-db --sleep 180
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys
import time
from datetime import datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PIPELINE = PROJECT_ROOT / "scripts" / "distribution" / "run_distribution_pipeline.py"
SEED = PROJECT_ROOT / "scripts" / "distribution" / "seed_films.py"
LOCK_DIR = PROJECT_ROOT / "logs" / "continuous-locks"
CLASSIFY = PROJECT_ROOT / "scripts" / "distribution" / "classify" / "classify_mention_intent.py"
METRICS = PROJECT_ROOT / "scripts" / "distribution" / "metrics" / "recompute_daily_film_metrics.py"
NEWS_SYNC = PROJECT_ROOT / "scripts" / "distribution" / "run_dis_full_sync.py"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def env_python(platform: str | None = None) -> dict[str, str]:
    """Inject DIS debugger ports (MKT+10) so runners không đụng Chrome MKT."""
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "SOCIAL_CONFIG_SOURCE": os.getenv("SOCIAL_CONFIG_SOURCE", "db"),
    }
    # Always set all DIS ports; runners pick their own env key
    env.setdefault("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9232")
    env.setdefault("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9233")
    env.setdefault("INSTAGRAM_DEBUGGER_ADDRESS", "127.0.0.1:9234")
    env.setdefault("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9235")
    env.setdefault("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9236")
    return env


def acquire_lock(name: str) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_DIR / f"dis-{name}.lock"
    if lock.exists():
        old = lock.read_text(encoding="utf-8").strip()
        raise SystemExit(
            f"Already running? Lock: {lock}\n  {old}\n  rm {lock} nếu process cũ đã chết"
        )
    lock.write_text(f"pid={os.getpid()} started={datetime.now().isoformat()}\n", encoding="utf-8")

    def _cleanup() -> None:
        try:
            if lock.exists():
                lock.unlink()
        except OSError:
            pass

    atexit.register(_cleanup)
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", default="", help="One film slug")
    parser.add_argument("--all-active", action="store_true")
    parser.add_argument(
        "--platform",
        default="tiktok",
        choices=["facebook", "instagram", "threads", "tiktok", "youtube", "all"],
    )
    parser.add_argument("--sleep", type=int, default=180)
    parser.add_argument("--import-db", action="store_true", default=True)
    parser.add_argument("--no-import-db", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--skip-seed", action="store_true", help="Skip seed_films each round")
    args = parser.parse_args()

    if not args.film and not args.all_active:
        raise SystemExit("Need --film <slug> or --all-active")
    if args.platform == "all":
        raise SystemExit(
            "Đừng dùng --platform all cho continuous. "
            "Treo 1 terminal / platform cho nhanh, ví dụ:\n"
            "  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py tiktok --all-active --continuous\n"
            "  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py youtube --all-active --continuous"
        )

    # Lock theo platform để chạy song song nhiều terminal
    lock_name = f"{args.film or 'all'}-{args.platform}"
    acquire_lock(lock_name)

    do_import = args.import_db and not args.no_import_db
    log("=" * 60)
    log(f"Distribution continuous: film={args.film or 'ALL_ACTIVE'} platform={args.platform}")
    log(f"Sleep={args.sleep}s import_db={do_import}")
    log("Ctrl+C để dừng")
    log("=" * 60)

    # Seed 1 lần đầu — round sau --skip-seed để tránh deadlock khi nhiều platform song song.
    seed_once = do_import and not args.skip_seed
    if seed_once:
        log("seed_films once before continuous rounds")
        import subprocess as _sp

        seed_code = int(
            _sp.run(
                [sys.executable, str(SEED), "--apply-schema"],
                cwd=str(PROJECT_ROOT),
                env=env_python(args.platform),
            ).returncode
            or 0
        )
        if seed_code != 0:
            log(f"seed_films failed code={seed_code} — rounds continue with --skip-seed")
        else:
            log("seed_films OK")

    round_no = 0
    try:
        while True:
            round_no += 1
            log(f"===== ROUND {round_no} =====")
            cmd = [
                sys.executable,
                str(PIPELINE),
                "--platform",
                args.platform,
                "--continue-on-error",
            ]
            if args.all_active:
                cmd.append("--all-active")
            else:
                cmd.extend(["--film", args.film])
            if do_import:
                cmd.append("--import-db")
            else:
                cmd.append("--no-import-db")
            # Seed đã chạy 1 lần đầu (hoặc user --skip-seed); tránh seed song song mỗi round.
            cmd.append("--skip-seed")

            import subprocess

            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env_python(args.platform),
            )
            log(f"Round {round_no} exit={result.returncode}")

            if do_import:
                # Intent trên comment (WOM / khen-chê) + metrics lại sau classify
                classify_cmd = [sys.executable, str(CLASSIFY), "--reclassify"]
                if args.film and not args.all_active:
                    classify_cmd.extend(["--film-slug", args.film])
                code = subprocess.run(
                    classify_cmd,
                    cwd=str(PROJECT_ROOT),
                    env=env_python(args.platform),
                ).returncode
                log(f"  post-step classify_mention_intent.py exit={code}")
                code = subprocess.run(
                    [sys.executable, str(METRICS)],
                    cwd=str(PROJECT_ROOT),
                    env=env_python(args.platform),
                ).returncode
                log(f"  post-step recompute_daily_film_metrics.py exit={code}")

            if args.max_rounds and round_no >= args.max_rounds:
                log(f"Reached --max-rounds={args.max_rounds}")
                return 0

            stop_file = LOCK_DIR / "stop-after-round"
            if stop_file.exists():
                log("Stop file detected — exit after this round")
                return 0

            log(f"Sleep {args.sleep}s…")
            time.sleep(max(0, args.sleep))
    except KeyboardInterrupt:
        log("Stopped by Ctrl+C")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
