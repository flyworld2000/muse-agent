import os
import sqlite3
from pathlib import Path

import pytest

from app.migrate_v4 import migrate


@pytest.fixture
def v4_db(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    source = Path(os.environ.get(
        "MUSE_TEST_SEED_DB",
        str(project_root / "data" / "learning.sqlite3"),
    )).expanduser().resolve()
    target = tmp_path / "learning-v4-test.sqlite3"

    if not source.is_file():
        raise FileNotFoundError(f"V3 源数据库不存在：{source}")

    source_uri = f"file:{source.resolve()}?mode=ro"
    src = sqlite3.connect(source_uri, uri=True)
    dst = sqlite3.connect(target)

    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    migrate(target)
    return target
