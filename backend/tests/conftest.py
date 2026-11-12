import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

_TMP = Path(__file__).resolve().parent / "_tmp"
_TMP.mkdir(exist_ok=True)
_DB = _TMP / "test.db"
if _DB.exists():
    _DB.unlink()
os.environ["SCHEMA_DATA_DIR"] = str(_TMP)
os.environ["SCHEMA_DB_PATH"] = str(_DB)

from app.config import ARTIFACT_DIR  # noqa: E402
from app import storage  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database():
    storage.init_db()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
