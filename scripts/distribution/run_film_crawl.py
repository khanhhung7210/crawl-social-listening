#!/usr/bin/env python3
"""Deprecated alias — dùng run_distribution_pipeline.py."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("run_distribution_pipeline.py")), run_name="__main__")
