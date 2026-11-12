"""Runtime configuration."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SCHEMA_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("SCHEMA_DB_PATH", DATA_DIR / "app.db"))
ARTIFACT_DIR = DATA_DIR / "artifacts"

DATA_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
