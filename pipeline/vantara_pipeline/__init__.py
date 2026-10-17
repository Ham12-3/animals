"""Vantara 3D reconstruction pipeline."""

from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PIPELINE_DIR.parent
INPUT_DIR = PIPELINE_DIR / "input"
WORK_DIR = PIPELINE_DIR / "work"
ZONES_FILE = REPO_DIR / "zones.json"
