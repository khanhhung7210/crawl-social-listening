#!/usr/bin/env python3
"""Continuous crawl loop: hết keyword/rạp → nghỉ → chạy lại vòng mới (incremental).

Treo 1 terminal. Ctrl+C để dừng.

Modes:
  facebook|…|google_maps  — 1 platform MXH (terminal riêng)
  news                    — News + App Reviews + classify/metrics (KHÔNG MXH)
  all                     — MXH tất cả + News/App + classify

Với --import-db + news|all: classify CX + topic app + campaign + daily metrics
→ đủ 3 panel Marketing: CX topics, Negative CX, App review topics.

Examples:
  PYTHONPATH=src python3 scripts/marketing/run_continuous.py news --import-db --sleep 300
  PYTHONPATH=src python3 scripts/marketing/run_continuous.py facebook --import-db
  PYTHONPATH=src python3 scripts/marketing/run_continuous.py all --import-db --sleep 300
"""

from __future__ import annotations

import argparse
import atexit
import os
import subprocess
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
PIPELINE = PROJECT_ROOT / "scripts" / "marketing" / "run_full_pipeline.py"
LOCK_DIR = PROJECT_ROOT / "logs" / "continuous-locks"
NEWS_CRAWL = PROJECT_ROOT / "scripts" / "marketing" / "crawl" / "news" / "crawl_news_mentions.py"
NEWS_FILE = PROJECT_ROOT / "data" / "news" / "processed" / "galaxy_cinema" / "news_keyword_mentions.json"
APP_CRAWL = PROJECT_ROOT / "scripts" / "marketing" / "crawl" / "reviews" / "crawl_app_reviews.py"
APP_IMPORT = PROJECT_ROOT / "scripts" / "shared" / "import_app_reviews.py"
APP_FILE = PROJECT_ROOT / "data" / "app-reviews" / "live.json"
IMPORT_MENTIONS = PROJECT_ROOT / "scripts" / "shared" / "import_keyword_mentions.py"
CLASSIFY_TOPICS = PROJECT_ROOT / "scripts" / "marketing" / "classify" / "classify_mention_topics.py"
BUILD_CAMPAIGN = PROJECT_ROOT / "scripts" / "marketing" / "classify" / "build_campaign_tracking.py"
RECOMPUTE_METRICS = PROJECT_ROOT / "scripts" / "marketing" / "metrics" / "recompute_daily_brand_metrics.py"
SCHEMA_SQL = PROJECT_ROOT / "sql" / "galaxy_mkt_schema.sql"

PLATFORMS = [
    "facebook",
    "instagram",
    "threads",
    "tiktok",
    "youtube",
    "google_maps",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def env_python() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        # Windows console defaults to cp1252; Vietnamese/emoji prints crash otherwise
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def acquire_lock(platform: str) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_DIR / f"{platform}.lock"
    if lock.exists():
        old = lock.read_text(encoding="utf-8").strip()
        raise SystemExit(
            f"Already running? Lock exists: {lock}\n"
            f"  contents: {old}\n"
            f"  Xóa lock nếu chắc process cũ đã chết: rm {lock}"
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


def run_py(script: Path, *extra: str) -> int:
    cmd = [sys.executable, str(script), *extra]
    log(f"RUN {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env_python())
    log(f"EXIT {script.name} code={result.returncode}")
    return result.returncode


def run_mxh_round(platform: str, args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(PIPELINE),
        platform,
        "--continue-on-error",
    ]
    if args.only_crawl:
        cmd.append("--only-crawl")
    if args.skip_sync or not args.import_db:
        cmd.append("--skip-sync")

    # Hard ceiling so one stuck platform cannot block continuous indefinitely.
    # Default 4h; override with CONTINUOUS_PLATFORM_TIMEOUT_SECONDS.
    timeout_s = int(os.getenv("CONTINUOUS_PLATFORM_TIMEOUT_SECONDS", "14400") or "14400")
    timeout_s = max(300, timeout_s)

    log(f"MXH start platform={platform} timeout={timeout_s}s")
    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env_python(), timeout=timeout_s)
        log(f"MXH end platform={platform} exit={result.returncode}")
        return result.returncode
    except subprocess.TimeoutExpired:
        log(f"MXH TIMEOUT platform={platform} after {timeout_s}s — continuing next round")
        return 124


def run_news_and_apps(args: argparse.Namespace) -> None:
    """News RSS + App Store/Play — không cần Chrome."""
    log("News + App Reviews start")
    run_py(NEWS_CRAWL, "--days", str(args.news_days))
    if args.import_db and NEWS_FILE.exists():
        run_py(IMPORT_MENTIONS, "--file", str(NEWS_FILE))

    run_py(APP_CRAWL)
    if args.import_db and APP_FILE.exists():
        run_py(APP_IMPORT, "--input", str(APP_FILE))
    log("News + App Reviews done")


def ensure_topics_seeded() -> None:
    """Insert CX/app topics if missing (idempotent)."""
    try:
        from social_listening.pg import get_connection
    except Exception as exc:
        log(f"Skip topic seed check (db import failed): {exc}")
        return

    topic_rows = [
        ("service", "Dịch vụ rạp", "cx", 10),
        ("ticket_price", "Giá vé", "cx", 20),
        ("merch", "Movie Merch", "cx", 30),
        ("booking", "App/Booking", "cx", 40),
        ("facility", "Cơ sở vật chất", "cx", 50),
        ("fnb", "Food & Beverage", "cx", 60),
        ("parking", "Parking", "cx", 70),
        ("tech", "Công nghệ (IMAX/Dolby)", "cx", 80),
        ("app_crash", "App bị crash", "app", 110),
        ("app_booking_error", "Đặt vé lỗi", "app", 120),
        ("app_slow", "Load chậm", "app", 130),
        ("app_payment", "Thanh toán thất bại", "app", 140),
        ("app_ui", "UI khó dùng", "app", 150),
        ("app_login", "Đăng nhập / OTP", "app", 160),
    ]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM topics WHERE topic_group IN ('cx', 'app') AND is_active"
        )
        n = int(cur.fetchone()[0])
        if n > 0:
            log(f"Topics OK: cx/app count={n}")
            return

        log("No CX/app topics — seeding via SQL INSERT…")
        cur.executemany(
            """
            INSERT INTO topics (topic_slug, topic_name, topic_group, sort_order)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (topic_slug) DO NOTHING
            """,
            topic_rows,
        )
        conn.commit()
        cur.execute(
            "SELECT COUNT(*) FROM topics WHERE topic_group IN ('cx', 'app') AND is_active"
        )
        n2 = int(cur.fetchone()[0])
        log(f"Topics seeded: cx/app count={n2}")
        if n2 == 0:
            log(
                "WARNING: seed still empty — chạy tay: "
                f'psql -h localhost -U root -d galaxy_social_listening -f "{SCHEMA_SQL}"'
            )


def run_enrich_for_ui(_args: argparse.Namespace | None = None) -> None:
    """Fill Marketing panels: CX topics, Negative CX, App review topics."""
    log("Enrich UI metrics start")
    ensure_topics_seeded()
    code = run_py(CLASSIFY_TOPICS, "--brand", "glx")
    if code != 0:
        log("classify_mention_topics failed — CX panels may stay empty")
    run_py(APP_IMPORT, "--reclassify-only")
    run_py(BUILD_CAMPAIGN, "--brand", "glx")
    run_py(RECOMPUTE_METRICS)
    log("Enrich UI metrics done")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "platform",
        choices=PLATFORMS + ["all", "news"],
        help="Loop target: 1 MXH platform | news (News+App+CX, no MXH) | all",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        default=120,
        help="Seconds between rounds (default 120; gợi ý news/all=300)",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        help="Import Postgres after each round",
    )
    parser.add_argument("--skip-sync", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--only-crawl", action="store_true", help="Only MXH crawl stages")
    parser.add_argument("--max-rounds", type=int, default=0, help="0 = forever")
    parser.add_argument(
        "--news-days",
        type=int,
        default=int(os.getenv("CRAWL_LOOKBACK_DAYS", "14") or "14"),
        help="Google News lookback days (default CRAWL_LOOKBACK_DAYS or 14)",
    )
    parser.add_argument(
        "--skip-news-apps",
        action="store_true",
        help="Skip News + App Reviews even when platform=all|news",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Force classify CX + app topics + campaign/metrics each round "
        "(default: on for platform=all|news with --import-db)",
    )
    args = parser.parse_args()

    acquire_lock(args.platform)

    news_only = args.platform == "news"
    include_extras = (
        args.platform in ("all", "news")
        and not args.skip_news_apps
        and not args.only_crawl
    )
    do_enrich = (
        args.import_db
        and not args.only_crawl
        and (args.platform in ("all", "news") or args.enrich)
    )
    run_mxh = not news_only

    log("=" * 60)
    log(f"Continuous loop: {args.platform}")
    log(f"Sleep between rounds: {args.sleep}s")
    log(f"Import DB each round: {args.import_db}")
    log(f"MXH crawl each round: {run_mxh}")
    log(f"News + App Reviews each round: {include_extras}")
    log(f"Classify CX + app topics + metrics each round: {do_enrich}")
    log("Ctrl+C để dừng")
    log("=" * 60)

    round_no = 0
    try:
        while True:
            round_no += 1
            log(f"===== ROUND {round_no} =====")
            if include_extras:
                run_news_and_apps(args)
            if do_enrich:
                run_enrich_for_ui(args)
            if run_mxh:
                run_mxh_round(args.platform, args)
                if do_enrich:
                    run_enrich_for_ui(args)

            if args.max_rounds and round_no >= args.max_rounds:
                log(f"Reached --max-rounds={args.max_rounds}, stopping")
                return 0

            log(f"Sleep {args.sleep}s before next round…")
            time.sleep(max(0, args.sleep))
    except KeyboardInterrupt:
        log("Stopped by Ctrl+C")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
