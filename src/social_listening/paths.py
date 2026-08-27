from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    current = Path(start).resolve() if start else Path(__file__).resolve()
    if current.is_file():
        current = current.parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {start or __file__}")


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def marketing_script(name: str) -> Path:
    """Resolve a marketing script after the crawl/classify/metrics split."""
    root = SCRIPTS_DIR / "marketing"
    for folder in ("metrics", "classify", ""):
        path = (root / folder / name) if folder else (root / name)
        if path.is_file():
            return path
    raise FileNotFoundError(f"Marketing script not found: {name}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
