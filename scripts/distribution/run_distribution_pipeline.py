#!/usr/bin/env python3
"""
Distribution pipeline — crawl MXH theo phim → import Postgres → daily_film_metrics.

Giống MKT (run_full_pipeline + import), nhưng:
  - Keyword config = Settings/DB (listening_queries movie) khi SOCIAL_CONFIG_SOURCE=db
    hoặc data/distribution/films/<slug>.json khi source=file
  - Import qua import_film_mentions.py (link mention_films, không bắt brand)
  - Metrics = daily_film_metrics

Usage:
  PYTHONPATH=src python3 scripts/distribution/run_distribution_pipeline.py \\
    --film 28_years_later_the_bone_temple --platform tiktok

  PYTHONPATH=src python3 scripts/distribution/run_distribution_pipeline.py \\
    --all-active --platform facebook --import-db

  PYTHONPATH=src python3 scripts/distribution/run_distribution_pipeline.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
CATALOG_PATH = PROJECT_ROOT / "data" / "distribution" / "film_catalog.json"
PIPELINE = PROJECT_ROOT / "scripts" / "marketing" / "run_full_pipeline.py"
SEED = PROJECT_ROOT / "scripts" / "distribution" / "seed_films.py"
IMPORT = PROJECT_ROOT / "scripts" / "distribution" / "import_film_mentions.py"
INTENT = PROJECT_ROOT / "scripts" / "distribution" / "classify" / "classify_mention_intent.py"
METRICS = PROJECT_ROOT / "scripts" / "distribution" / "metrics" / "recompute_daily_film_metrics.py"
SCHEMA = PROJECT_ROOT / "sql" / "galaxy_dis_schema.sql"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def env_base() -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    # DIS chromedriver — không sửa runner MKT; set path qua env khi crawl DIS
    dis_driver = PROJECT_ROOT / "runtime" / "bin" / "chromedriver"
    if dis_driver.is_file():
        env.setdefault("CHROMEDRIVER_PATH", str(dis_driver))
    # Distribution Chrome = MKT port + 10
    env.setdefault("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9232")
    env.setdefault("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9233")
    env.setdefault("INSTAGRAM_DEBUGGER_ADDRESS", "127.0.0.1:9234")
    env.setdefault("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9235")
    env.setdefault("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9236")
    return env


def run_py(script: Path, *extra: str, env: dict[str, str] | None = None) -> int:
    cmd = [sys.executable, str(script), *extra]
    log(f"RUN {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env or env_base())
    log(f"EXIT {script.name} code={result.returncode}")
    return int(result.returncode or 0)


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Missing catalog: {CATALOG_PATH}")
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def resolve_keyword_file(film: dict) -> Path | None:
    rel = str(film.get("keyword_file") or f"films/{film['slug']}.json")
    path = PROJECT_ROOT / "data" / "distribution" / rel
    if path.exists():
        return path
    config_source = str(os.getenv("SOCIAL_CONFIG_SOURCE") or "file").strip().lower()
    if config_source == "db":
        return None
    raise FileNotFoundError(f"Keyword config not found: {path}")


def list_films(catalog: dict) -> None:
    films = catalog.get("films") or []
    print(f"{'slug':<40} {'active':<8} {'status':<12} title")
    print("-" * 90)
    for film in films:
        print(
            f"{film.get('slug', ''):<40} "
            f"{str(bool(film.get('active'))):<8} "
            f"{str(film.get('status') or ''):<12} "
            f"{film.get('title') or ''}"
        )


def select_films(catalog: dict, slug: str | None, all_active: bool) -> list[dict]:
    films = catalog.get("films") or []
    if all_active:
        return [f for f in films if f.get("active")]
    if not slug:
        raise SystemExit("Specify --film <slug> or --all-active")
    matched = [f for f in films if f.get("slug") == slug]
    if not matched:
        raise SystemExit(f"Film slug not in catalog: {slug}")
    return matched


def apply_schema_if_needed() -> None:
    code = run_py(SEED, "--apply-schema")
    if code != 0:
        # Fallback: psql
        log(f"seed --apply-schema failed — try: psql -d galaxy_social_listening -f {SCHEMA}")


def crawl_film(
    platform: str,
    keyword_file: Path | None,
    pipeline_flags: list[str],
    dry_run: bool,
    *,
    film_slug: str,
) -> int:
    env = env_base()
    config_source = str(env.get("SOCIAL_CONFIG_SOURCE") or "file").strip().lower()
    env["SOCIAL_LISTENING_PROFILE"] = "dis"
    env["SOCIAL_FILM_SLUG"] = film_slug

    if config_source == "db":
        # Prefer Settings / listening_queries — do not force JSON file override
        env.pop("SOCIAL_KEYWORD_CONFIG_FILE", None)
        env.pop("KEYWORD_CONFIG_FILE", None)
        log(f"CRAWL film={film_slug} platform={platform} source=db")
    else:
        if keyword_file is None:
            raise FileNotFoundError(f"Keyword config missing for film={film_slug}")
        env["SOCIAL_KEYWORD_CONFIG_FILE"] = str(keyword_file)
        env["KEYWORD_CONFIG_FILE"] = str(keyword_file)
        log(f"CRAWL film_config={keyword_file.name} platform={platform} source=file")
        log(f"  SOCIAL_KEYWORD_CONFIG_FILE={keyword_file}")

    # Pipeline always imports via MKT importer — skip that, we use film importer
    flags = list(pipeline_flags)
    if "--skip-sync" not in flags:
        flags.append("--skip-sync")
    if dry_run and "--dry-run" not in flags:
        flags.append("--dry-run")

    cmd = [sys.executable, str(PIPELINE), platform, *flags]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    return int(result.returncode or 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", help="Film slug from film_catalog.json")
    parser.add_argument("--all-active", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--platform",
        default="tiktok",
        choices=["facebook", "instagram", "threads", "tiktok", "youtube", "all"],
        help="Chạy 1 platform mỗi lần cho nhanh. Dùng run_by_platform.py để tách terminal.",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        default=True,
        help="Import mentions + recompute daily_film_metrics (default: on)",
    )
    parser.add_argument(
        "--no-import-db",
        action="store_true",
        help="Crawl only — skip Postgres import",
    )
    parser.add_argument("--seed-only", action="store_true", help="Only seed films/milestones")
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Không gọi seed_films (dùng khi crawl song song — seed 1 lần ở script orchestrator)",
    )
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--skip-format", action="store_true")
    parser.add_argument("--skip-filter", action="store_true")
    parser.add_argument("--only-crawl", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_catalog()

    if args.list:
        list_films(catalog)
        return 0

    do_import = args.import_db and not args.no_import_db and not args.dry_run

    if args.platform == "all":
        log(
            "[!] --platform all sẽ chạy tuần tự rất chậm. "
            "Nên tách terminal: run_by_platform.py tiktok|youtube|facebook|…"
        )

    log("=" * 60)
    log("Distribution pipeline")
    log(f"Platform: {args.platform}")
    log(f"Import DB: {do_import}")
    log("=" * 60)

    # Seed schema + films khi import — tránh gọi lại mỗi platform (race tắt phim)
    if (do_import or args.seed_only) and not args.skip_seed:
        apply_schema_if_needed()
        if args.seed_only:
            return 0

    films = select_films(catalog, args.film, args.all_active)
    pipeline_flags: list[str] = []
    for flag in ("skip_crawl", "skip_format", "skip_filter", "only_crawl", "continue_on_error"):
        if getattr(args, flag):
            pipeline_flags.append(f"--{flag.replace('_', '-')}")

    failed = 0
    for film in films:
        slug = str(film.get("slug") or "")
        keyword_file = resolve_keyword_file(film)
        log(f"----- film={slug} -----")

        if not args.skip_crawl or args.only_crawl:
            code = crawl_film(
                args.platform,
                keyword_file,
                pipeline_flags,
                args.dry_run,
                film_slug=slug,
            )
            if code != 0:
                failed += 1
                log(f"[FAIL] crawl {slug} exit={code}")
                if not args.continue_on_error:
                    return code

        if do_import:
            code = run_py(IMPORT, "--film", slug)
            if code != 0:
                failed += 1
                log(f"[FAIL] import {slug} exit={code}")
                if not args.continue_on_error:
                    return code
            if not args.dry_run:
                code = run_py(INTENT, "--film-slug", slug, "--reclassify")
                if code != 0:
                    failed += 1
                    log(f"[FAIL] intent {slug} exit={code}")
                    if not args.continue_on_error:
                        return code

    if do_import and not args.dry_run:
        # Final metrics pass across all films
        run_py(METRICS)

    if failed:
        log(f"Done with {failed} failure(s).")
        return 1
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
