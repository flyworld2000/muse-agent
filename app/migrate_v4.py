"""Muse Agent V3 -> V4 education stages and subjects migration."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "learning.sqlite3"
DB_PATH = Path(os.environ.get("LEARNING_DB_PATH", str(DEFAULT_DB)))
TARGET_VERSION = 4

STAGES = (
    ("primary", "小学", 1),
    ("senior_high", "高中", 2),
    ("university", "大学", 3),
)

NEW_SUBJECTS = (
    ("physics", "物理", 6),
    ("chemistry", "化学", 7),
    ("biology", "生物", 8),
    ("geography", "地理", 9),
    ("history", "历史", 10),
    ("politics", "政治", 11),
    ("technology", "技术", 12),
    ("university_english", "大学英语", 13),
)

STAGE_SUBJECTS = {
    "primary": ("chinese", "mathematics", "english", "science"),
    "senior_high": (
        "chinese", "mathematics", "english", "physics", "chemistry",
        "biology", "geography", "history", "politics", "technology",
    ),
    "university": ("university_english",),
}

SCHEMA = (
    """
    CREATE TABLE education_stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE education_stage_subjects (
        education_stage_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (education_stage_id, subject_id),
        FOREIGN KEY (education_stage_id) REFERENCES education_stages(id)
            ON DELETE CASCADE,
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE RESTRICT
    )
    """,
)

INDEXES = (
    """
    CREATE INDEX idx_stage_subjects_stage_active_order
    ON education_stage_subjects(
        education_stage_id, is_active, sort_order, subject_id
    )
    """,
    """
    CREATE INDEX idx_stage_subjects_subject
    ON education_stage_subjects(subject_id, education_stage_id)
    """,
)


def _check_existing_code(
    conn: sqlite3.Connection,
    table: str,
    code: str,
    expected_name: str,
) -> None:
    row = conn.execute(
        f"SELECT name FROM {table} WHERE code = ?", (code,)
    ).fetchone()
    if row is not None and row[0] != expected_name:
        raise RuntimeError(
            f"{table} 编码冲突：{code} 已对应名称 {row[0]!r}，"
            f"预期名称为 {expected_name!r}"
        )


def migrate(db_path: str | Path = DB_PATH) -> None:
    path = Path(db_path)

    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"数据库不存在或为空：{path}")

    conn = sqlite3.connect(path, timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")

    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()

        if row is None:
            raise RuntimeError("数据库缺少 schema_version，停止迁移")

        current_version = int(row[0])

        if current_version > TARGET_VERSION:
            raise RuntimeError(
                f"数据库版本 {current_version} 高于脚本版本 {TARGET_VERSION}"
            )

        if current_version == TARGET_VERSION:
            print("数据库已经是 V4，无需重复迁移")
            return

        if current_version != 3:
            raise RuntimeError(
                f"只支持从 V3 升级到 V4，当前版本为 {current_version}"
            )

        # 迁移前检查编码冲突，避免静默覆盖已有数据。
        for code, name, _ in NEW_SUBJECTS:
            _check_existing_code(conn, "subjects", code, name)

        conn.execute("BEGIN IMMEDIATE")

        try:
            for statement in SCHEMA:
                conn.execute(statement)

            for statement in INDEXES:
                conn.execute(statement)

            for code, name, order in NEW_SUBJECTS:
                conn.execute(
                    """
                    INSERT INTO subjects(code, name, sort_order, is_active)
                    SELECT ?, ?, ?, 1
                    WHERE NOT EXISTS (
                        SELECT 1 FROM subjects WHERE code = ?
                    )
                    """,
                    (code, name, order, code),
                )

            for code, name, order in STAGES:
                conn.execute(
                    """
                    INSERT INTO education_stages(code, name, sort_order)
                    VALUES (?, ?, ?)
                    """,
                    (code, name, order),
                )

            stage_ids = {
                code: row[0]
                for code, row in (
                    (
                        code,
                        conn.execute(
                            "SELECT id FROM education_stages WHERE code = ?",
                            (code,),
                        ).fetchone(),
                    )
                    for code, _, _ in STAGES
                )
            }

            subject_ids = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT code, id FROM subjects"
                ).fetchall()
            }

            for stage_code, subject_codes in STAGE_SUBJECTS.items():
                for order, subject_code in enumerate(subject_codes, start=1):
                    conn.execute(
                        """
                        INSERT INTO education_stage_subjects(
                            education_stage_id, subject_id, sort_order
                        )
                        VALUES (?, ?, ?)
                        """,
                        (
                            stage_ids[stage_code],
                            subject_ids[subject_code],
                            order,
                        ),
                    )

            conn.execute(
                """
                UPDATE schema_meta
                SET value = ?
                WHERE key = 'schema_version'
                """,
                (str(TARGET_VERSION),),
            )

            violations = conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violations:
                raise RuntimeError(
                    f"外键检查失败，迁移将回滚：{violations}"
                )

            integrity = conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(
                    f"数据库完整性检查失败，迁移将回滚：{integrity}"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        stage_count = conn.execute(
            "SELECT COUNT(*) FROM education_stages"
        ).fetchone()[0]
        subject_count = conn.execute(
            "SELECT COUNT(*) FROM subjects"
        ).fetchone()[0]
        relation_count = conn.execute(
            "SELECT COUNT(*) FROM education_stage_subjects"
        ).fetchone()[0]

        print("V4 数据库迁移成功")
        print("数据库版本:", TARGET_VERSION)
        print("学段数量:", stage_count)
        print("学科总数:", subject_count)
        print("学段学科关联数量:", relation_count)
        print("数据库完整性检查:", integrity)
        print("外键检查通过")

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
