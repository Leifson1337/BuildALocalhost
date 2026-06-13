"""Universal AI Stack Builder — installer package.

The installer turns (detected/simulated hardware) + (profile) + (catalogs) into a
validated, rendered deployment. Decision logic is kept pure and data-driven so it can be
tested without a GPU. See docs/STRUCTURE.md.
"""
from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

# Repo root = parent of this package directory.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
CATALOGS_DIR: Path = REPO_ROOT / "catalogs"
PROFILES_DIR: Path = REPO_ROOT / "profiles"
TEMPLATES_DIR: Path = REPO_ROOT / "templates"
CONFIGS_DIR: Path = REPO_ROOT / "configs"
DEFAULT_OUTPUT_DIR: Path = REPO_ROOT / "output"
