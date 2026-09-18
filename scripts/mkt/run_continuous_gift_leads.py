#!/usr/bin/env python3
"""Continuous Gift Lead Gen crawl: hết keyword → nghỉ → chạy lại.

Treo 1 terminal / platform (giống MKT + DIS). Ctrl+C để dừng.

Process: SOCIAL_LISTENING_PROCESS=gift_leads (chỉ keyword gift, không lẫn brand/phim).
Chrome ports: MKT+20 (9242–9246) để chạy song song với MKT/DIS.
State DB riêng: data/crawl_state_gift.db

Examples:
  # Seed 1 lần (nếu chưa có row listening_queries gift_leads)
  PYTHONPATH=src python3 scripts/mkt/seed_gift_leads_config.py

  # Continuous Facebook
  PYTHONPATH=src python3 scripts/mkt/run_continuous_gift_leads.py --platform facebook

  # Continuous Threads
  PYTHONPATH=src python3 scripts/mkt/run_continuous_gift_leads.py --platform threads --sleep 180

  # Một vòng thử
  PYTHONPATH=src python3 scripts/mkt/run_continuous_gift_leads.py --platform facebook --max-rounds 1
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
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PIPELINE = PROJECT_ROOT / "scripts" / "mkt" / "run_gift_leads_pipeline.py"
SEED = PROJECT_ROOT / "scripts" / "mkt" / "seed_gift_leads_config.py"
LOCK_DIR = PROJECT_ROOT / "logs" / "continuous-locks"

PLATFORMS = ["facebook", "threads", "instagram", "tiktok"]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def env_python() -> dict[str, str]:
    """Gift ports = MKT + 20 so parallel with MKT (922x) and DIS (923x)."""
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "SOCIAL_CONFIG_SOURCE": os.getenv("SOCIAL_CONFIG_SOURCE", "db"),
        "SOCIAL_LISTENING_PROCESS": "gift_leads",
        "KEYWORD_PROCESS": "gift_leads",
        "CRAWL_STATE_DB": os.getenv(
            "CRAWL_STATE_DB",
            str(PROJECT_ROOT / "data" / "crawl_state_gift.db"),
        ),
    }
    env.setdefault("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9242")
    env.setdefault("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9243")
    env.setdefault("INSTAGRAM_DEBUGGER_ADDRESS", "127.0.0.1:9244")
    env.setdefault("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9245")
    env.setdefault("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9246")
    return env


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_lock_pid(text: str) -> int | None:
    for part in (text or "").replace("\n", " ").split():
        if part.startswith("pid="):
            raw = part.split("=", 1)[-1].strip()
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def acquire_lock(platform: str) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_DIR / f"gift-{platform}.lock"
    if lock.exists():
        old = lock.read_text(encoding="utf-8").strip()
        old_pid = _parse_lock_pid(old)
        if old_pid is not None and not _pid_alive(old_pid):
            print(f"[lock] stale lock removed (dead pid={old_pid}): {lock}", flush=True)
            try:
                lock.unlink()
            except OSError:
                pass
        else:
            raise SystemExit(
                f"Already running? Lock: {lock}\n  {old}\n"
                f"  rm {lock} nếu process cũ đã chết"
            )
    lock.write_text(
        f"pid={os.getpid()} started={datetime.now().isoformat()}\n",
        encoding="utf-8",
    )

    def _cleanup() -> None:
        try:
            if lock.exists():
                lock.unlink()
        except OSError:
            pass

    atexit.register(_cleanup)
    return lock


def run_cmd(cmd: list[str]) -> int:
    log("+ " + " ".join(cmd))
    return int(
        subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env_python()).returncode or 0
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        default="facebook",
        choices=PLATFORMS,
        help="1 platform / terminal (default facebook)",
    )
    parser.add_argument("--sleep", type=int, default=180, help="Seconds between rounds")
    parser.add_argument("--max-rounds", type=int, default=0, help="0 = forever")
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip seed even on first round",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Classify lookback days (passed to classify_gift_leads)",
    )
    args = parser.parse_args()

    acquire_lock(args.platform)

    log("=" * 60)
    log(f"Gift Leads continuous: platform={args.platform}")
    log(f"Sleep={args.sleep}s process=gift_leads")
    log("Keyword nguồn: Admin → Gift Leads → Keyword crawl (DB listening_queries)")
    log("Ctrl+C để dừng")
    log("=" * 60)

    if not args.skip_seed:
        log("seed_gift_leads_config once (skip if already exists)")
        seed_code = run_cmd([sys.executable, str(SEED)])
        if seed_code != 0:
            log(f"seed failed code={seed_code} — continue if row already exists")

    round_no = 0
    fail_streak = 0
    alert_dir = PROJECT_ROOT / "logs" / "continuous-alerts"
    try:
        while True:
            round_no += 1
            log(f"===== ROUND {round_no} =====")
            cmd = [
                sys.executable,
                str(PIPELINE),
                "--platforms",
                args.platform,
                "--skip-seed",
                "--days",
                str(args.days),
            ]
            round_code = run_cmd(cmd)
            log(f"Round {round_no} exit={round_code}")

            if args.max_rounds and round_no >= args.max_rounds:
                log(f"Reached --max-rounds={args.max_rounds}")
                return 0

            stop_file = LOCK_DIR / "stop-gift-after-round"
            if stop_file.exists():
                log("Stop file detected — exit after this round")
                return 0

            sleep_s = max(0, int(args.sleep))
            if round_code != 0:
                fail_streak += 1
                sleep_s = min(1800, max(sleep_s, sleep_s * (2 ** min(fail_streak, 4))))
                try:
                    alert_dir.mkdir(parents=True, exist_ok=True)
                    alert_path = alert_dir / f"gift_{args.platform}.alert"
                    alert_path.write_text(
                        f"ts={datetime.now().isoformat()}\n"
                        f"platform={args.platform}\n"
                        f"round={round_no}\n"
                        f"exit={round_code}\n"
                        f"fail_streak={fail_streak}\n"
                        f"next_sleep_s={sleep_s}\n",
                        encoding="utf-8",
                    )
                    log(
                        f"ALERT gift platform={args.platform} exit={round_code} "
                        f"streak={fail_streak} → {alert_path}"
                    )
                except OSError as exc:
                    log(f"ALERT write failed: {exc}")
                log(f"Crawl failed — backoff sleep {sleep_s}s…")
            else:
                fail_streak = 0
                try:
                    alert_path = alert_dir / f"gift_{args.platform}.alert"
                    if alert_path.exists():
                        alert_path.unlink()
                except OSError:
                    pass
                log(f"Sleep {sleep_s}s…")
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        log("Stopped by Ctrl+C")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
