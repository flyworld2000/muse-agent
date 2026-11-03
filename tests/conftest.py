import importlib
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app.learning_db import initialize_database
from app.migrate_v4 import migrate as migrate_v4


@pytest.fixture
def v4_db(tmp_path, monkeypatch):
    target = tmp_path / "learning-v4-test.sqlite3"

    monkeypatch.setenv("LEARNING_DB_PATH", str(target))

    initialize_database(target)

    migrate_v2 = importlib.import_module("migrate_v2")
    importlib.reload(migrate_v2)
    migrate_v2.migrate()

    migrate_v3 = importlib.import_module("migrate_v3")
    importlib.reload(migrate_v3)
    migrate_v3.migrate()

    migrate_v4(target)

    return target
