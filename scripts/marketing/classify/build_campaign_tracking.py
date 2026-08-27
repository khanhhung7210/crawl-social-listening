#!/usr/bin/env python3
"""One-shot: seed campaigns → classify → resolve media_type → metrics.

Run after import_keyword_mentions (or whenever campaign keywords change):

  PYTHONPATH=src python3 scripts/marketing/classify/build_campaign_tracking.py
  PYTHONPATH=src python3 scripts/marketing/classify/build_campaign_tracking.py --brand glx
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _run(module_name: str, argv: list[str] | None = None) -> int:
    path = HERE / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    old = sys.argv[:]
    try:
        sys.argv = [str(path)] + (argv or [])
        spec.loader.exec_module(mod)
        if hasattr(mod, "main"):
            return int(mod.main())
    finally:
        sys.argv = old
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", default="glx")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--skip-media", action="store_true")
    args = parser.parse_args()

    if not args.skip_seed:
        print("== seed_campaigns ==")
        code = _run("seed_campaigns")
        if code != 0:
            return code

    print("== classify_mention_campaigns ==")
    code = _run("classify_mention_campaigns", ["--brand", args.brand])
    if code != 0:
        return code

    if not args.skip_media:
        print("== resolve_mention_media_types ==")
        code = _run("resolve_mention_media_types")
        if code != 0:
            return code

    print("Campaign tracking build done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
