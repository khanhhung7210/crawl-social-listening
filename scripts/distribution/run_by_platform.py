#!/usr/bin/env python3
"""Crawl Distribution theo TỪNG platform — 1 Chrome / 1 terminal.

Port DIS = MKT + 10 (tránh trùng khi chạy song song Marketing):

  threads    MKT 9222 → DIS 9232
  tiktok     MKT 9223 → DIS 9233
  instagram  MKT 9224 → DIS 9234
  youtube    MKT 9225 → DIS 9235
  facebook   MKT 9226 → DIS 9236

Examples:
  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py --list
  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py tiktok --chrome-only
  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py tiktok --all-active --import-db --continue-on-error
  PYTHONPATH=src python3 scripts/distribution/run_by_platform.py youtube --all-active --continuous --sleep 180
"""

from __future__ import annotations

import argparse
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
PIPELINE = PROJECT_ROOT / "scripts" / "distribution" / "run_distribution_pipeline.py"
CONTINUOUS = PROJECT_ROOT / "scripts" / "distribution" / "run_continuous_distribution.py"
CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# DIS ports = MKT+10. Profile riêng dis-* để không đụng user-data-dir MKT.
PLATFORMS: dict[str, dict[str, str | int]] = {
    "threads": {"port": 9232, "profile": "dis-threads", "env_key": "THREADS_DEBUGGER_ADDRESS"},
    "tiktok": {"port": 9233, "profile": "dis-tiktok", "env_key": "TIKTOK_DEBUGGER_ADDRESS"},
    "instagram": {"port": 9234, "profile": "dis-instagram", "env_key": "INSTAGRAM_DEBUGGER_ADDRESS"},
    "youtube": {"port": 9235, "profile": "dis-youtube", "env_key": "YOUTUBE_DEBUGGER_ADDRESS"},
    "facebook": {"port": 9236, "profile": "dis-facebook", "env_key": "FACEBOOK_DEBUGGER_ADDRESS"},
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def debugger_url(platform: str) -> str:
    return f"127.0.0.1:{int(PLATFORMS[platform]['port'])}"


def env_base(platform: str | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    # DIS chromedriver (không đụng runner MKT) — ưu tiên binary sạch trong runtime/bin
    dis_driver = PROJECT_ROOT / "runtime" / "bin" / "chromedriver"
    if dis_driver.is_file():
        env["CHROMEDRIVER_PATH"] = str(dis_driver)
    # Always export all DIS ports; runners read their own key
    env["THREADS_DEBUGGER_ADDRESS"] = "127.0.0.1:9232"
    env["TIKTOK_DEBUGGER_ADDRESS"] = "127.0.0.1:9233"
    env["INSTAGRAM_DEBUGGER_ADDRESS"] = "127.0.0.1:9234"
    env["YOUTUBE_DEBUGGER_ADDRESS"] = "127.0.0.1:9235"
    env["FACEBOOK_DEBUGGER_ADDRESS"] = "127.0.0.1:9236"
    if platform and platform in PLATFORMS:
        env[str(PLATFORMS[platform]["env_key"])] = debugger_url(platform)
    return env


def profile_dir(platform: str) -> Path:
    path = PROJECT_ROOT / "runtime" / "chrome" / str(PLATFORMS[platform]["profile"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def chrome_listening(platform: str) -> bool:
    port = int(PLATFORMS[platform]["port"])
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_chrome(platform: str) -> None:
    if not CHROME_BIN.exists():
        raise SystemExit(f"Không tìm thấy Chrome: {CHROME_BIN}")

    port = int(PLATFORMS[platform]["port"])
    user_dir = profile_dir(platform)
    log_file = Path(f"/tmp/chrome-dis-{platform}-{port}.log")

    if chrome_listening(platform):
        log(f"Chrome DIS {platform} đã sẵn sàng tại :{port}")
        return

    cmd = [
        str(CHROME_BIN),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    log(f"Mở Chrome DIS {platform} port={port} profile={user_dir}")
    with log_file.open("w", encoding="utf-8") as fh:
        subprocess.Popen(cmd, stdout=fh, stderr=fh, start_new_session=True)

    for _ in range(20):
        time.sleep(0.5)
        if chrome_listening(platform):
            log(f"Chrome DIS {platform} OK → http://127.0.0.1:{port}")
            return
    raise SystemExit(f"Chrome DIS {platform} không lắng nghe :{port}. Log: {log_file}")


def print_matrix() -> None:
    print("Platform   DIS port  MKT port  profile")
    print("-" * 72)
    for name, meta in PLATFORMS.items():
        port = int(meta["port"])
        status = "UP" if chrome_listening(name) else "down"
        print(f"{name:<10} {port:<9} {port - 10:<9} {profile_dir(name)}  [{status}]")
    print("\nDIS = MKT+10 — chạy song song Marketing không trùng port/profile.")


def run_once(platform: str, args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(PIPELINE), "--platform", platform]
    if args.all_active:
        cmd.append("--all-active")
    elif args.film:
        cmd.extend(["--film", args.film])
    else:
        raise SystemExit("Cần --film <slug> hoặc --all-active")
    cmd.append("--import-db" if args.import_db and not args.no_import_db else "--no-import-db")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.skip_crawl:
        cmd.append("--skip-crawl")
    log(f"RUN {' '.join(cmd)}")
    return int(subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env_base(platform)).returncode or 0)


def run_continuous(platform: str, args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(CONTINUOUS),
        "--platform",
        platform,
        "--sleep",
        str(args.sleep),
    ]
    if args.all_active:
        cmd.append("--all-active")
    else:
        cmd.extend(["--film", args.film])
    cmd.append("--import-db" if args.import_db and not args.no_import_db else "--no-import-db")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.max_rounds:
        cmd.extend(["--max-rounds", str(args.max_rounds)])
    log(f"CONTINUOUS {' '.join(cmd)}")
    return int(subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env_base(platform)).returncode or 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platform", nargs="?", choices=[*PLATFORMS.keys(), "status"])
    parser.add_argument("--film", default="")
    parser.add_argument("--all-active", action="store_true")
    parser.add_argument("--chrome-only", action="store_true")
    parser.add_argument("--no-chrome", action="store_true")
    parser.add_argument("--import-db", action="store_true", default=True)
    parser.add_argument("--no-import-db", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--sleep", type=int, default=180)
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--list", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list or args.platform in (None, "status"):
        print_matrix()
        return 0

    platform = str(args.platform)
    log("=" * 60)
    log(f"DIS platform={platform} debugger={debugger_url(platform)} (MKT={int(PLATFORMS[platform]['port']) - 10})")
    log("=" * 60)

    if not args.no_chrome:
        start_chrome(platform)
    if args.chrome_only:
        log(f"Chrome DIS {platform} sẵn sàng — login rồi chạy crawl.")
        return 0
    if args.continuous:
        return run_continuous(platform, args)
    return run_once(platform, args)


if __name__ == "__main__":
    raise SystemExit(main())
