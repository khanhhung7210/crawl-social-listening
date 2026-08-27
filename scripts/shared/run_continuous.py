#!/usr/bin/env python3
"""Compatibility shim — moved to scripts/marketing/run_continuous.py."""
import runpy
from pathlib import Path

runpy.run_path(
    str((Path(__file__).resolve().parent / "../marketing/run_continuous.py").resolve()),
    run_name="__main__",
)
