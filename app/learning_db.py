"""Muse Agent learning database.

独立于现有任务 JSON 系统。
仅使用 Python 标准库 sqlite3。
正式数据库路径：/data/learning.sqlite3
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(
    os.environ.get("LEARNING_DB_PATH", "/data/learning.sqlite3")
)
SCHEMA_VERSION = 1
_UNSET = object()  # 区分参数未提供与主动传入 None

SUBJECTS = (
    ("english", "英语", 1),
    ("chinese", "语文", 2),
    ("mathematics", "数学", 3),
    ("science", "科学", 4),
    ("morality_law", "道德与法治", 5),
)


V3_SCHEMA_VERSION = 3
CURRENT_SCHEMA_VERSION = 4


def generate_id() -> str:
    """生成 V3 TEXT 主键。"""
    return str(uuid.uuid4())


def require_schema_version(
    conn: sqlite3.Connection,
    expected: int = CURRENT_SCHEMA_VERSION,
) -> None:
    """验证数据库版本，不自动创建或升级数据库。"""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            raise RuntimeError("数据库缺少 schema_meta 表") from exc
        raise

    if row is None:
        raise RuntimeError("数据库缺少 schema_version")

    try:
        actual = int(row["value"])
    except (TypeError, ValueError):
        raise RuntimeError("数据库版本号无效") from None

    if actual != expected:
        raise RuntimeError(
            f"数据库版本不匹配：要求 V{expected}，实际 V{actual}"
        )


def encode_json(value: object) -> str:
    """将 JSON 兼容对象编码为稳定的 UTF-8 JSON 字符串。"""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无法编码 JSON 数据：{exc}") from exc


def decode_json(value: str | bytes | None, default=None):
    """解析数据库 JSON 字段；NULL 使用调用者指定的默认值。"""
    if value is None:
        return default

    try:
        return json.loads(value)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"数据库中的 JSON 数据无效：{exc}") from exc


@contextmanager
def write_transaction(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Iterator[sqlite3.Connection]:
    """当前版本专用立即写事务；不自动创建或升级数据库。"""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在，拒绝自动创建：{path}")

    conn = connect(path)

    try:
        conn.execute("BEGIN IMMEDIATE")
        require_schema_version(conn)

        yield conn
        conn.commit()

    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    finally:
        conn.close()


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """创建数据库连接并启用外键约束。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def database(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Iterator[sqlite3.Connection]:
    """事务管理：成功提交，异常回滚。"""
    conn = connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_database(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """幂等初始化数据库结构和首批五门学科。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(path)
    try:
        conn.execute("PRAGMA synchronous = FULL")

        # 先检查数据库版本，禁止旧初始化器触碰 V2/V3 数据库。
        conn.execute("BEGIN IMMEDIATE")

        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table'"
                ).fetchall()
            }

            if tables:
                if "schema_meta" not in tables:
                    raise RuntimeError(
                        "数据库非空但缺少 schema_meta，拒绝初始化"
                    )

                current = conn.execute(
                    "SELECT value FROM schema_meta "
                    "WHERE key = 'schema_version'"
                ).fetchone()

                if current is None:
                    raise RuntimeError(
                        "数据库缺少 schema_version，拒绝初始化"
                    )

                try:
                    current_version = int(current["value"])
                except (TypeError, ValueError):
                    raise RuntimeError(
                        "数据库版本号无效，拒绝初始化"
                    ) from None

                if current_version != SCHEMA_VERSION:
                    raise RuntimeError(
                        "V1 初始化器只允许操作 V1 数据库；"
                        f"当前版本为 {current_version}"
                    )

            schema = """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT,
                grade TEXT,
                region TEXT,
                school_system TEXT,
                learning_goals TEXT NOT NULL DEFAULT '',
                english_level TEXT NOT NULL DEFAULT '初中起步',
                teaching_preferences TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                subject_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'textbook',
                publisher TEXT,
                edition TEXT,
                grade TEXT,
                region TEXT,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                storage_path TEXT NOT NULL,
                checksum_sha256 TEXT,
                parse_status TEXT NOT NULL DEFAULT 'queued'
                    CHECK (
                        parse_status IN (
                            'queued', 'processing',
                            'completed', 'failed'
                        )
                    ),
                parse_error TEXT,
                uploaded_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(subject_id) REFERENCES subjects(id)
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                parent_id TEXT,
                chapter_no TEXT,
                title TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                source_page_start INTEGER,
                source_page_end INTEGER,
                FOREIGN KEY(document_id)
                    REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id)
                    REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_points (
                id TEXT PRIMARY KEY,
                subject_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                difficulty INTEGER NOT NULL DEFAULT 1
                    CHECK (difficulty BETWEEN 1 AND 5),
                source_kind TEXT NOT NULL DEFAULT 'textbook'
                    CHECK (
                        source_kind IN (
                            'textbook',
                            'ai_supplement',
                            'teacher_added'
                        )
                    ),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(subject_id) REFERENCES subjects(id)
            );

            CREATE TABLE IF NOT EXISTS chapter_knowledge_points (
                chapter_id TEXT NOT NULL,
                knowledge_point_id TEXT NOT NULL,
                relation_note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(chapter_id, knowledge_point_id),
                FOREIGN KEY(chapter_id)
                    REFERENCES chapters(id) ON DELETE CASCADE,
                FOREIGN KEY(knowledge_point_id)
                    REFERENCES knowledge_points(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_mastery (
                profile_id INTEGER NOT NULL,
                knowledge_point_id TEXT NOT NULL,
                mastery_score REAL NOT NULL DEFAULT 0
                    CHECK (mastery_score >= 0 AND mastery_score <= 1),
                confidence TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (
                        confidence IN (
                            'unknown', 'low', 'medium', 'high'
                        )
                    ),
                last_assessed_at TEXT,
                next_review_at TEXT,
                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(profile_id, knowledge_point_id),
                FOREIGN KEY(profile_id)
                    REFERENCES learning_profiles(id) ON DELETE CASCADE,
                FOREIGN KEY(knowledge_point_id)
                    REFERENCES knowledge_points(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_documents_subject
                ON documents(subject_id, uploaded_at);

            CREATE INDEX IF NOT EXISTS idx_chapters_document
                ON chapters(document_id, sort_order);

            CREATE INDEX IF NOT EXISTS idx_knowledge_subject
                ON knowledge_points(subject_id, title);

            CREATE INDEX IF NOT EXISTS idx_mastery_review
                ON knowledge_mastery(profile_id, next_review_at);
            """

            # 逐条执行 DDL，避免 executescript 隐式提交事务。
            for statement in schema.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)

            # 仅首次写入版本；绝不覆盖已有版本。
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_meta(key, value)
                VALUES ('schema_version', ?)
                """,
                (str(SCHEMA_VERSION),),
            )

            conn.executemany(
                """
                INSERT INTO subjects(code, name, sort_order)
                VALUES (?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    sort_order = excluded.sort_order,
                    is_active = 1
                """,
                SUBJECTS,
            )

            conn.commit()

        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

        subject_count = conn.execute(
            "SELECT COUNT(*) FROM subjects"
        ).fetchone()[0]

        profile_count = conn.execute(
            "SELECT COUNT(*) FROM learning_profiles"
        ).fetchone()[0]

        return {
            "database": str(path),
            "schema_version": SCHEMA_VERSION,
            "subject_count": subject_count,
            "profile_count": profile_count,
        }

    finally:
        conn.close()


def list_subjects(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """获取已启用学科。"""
    with database(db_path) as conn:
        rows = conn.execute(
            """
            SELECT code, name, sort_order, is_active
            FROM subjects
            WHERE is_active = 1
            ORDER BY sort_order, id
            """
        ).fetchall()

        return [dict(row) for row in rows]


def create_learning_profile(
    display_name: str | None = None,
    grade: str | None = None,
    region: str | None = None,
    school_system: str | None = None,
    learning_goals: str = "",
    english_level: str = "初中起步",
    teaching_preferences: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """创建学习者档案，返回档案 ID。"""
    with database(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_profiles(
                display_name,
                grade,
                region,
                school_system,
                learning_goals,
                english_level,
                teaching_preferences
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                display_name,
                grade,
                region,
                school_system,
                learning_goals,
                english_level,
                teaching_preferences,
            ),
        )

        return int(cursor.lastrowid)


def get_learning_profile(
    profile_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按 ID 获取学习者档案。"""
    with database(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM learning_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()

        return dict(row) if row else None


def _decode_learner_teaching_profile(row: sqlite3.Row) -> dict:
    """将学科画像记录中的 JSON 字段解析为 Python 对象。"""
    result = dict(row)
    object_fields = (
        "learning_state",
        "knowledge_mastery",
        "learning_preferences",
        "learning_pace",
        "motivation_observations",
    )
    list_fields = ("strengths", "difficulties")

    for field in object_fields:
        result[field] = decode_json(result[field], default={})
        if not isinstance(result[field], dict):
            raise ValueError(f"{field} 必须是 JSON 对象")

    for field in list_fields:
        result[field] = decode_json(result[field], default=[])
        if not isinstance(result[field], list):
            raise ValueError(f"{field} 必须是 JSON 数组")

    return result


def create_learner_teaching_profile(
    profile_id: int,
    subject_id: int,
    learning_state: dict | None = None,
    knowledge_mastery: dict | None = None,
    strengths: list | None = None,
    difficulties: list | None = None,
    learning_preferences: dict | None = None,
    learning_pace: dict | None = None,
    motivation_observations: dict | None = None,
    confidence_score: float | None = None,
    observation_count: int = 0,
    last_assessed_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建学习者的单学科教学画像。"""
    object_values = {
        "learning_state": {} if learning_state is None else learning_state,
        "knowledge_mastery": {} if knowledge_mastery is None else knowledge_mastery,
        "learning_preferences": {} if learning_preferences is None else learning_preferences,
        "learning_pace": {} if learning_pace is None else learning_pace,
        "motivation_observations": (
            {} if motivation_observations is None else motivation_observations
        ),
    }
    list_values = {
        "strengths": [] if strengths is None else strengths,
        "difficulties": [] if difficulties is None else difficulties,
    }

    for field, value in object_values.items():
        if not isinstance(value, dict):
            raise ValueError(f"{field} 必须是 dict")

    for field, value in list_values.items():
        if not isinstance(value, list):
            raise ValueError(f"{field} 必须是 list")

    with write_transaction(db_path) as conn:
        profile_id_value = generate_id()
        conn.execute(
            """
            INSERT INTO learner_teaching_profiles (
                id, profile_id, subject_id,
                learning_state, knowledge_mastery,
                strengths, difficulties,
                learning_preferences, learning_pace,
                motivation_observations,
                confidence_score, observation_count, last_assessed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id_value,
                profile_id,
                subject_id,
                encode_json(object_values["learning_state"]),
                encode_json(object_values["knowledge_mastery"]),
                encode_json(list_values["strengths"]),
                encode_json(list_values["difficulties"]),
                encode_json(object_values["learning_preferences"]),
                encode_json(object_values["learning_pace"]),
                encode_json(object_values["motivation_observations"]),
                confidence_score,
                observation_count,
                last_assessed_at,
            ),
        )

        row = conn.execute(
            "SELECT * FROM learner_teaching_profiles WHERE id = ?",
            (profile_id_value,),
        ).fetchone()

        return _decode_learner_teaching_profile(row)


def get_learner_teaching_profile(
    profile_id: int,
    subject_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按学习档案 ID 和学科 ID 获取教学画像。"""
    with write_transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM learner_teaching_profiles
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()

        return _decode_learner_teaching_profile(row) if row else None


def update_learner_teaching_profile(
    learner_profile_id: str,
    *,
    learning_state=_UNSET,
    knowledge_mastery=_UNSET,
    strengths=_UNSET,
    difficulties=_UNSET,
    learning_preferences=_UNSET,
    learning_pace=_UNSET,
    motivation_observations=_UNSET,
    confidence_score=_UNSET,
    observation_count=_UNSET,
    last_assessed_at=_UNSET,
    change_reason: str = "",
    evidence: dict | None = None,
    teaching_session_id: str | None = None,
    change_type: str = "assessment",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """更新学科画像，并在同一事务中追加不可变历史记录。"""
    if not isinstance(learner_profile_id, str) or not learner_profile_id:
        raise ValueError("learner_profile_id 必须是非空字符串")

    if not isinstance(change_reason, str):
        raise ValueError("change_reason 必须是字符串")

    if not isinstance(change_type, str) or not change_type.strip():
        raise ValueError("change_type 必须是非空字符串")

    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ValueError("evidence 必须是字典")

    if teaching_session_id is not None and not isinstance(
        teaching_session_id, str
    ):
        raise ValueError("teaching_session_id 必须是字符串或 None")

    object_fields = (
        "learning_state",
        "knowledge_mastery",
        "learning_preferences",
        "learning_pace",
        "motivation_observations",
    )
    list_fields = ("strengths", "difficulties")

    updates = {}
    for field in object_fields:
        value = locals()[field]
        if value is not _UNSET:
            if not isinstance(value, dict):
                raise ValueError(f"{field} 必须是字典")
            updates[field] = encode_json(value)

    for field in list_fields:
        value = locals()[field]
        if value is not _UNSET:
            if not isinstance(value, list):
                raise ValueError(f"{field} 必须是列表")
            updates[field] = encode_json(value)

    if confidence_score is not _UNSET:
        if confidence_score is not None:
            if (
                isinstance(confidence_score, bool)
                or not isinstance(confidence_score, (int, float))
                or not 0 <= confidence_score <= 1
            ):
                raise ValueError("confidence_score 必须在 0 到 1 之间或为 None")
        updates["confidence_score"] = confidence_score

    if observation_count is not _UNSET:
        if (
            isinstance(observation_count, bool)
            or not isinstance(observation_count, int)
            or observation_count < 0
        ):
            raise ValueError("observation_count 必须是非负整数")
        updates["observation_count"] = observation_count

    if last_assessed_at is not _UNSET:
        if last_assessed_at is not None and not isinstance(last_assessed_at, str):
            raise ValueError("last_assessed_at 必须是字符串或 None")
        updates["last_assessed_at"] = last_assessed_at

    if not updates:
        raise ValueError("至少需要提供一个要更新的画像字段")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM learner_teaching_profiles WHERE id = ?",
            (learner_profile_id,),
        ).fetchone()

        if row is None:
            raise LookupError(f"学科画像不存在：{learner_profile_id}")

        previous = _decode_learner_teaching_profile(row)

        assignments = [f"{field} = ?" for field in updates]
        values = list(updates.values())
        assignments.append(
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        )

        conn.execute(
            f"""
            UPDATE learner_teaching_profiles
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            (*values, learner_profile_id),
        )

        updated_row = conn.execute(
            "SELECT * FROM learner_teaching_profiles WHERE id = ?",
            (learner_profile_id,),
        ).fetchone()

        updated = _decode_learner_teaching_profile(updated_row)

        state_fields = (
            "learning_state",
            "knowledge_mastery",
            "strengths",
            "difficulties",
            "learning_preferences",
            "learning_pace",
            "motivation_observations",
            "confidence_score",
            "observation_count",
            "last_assessed_at",
        )

        previous_state = {
            field: previous[field] for field in state_fields
        }
        new_state = {
            field: updated[field] for field in state_fields
        }

        conn.execute(
            """
            INSERT INTO learner_profile_history (
                id,
                learner_profile_id,
                change_type,
                previous_state,
                new_state,
                change_reason,
                evidence_json,
                teaching_session_id,
                confidence_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generate_id(),
                learner_profile_id,
                change_type,
                encode_json(previous_state),
                encode_json(new_state),
                change_reason,
                encode_json(evidence),
                teaching_session_id,
                updated["confidence_score"],
            ),
        )

        return updated


def add_learner_profile_history(
    learner_profile_id: str,
    change_type: str = "assessment",
    previous_state: dict | None = None,
    new_state: dict | None = None,
    change_reason: str = "",
    evidence: dict | None = None,
    teaching_session_id: str | None = None,
    confidence_score: float | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """独立追加一条学科画像历史记录，不修改当前画像。"""
    if not isinstance(learner_profile_id, str) or not learner_profile_id:
        raise ValueError("learner_profile_id 必须是非空字符串")

    if not isinstance(change_type, str) or not change_type.strip():
        raise ValueError("change_type 必须是非空字符串")

    if not isinstance(change_reason, str):
        raise ValueError("change_reason 必须是字符串")

    for name, value in (
        ("previous_state", previous_state),
        ("new_state", new_state),
        ("evidence", evidence),
    ):
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{name} 必须是字典或 None")

    if teaching_session_id is not None and not isinstance(
        teaching_session_id, str
    ):
        raise ValueError("teaching_session_id 必须是字符串或 None")

    if confidence_score is not None:
        if (
            isinstance(confidence_score, bool)
            or not isinstance(confidence_score, (int, float))
            or not 0 <= confidence_score <= 1
        ):
            raise ValueError("confidence_score 必须在 0 到 1 之间或为 None")

    previous_state = previous_state if previous_state is not None else {}
    new_state = new_state if new_state is not None else {}
    evidence = evidence if evidence is not None else {}

    history_id = generate_id()

    with write_transaction(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM learner_teaching_profiles WHERE id = ?",
            (learner_profile_id,),
        ).fetchone()

        if exists is None:
            raise LookupError(f"学科画像不存在：{learner_profile_id}")

        conn.execute(
            """
            INSERT INTO learner_profile_history (
                id, learner_profile_id, change_type,
                previous_state, new_state, change_reason,
                evidence_json, teaching_session_id, confidence_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history_id,
                learner_profile_id,
                change_type,
                encode_json(previous_state),
                encode_json(new_state),
                change_reason,
                encode_json(evidence),
                teaching_session_id,
                confidence_score,
            ),
        )

        row = conn.execute(
            "SELECT * FROM learner_profile_history WHERE id = ?",
            (history_id,),
        ).fetchone()

        return {
            "id": row["id"],
            "learner_profile_id": row["learner_profile_id"],
            "change_type": row["change_type"],
            "previous_state": decode_json(row["previous_state"], {}),
            "new_state": decode_json(row["new_state"], {}),
            "change_reason": row["change_reason"],
            "evidence": decode_json(row["evidence_json"], {}),
            "teaching_session_id": row["teaching_session_id"],
            "confidence_score": row["confidence_score"],
            "created_at": row["created_at"],
        }


def list_learner_profile_history(
    learner_profile_id: str,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """按时间倒序查询学科画像历史记录，支持分页。"""
    if not isinstance(learner_profile_id, str) or not learner_profile_id:
        raise ValueError("learner_profile_id 必须是非空字符串")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM learner_profile_history
            WHERE learner_profile_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            (learner_profile_id, limit, offset),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "learner_profile_id": row["learner_profile_id"],
                "change_type": row["change_type"],
                "previous_state": decode_json(row["previous_state"], {}),
                "new_state": decode_json(row["new_state"], {}),
                "change_reason": row["change_reason"],
                "evidence": decode_json(row["evidence_json"], {}),
                "teaching_session_id": row["teaching_session_id"],
                "confidence_score": row["confidence_score"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
def create_teaching_method(
    slug: str,
    name: str,
    description: str = "",
    subject_id: int | None = None,
    method_category: str = "general",
    status: str = "candidate",
    confidence_score: float | None = None,
    discovery_source: str = "research",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学方法主档。"""
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError("slug 必须是非空字符串")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name 必须是非空字符串")
    if not isinstance(description, str):
        raise ValueError("description 必须是字符串")
    if not isinstance(method_category, str) or not method_category.strip():
        raise ValueError("method_category 必须是非空字符串")
    if status not in {"candidate", "active", "disabled", "deprecated"}:
        raise ValueError("无效的 status")
    if discovery_source not in {
        "research", "manual", "model_generated", "imported"
    }:
        raise ValueError("无效的 discovery_source")
    if confidence_score is not None:
        if (
            isinstance(confidence_score, bool)
            or not isinstance(confidence_score, (int, float))
            or not 0 <= confidence_score <= 1
        ):
            raise ValueError("confidence_score 必须是 0 到 1 之间的数字或 None")
    if subject_id is not None:
        if isinstance(subject_id, bool) or not isinstance(subject_id, int):
            raise ValueError("subject_id 必须是整数或 None")

    method_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO teaching_methods (
                id, slug, name, description, subject_id,
                method_category, status, confidence_score, discovery_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                method_id,
                slug.strip(),
                name.strip(),
                description,
                subject_id,
                method_category.strip(),
                status,
                confidence_score,
                discovery_source,
            ),
        )

        row = conn.execute(
            "SELECT * FROM teaching_methods WHERE id = ?",
            (method_id,),
        ).fetchone()

        return dict(row)
def get_teaching_method(
    method_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据 UUID 获取教学方法主档。"""
    if not isinstance(method_id, str) or not method_id.strip():
        raise ValueError("method_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM teaching_methods WHERE id = ?",
            (method_id.strip(),),
        ).fetchone()

        return dict(row) if row else None
def get_teaching_method_by_slug(
    slug: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据唯一 slug 获取教学方法主档。"""
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError("slug 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM teaching_methods WHERE slug = ?",
            (slug.strip(),),
        ).fetchone()

        return dict(row) if row else None
def list_teaching_methods(
    subject_id: int | None = None,
    status: str | None = None,
    method_category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """筛选并分页查询教学方法。"""
    if subject_id is not None:
        if isinstance(subject_id, bool) or not isinstance(subject_id, int):
            raise ValueError("subject_id 必须是整数或 None")

    if status is not None:
        if status not in {"candidate", "active", "disabled", "deprecated"}:
            raise ValueError("无效的 status")

    if method_category is not None:
        if not isinstance(method_category, str) or not method_category.strip():
            raise ValueError("method_category 必须是非空字符串或 None")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = []
    params = []

    if subject_id is not None:
        conditions.append("subject_id = ?")
        params.append(subject_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if method_category is not None:
        conditions.append("method_category = ?")
        params.append(method_category.strip())

    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    params.extend([limit, offset])

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM teaching_methods
            {where_clause}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        return [dict(row) for row in rows]
def create_teaching_method_version(
    method_id: str,
    version_no: int,
    summary: str = "",
    teaching_steps: list | None = None,
    applicable_stages: list | None = None,
    applicable_grades: list | None = None,
    applicable_subjects: list | None = None,
    applicable_scenarios: list | None = None,
    prerequisites: list | None = None,
    limitations: list | None = None,
    expected_outcomes: list | None = None,
    evidence_summary: str = "",
    confidence_score: float | None = None,
    review_status: str = "candidate",
    created_by: str = "muse",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学方法版本，保留已有版本不被覆盖。"""

    if not isinstance(method_id, str) or not method_id.strip():
        raise ValueError("method_id 必须是非空字符串")

    if isinstance(version_no, bool) or not isinstance(version_no, int) or version_no <= 0:
        raise ValueError("version_no 必须是正整数")

    if not isinstance(summary, str):
        raise ValueError("summary 必须是字符串")

    if not isinstance(evidence_summary, str):
        raise ValueError("evidence_summary 必须是字符串")

    if review_status not in ("candidate", "approved", "rejected", "superseded"):
        raise ValueError("无效的 review_status")

    if not isinstance(created_by, str) or not created_by.strip():
        raise ValueError("created_by 必须是非空字符串")

    if confidence_score is not None:
        if (
            isinstance(confidence_score, bool)
            or not isinstance(confidence_score, (int, float))
            or not 0 <= confidence_score <= 1
        ):
            raise ValueError("confidence_score 必须是 0 到 1 之间的数字或 None")

    list_fields = {
        "teaching_steps": teaching_steps,
        "applicable_stages": applicable_stages,
        "applicable_grades": applicable_grades,
        "applicable_subjects": applicable_subjects,
        "applicable_scenarios": applicable_scenarios,
        "prerequisites": prerequisites,
        "limitations": limitations,
        "expected_outcomes": expected_outcomes,
    }

    encoded_fields = {}
    for field, value in list_fields.items():
        if value is None:
            value = []
        if not isinstance(value, list):
            raise ValueError(f"{field} 必须是列表")
        encoded_fields[field] = encode_json(value)

    version_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO teaching_method_versions (
                id,
                method_id,
                version_no,
                summary,
                teaching_steps,
                applicable_stages,
                applicable_grades,
                applicable_subjects,
                applicable_scenarios,
                prerequisites,
                limitations,
                expected_outcomes,
                evidence_summary,
                confidence_score,
                review_status,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                method_id.strip(),
                version_no,
                summary,
                encoded_fields["teaching_steps"],
                encoded_fields["applicable_stages"],
                encoded_fields["applicable_grades"],
                encoded_fields["applicable_subjects"],
                encoded_fields["applicable_scenarios"],
                encoded_fields["prerequisites"],
                encoded_fields["limitations"],
                encoded_fields["expected_outcomes"],
                evidence_summary,
                confidence_score,
                review_status,
                created_by.strip(),
            ),
        )

        row = conn.execute(
            "SELECT * FROM teaching_method_versions WHERE id = ?",
            (version_id,),
        ).fetchone()

        result = dict(row)

        for field in list_fields:
            result[field] = decode_json(result[field], default=[])

        return result
def get_teaching_method_version(
    version_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据版本 ID 获取教学方法版本。"""

    if not isinstance(version_id, str) or not version_id.strip():
        raise ValueError("version_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM teaching_method_versions
            WHERE id = ?
            """,
            (version_id.strip(),),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        json_fields = (
            "teaching_steps",
            "applicable_stages",
            "applicable_grades",
            "applicable_subjects",
            "applicable_scenarios",
            "prerequisites",
            "limitations",
            "expected_outcomes",
        )

        for field in json_fields:
            result[field] = decode_json(result[field], default=[])

        return result
def list_teaching_method_versions(
    method_id: str,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """获取教学方法的版本列表，支持审核状态筛选和分页。"""

    if not isinstance(method_id, str) or not method_id.strip():
        raise ValueError("method_id 必须是非空字符串")

    if review_status is not None:
        if review_status not in ("candidate", "approved", "rejected", "superseded"):
            raise ValueError("无效的 review_status")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = ["method_id = ?"]
    params = [method_id.strip()]

    if review_status is not None:
        conditions.append("review_status = ?")
        params.append(review_status)

    params.extend([limit, offset])

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM teaching_method_versions
            WHERE {" AND ".join(conditions)}
            ORDER BY version_no DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        json_fields = (
            "teaching_steps",
            "applicable_stages",
            "applicable_grades",
            "applicable_subjects",
            "applicable_scenarios",
            "prerequisites",
            "limitations",
            "expected_outcomes",
        )

        results = []

        for row in rows:
            result = dict(row)

            for field in json_fields:
                result[field] = decode_json(result[field], default=[])

            results.append(result)

        return results
def add_teaching_method_evidence(
    method_version_id: str,
    source_id: str,
    evidence_type: str = "supporting",
    finding: str = "",
    limitations: str = "",
    evidence_strength: str = "unknown",
    confidence_score: float | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """为教学方法版本添加研究证据。"""

    if not isinstance(method_version_id, str) or not method_version_id.strip():
        raise ValueError("method_version_id 必须是非空字符串")

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 必须是非空字符串")

    if not isinstance(evidence_type, str) or not evidence_type.strip():
        raise ValueError("evidence_type 必须是非空字符串")

    if not isinstance(finding, str):
        raise ValueError("finding 必须是字符串")

    if not isinstance(limitations, str):
        raise ValueError("limitations 必须是字符串")

    allowed_strengths = (
        "very_low",
        "low",
        "moderate",
        "high",
        "very_high",
        "unknown",
    )
    if evidence_strength not in allowed_strengths:
        raise ValueError("无效的 evidence_strength")

    if confidence_score is not None:
        if (
            isinstance(confidence_score, bool)
            or not isinstance(confidence_score, (int, float))
            or not 0 <= confidence_score <= 1
        ):
            raise ValueError("confidence_score 必须是 0 到 1 之间的数字或 None")

    evidence_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO teaching_method_evidence (
                id,
                method_version_id,
                source_id,
                evidence_type,
                finding,
                limitations,
                evidence_strength,
                confidence_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                method_version_id.strip(),
                source_id.strip(),
                evidence_type.strip(),
                finding,
                limitations,
                evidence_strength,
                confidence_score,
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM teaching_method_evidence
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()

        return dict(row)
def list_teaching_method_evidence(
    method_version_id: str,
    evidence_strength: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """获取教学方法版本的证据列表，支持强度筛选和分页。"""

    if not isinstance(method_version_id, str) or not method_version_id.strip():
        raise ValueError("method_version_id 必须是非空字符串")

    allowed_strengths = (
        "very_low",
        "low",
        "moderate",
        "high",
        "very_high",
        "unknown",
    )

    if evidence_strength is not None:
        if evidence_strength not in allowed_strengths:
            raise ValueError("无效的 evidence_strength")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = ["method_version_id = ?"]
    params = [method_version_id.strip()]

    if evidence_strength is not None:
        conditions.append("evidence_strength = ?")
        params.append(evidence_strength)

    params.extend([limit, offset])

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM teaching_method_evidence
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        return [dict(row) for row in rows]
def create_teaching_research_source(
    title: str,
    source_type: str = "web",
    url: str | None = None,
    canonical_url: str | None = None,
    content_hash: str | None = None,
    publisher: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
    language: str | None = None,
    reliability_score: float | None = None,
    source_quality: str = "unreviewed",
    extracted_content: str = "",
    metadata: dict | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学研究来源记录。"""

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title 必须是非空字符串")

    allowed_source_types = (
        "web", "paper", "book", "course",
        "video", "teacher_case", "official_resource", "other",
    )
    if source_type not in allowed_source_types:
        raise ValueError("无效的 source_type")

    optional_strings = {
        "url": url,
        "canonical_url": canonical_url,
        "content_hash": content_hash,
        "publisher": publisher,
        "author": author,
        "published_at": published_at,
        "language": language,
    }
    for field, value in optional_strings.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串或 None")

    if reliability_score is not None:
        if (
            isinstance(reliability_score, bool)
            or not isinstance(reliability_score, (int, float))
            or not 0 <= reliability_score <= 1
        ):
            raise ValueError("reliability_score 必须在 0 到 1 之间")

    allowed_qualities = ("unreviewed", "low", "medium", "high", "verified")
    if source_quality not in allowed_qualities:
        raise ValueError("无效的 source_quality")

    if not isinstance(extracted_content, str):
        raise ValueError("extracted_content 必须是字符串")

    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是字典")

    metadata_json = encode_json(metadata)
    source_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO teaching_research_sources (
                id,
                source_type,
                title,
                url,
                canonical_url,
                content_hash,
                publisher,
                author,
                published_at,
                language,
                reliability_score,
                source_quality,
                extracted_content,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source_type,
                title.strip(),
                url,
                canonical_url,
                content_hash,
                publisher,
                author,
                published_at,
                language,
                reliability_score,
                source_quality,
                extracted_content,
                metadata_json,
            ),
        )

        row = conn.execute(
            "SELECT * FROM teaching_research_sources WHERE id = ?",
            (source_id,),
        ).fetchone()

        result = dict(row)
        result["metadata"] = decode_json(result.pop("metadata_json"), {})
        return result
def get_teaching_research_source(
    source_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据来源 ID 查询研究来源。"""

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM teaching_research_sources
            WHERE id = ?
            """,
            (source_id.strip(),),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["metadata"] = decode_json(
            result.pop("metadata_json"),
            {},
        )
        return result
def list_teaching_research_sources(
    source_type: str | None = None,
    source_quality: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """查询教学研究来源，支持类型、质量等级筛选和分页。"""

    allowed_source_types = {
        "web", "paper", "book", "course",
        "video", "teacher_case", "official_resource", "other",
    }
    allowed_source_qualities = {
        "unreviewed", "low", "medium", "high", "verified",
    }

    if source_type is not None:
        if not isinstance(source_type, str) or source_type not in allowed_source_types:
            raise ValueError("source_type 无效")

    if source_quality is not None:
        if not isinstance(source_quality, str) or source_quality not in allowed_source_qualities:
            raise ValueError("source_quality 无效")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = []
    params = []

    if source_type is not None:
        conditions.append("source_type = ?")
        params.append(source_type)

    if source_quality is not None:
        conditions.append("source_quality = ?")
        params.append(source_quality)

    where_sql = ""
    if conditions:
        where_sql = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT *
        FROM teaching_research_sources
        {where_sql}
        ORDER BY accessed_at DESC, rowid DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    with write_transaction(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["metadata"] = decode_json(item.pop("metadata_json"), default={})
            results.append(item)

        return results
def find_teaching_research_source(
    canonical_url: str | None = None,
    content_hash: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按规范 URL 或内容哈希查找已有研究来源。"""

    if canonical_url is not None:
        if not isinstance(canonical_url, str) or not canonical_url.strip():
            raise ValueError("canonical_url 必须是非空字符串或 None")

    if content_hash is not None:
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError("content_hash 必须是非空字符串或 None")

    if canonical_url is None and content_hash is None:
        raise ValueError("canonical_url 和 content_hash 至少提供一个")

    with write_transaction(db_path) as conn:
        row = None

        # 优先按规范 URL 查找
        if canonical_url is not None:
            row = conn.execute(
                """
                SELECT *
                FROM teaching_research_sources
                WHERE canonical_url = ?
                ORDER BY accessed_at DESC, rowid DESC
                LIMIT 1
                """,
                (canonical_url.strip(),),
            ).fetchone()

        # URL 未找到时，再按内容哈希查找
        if row is None and content_hash is not None:
            row = conn.execute(
                """
                SELECT *
                FROM teaching_research_sources
                WHERE content_hash = ?
                ORDER BY accessed_at DESC, rowid DESC
                LIMIT 1
                """,
                (content_hash.strip(),),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["metadata"] = decode_json(
            result.pop("metadata_json"),
            default={},
        )
        return result
def update_teaching_research_source(
    source_id: str,
    title: str = _UNSET,
    source_type: str = _UNSET,
    url: str | None = _UNSET,
    canonical_url: str | None = _UNSET,
    content_hash: str | None = _UNSET,
    publisher: str | None = _UNSET,
    author: str | None = _UNSET,
    published_at: str | None = _UNSET,
    language: str | None = _UNSET,
    reliability_score: float | None = _UNSET,
    source_quality: str = _UNSET,
    extracted_content: str = _UNSET,
    metadata: dict | None = _UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """部分更新教学研究来源；未提供的字段保持原值。"""

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 必须是非空字符串")

    changes = {}

    if title is not _UNSET:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title 必须是非空字符串")
        changes["title"] = title.strip()

    if source_type is not _UNSET:
        allowed_source_types = (
            "web", "paper", "book", "course",
            "video", "teacher_case", "official_resource", "other",
        )
        if not isinstance(source_type, str) or source_type not in allowed_source_types:
            raise ValueError("无效的 source_type")
        changes["source_type"] = source_type

    optional_string_fields = (
        "url", "canonical_url", "content_hash",
        "publisher", "author", "published_at", "language",
    )

    values = {
        "url": url,
        "canonical_url": canonical_url,
        "content_hash": content_hash,
        "publisher": publisher,
        "author": author,
        "published_at": published_at,
        "language": language,
    }

    for field in optional_string_fields:
        value = values[field]
        if value is not _UNSET:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")
            changes[field] = value

    if reliability_score is not _UNSET:
        if reliability_score is not None:
            if (
                isinstance(reliability_score, bool)
                or not isinstance(reliability_score, (int, float))
                or not 0 <= reliability_score <= 1
            ):
                raise ValueError("reliability_score 必须在 0 到 1 之间")
        changes["reliability_score"] = reliability_score

    if source_quality is not _UNSET:
        allowed_qualities = (
            "unreviewed", "low", "medium", "high", "verified",
        )
        if not isinstance(source_quality, str) or source_quality not in allowed_qualities:
            raise ValueError("无效的 source_quality")
        changes["source_quality"] = source_quality

    if extracted_content is not _UNSET:
        if not isinstance(extracted_content, str):
            raise ValueError("extracted_content 必须是字符串")
        changes["extracted_content"] = extracted_content

    if metadata is not _UNSET:
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata 必须是字典")
        changes["metadata_json"] = encode_json(metadata)

    with write_transaction(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM teaching_research_sources
            WHERE id = ?
            """,
            (source_id.strip(),),
        ).fetchone()

        if existing is None:
            return None

        if changes:
            assignments = ", ".join(
                f"{field} = ?" for field in changes
            )
            params = list(changes.values())
            params.append(source_id.strip())

            conn.execute(
                f"""
                UPDATE teaching_research_sources
                SET {assignments}
                WHERE id = ?
                """,
                params,
            )

        row = conn.execute(
            """
            SELECT *
            FROM teaching_research_sources
            WHERE id = ?
            """,
            (source_id.strip(),),
        ).fetchone()

        result = dict(row)
        result["metadata"] = decode_json(
            result.pop("metadata_json"),
            default={},
        )
        return result
def create_research_job(
    topic: str,
    job_type: str = "teaching_method_discovery",
    subject_id: int | None = None,
    education_stage: str | None = None,
    grade_level: str | None = None,
    status: str = "pending",
    search_plan: str = "",
    result_summary: str = "",
    error_message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学研究任务。"""

    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic 必须是非空字符串")

    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("job_type 必须是非空字符串")

    if (
        isinstance(subject_id, bool)
        or (subject_id is not None and not isinstance(subject_id, int))
    ):
        raise ValueError("subject_id 必须是整数或 None")

    allowed_statuses = {
        "pending", "running", "completed", "failed", "cancelled"
    }
    if not isinstance(status, str) or status not in allowed_statuses:
        raise ValueError("无效的 status")

    nullable_string_fields = {
        "education_stage": education_stage,
        "grade_level": grade_level,
    }
    for field, value in nullable_string_fields.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串或 None")

    required_string_fields = {
        "search_plan": search_plan,
        "result_summary": result_summary,
    }
    for field, value in required_string_fields.items():
        if not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串")
    nullable_string_fields = {
        "error_message": error_message,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    for field, value in nullable_string_fields.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串或 None")

    job_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_jobs (
                id,
                job_type,
                topic,
                subject_id,
                education_stage,
                grade_level,
                status,
                search_plan,
                result_summary,
                error_message,
                started_at,
                finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type.strip(),
                topic.strip(),
                subject_id,
                education_stage,
                grade_level,
                status,
                search_plan,
                result_summary,
                error_message,
                started_at,
                finished_at,
            ),
        )

        row = conn.execute(
            "SELECT * FROM research_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

        return dict(row)


def get_research_job(
    job_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据 ID 获取教学研究任务。"""

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM research_jobs
            WHERE id = ?
            """,
            (job_id.strip(),),
        ).fetchone()

        return dict(row) if row is not None else None


def list_research_jobs(
    status: str | None = None,
    subject_id: int | None = None,
    job_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """查询研究任务，支持状态、学科、类型筛选和分页。"""

    allowed_statuses = {
        "pending", "running", "completed", "failed", "cancelled"
    }

    if status is not None:
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError("无效的 status")

    if (
        isinstance(subject_id, bool)
        or (subject_id is not None and not isinstance(subject_id, int))
    ):
        raise ValueError("subject_id 必须是整数或 None")

    if job_type is not None:
        if not isinstance(job_type, str) or not job_type.strip():
            raise ValueError("job_type 必须是非空字符串或 None")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 500
    ):
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
    ):
        raise ValueError("offset 必须是非负整数")

    conditions = []
    params = []

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if subject_id is not None:
        conditions.append("subject_id = ?")
        params.append(subject_id)

    if job_type is not None:
        conditions.append("job_type = ?")
        params.append(job_type.strip())

    where_sql = ""
    if conditions:
        where_sql = "WHERE " + " AND ".join(conditions)

    params.extend([limit, offset])

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM research_jobs
            {where_sql}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        return [dict(row) for row in rows]


def update_research_job(
    job_id: str,
    job_type: str = _UNSET,
    topic: str = _UNSET,
    subject_id: int | None = _UNSET,
    education_stage: str | None = _UNSET,
    grade_level: str | None = _UNSET,
    status: str = _UNSET,
    search_plan: str = _UNSET,
    result_summary: str = _UNSET,
    error_message: str | None = _UNSET,
    started_at: str | None = _UNSET,
    finished_at: str | None = _UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """部分更新研究任务；未提供的字段保持原值。"""

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id 必须是非空字符串")

    changes = {}

    if job_type is not _UNSET:
        if not isinstance(job_type, str) or not job_type.strip():
            raise ValueError("job_type 必须是非空字符串")
        changes["job_type"] = job_type.strip()

    if topic is not _UNSET:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic 必须是非空字符串")
        changes["topic"] = topic.strip()

    if subject_id is not _UNSET:
        if (
            isinstance(subject_id, bool)
            or (subject_id is not None and not isinstance(subject_id, int))
        ):
            raise ValueError("subject_id 必须是整数或 None")
        changes["subject_id"] = subject_id
    for field, value in {
        "education_stage": education_stage,
        "grade_level": grade_level,
    }.items():
        if value is not _UNSET:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")
            changes[field] = value

    for field, value in {
        "search_plan": search_plan,
        "result_summary": result_summary,
    }.items():
        if value is not _UNSET:
            if not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串")
            changes[field] = value
    for field, value in {
        "error_message": error_message,
        "started_at": started_at,
        "finished_at": finished_at,
    }.items():
        if value is not _UNSET:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")
            changes[field] = value

    if status is not _UNSET:
        allowed_statuses = {
            "pending", "running", "completed", "failed", "cancelled"
        }
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError("无效的 status")
        changes["status"] = status

    with write_transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM research_jobs WHERE id = ?",
            (job_id.strip(),),
        ).fetchone()

        if existing is None:
            return None

        if changes:
            assignments = ", ".join(
                f"{field} = ?" for field in changes
            )
            params = list(changes.values())
            params.append(job_id.strip())

            conn.execute(
                f"""
                UPDATE research_jobs
                SET {assignments}
                WHERE id = ?
                """,
                params,
            )

        row = conn.execute(
            "SELECT * FROM research_jobs WHERE id = ?",
            (job_id.strip(),),
        ).fetchone()

        return dict(row)


def add_research_job_source(
    research_job_id: str,
    source_id: str,
    relevance_score: float | None = None,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """添加研究任务与来源的关联；重复关联保持原记录不变。"""

    if not isinstance(research_job_id, str) or not research_job_id.strip():
        raise ValueError("research_job_id 必须是非空字符串")

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 必须是非空字符串")

    if relevance_score is not None:
        if (
            isinstance(relevance_score, bool)
            or not isinstance(relevance_score, (int, float))
            or not 0 <= relevance_score <= 1
        ):
            raise ValueError("relevance_score 必须是 0 到 1 之间的数字或 None")

    if not isinstance(notes, str):
        raise ValueError("notes 必须是字符串")

    job_id = research_job_id.strip()
    source_key = source_id.strip()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_job_sources (
                research_job_id,
                source_id,
                relevance_score,
                notes
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT (research_job_id, source_id) DO NOTHING
            """,
            (job_id, source_key, relevance_score, notes),
        )

        row = conn.execute(
            """
            SELECT
                research_job_id,
                source_id,
                relevance_score,
                notes,
                created_at
            FROM research_job_sources
            WHERE research_job_id = ? AND source_id = ?
            """,
            (job_id, source_key),
        ).fetchone()

        return dict(row)


def get_research_job_sources(
    research_job_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """查询研究任务关联的来源，并解码来源 metadata。"""

    if not isinstance(research_job_id, str) or not research_job_id.strip():
        raise ValueError("research_job_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.*,
                s.id AS source_id,
                rjs.research_job_id,
                rjs.relevance_score,
                rjs.notes,
                rjs.created_at AS association_created_at
            FROM research_job_sources AS rjs
            JOIN teaching_research_sources AS s
                ON s.id = rjs.source_id
            WHERE rjs.research_job_id = ?
            ORDER BY rjs.created_at ASC, s.id ASC
            """,
            (research_job_id.strip(),),
        ).fetchall()

        results = []
        for row in rows:
            result = dict(row)
            if "metadata_json" in result:
                result["metadata"] = decode_json(
                    result.pop("metadata_json"),
                    {},
                )
            results.append(result)

        return results


def remove_research_job_source(
    research_job_id: str,
    source_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """解除任务与来源的关联，不删除来源记录。"""

    if not isinstance(research_job_id, str) or not research_job_id.strip():
        raise ValueError("research_job_id 必须是非空字符串")

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM research_job_sources
            WHERE research_job_id = ? AND source_id = ?
            """,
            (research_job_id.strip(), source_id.strip()),
        )

        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Teaching strategy DAL
# ---------------------------------------------------------------------------

_TEACHING_STRATEGY_TYPES = {
    "explanation",
    "guided_practice",
    "inquiry",
    "practice",
    "review",
    "adaptive",
    "mixed",
}


def _decode_teaching_strategy(row) -> dict:
    """将策略记录转换为字典，并解码 strategy_config。"""
    result = dict(row)
    result["strategy_config"] = decode_json(
        result.get("strategy_config"),
        default={},
    )
    return result


def create_teaching_strategy(
    name: str,
    description: str = "",
    subject_id: int | None = None,
    method_version_id: str | None = None,
    strategy_type: str = "adaptive",
    target_stage: str | None = None,
    target_grade: str | None = None,
    difficulty_level: int | None = None,
    strategy_config: dict | None = None,
    is_active: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学策略。"""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("name 必须是非空字符串")

    if not isinstance(description, str):
        raise ValueError("description 必须是字符串")

    if subject_id is not None:
        if isinstance(subject_id, bool) or not isinstance(subject_id, int):
            raise ValueError("subject_id 必须是整数或 None")

    if method_version_id is not None:
        if not isinstance(method_version_id, str) or not method_version_id.strip():
            raise ValueError("method_version_id 必须是非空字符串或 None")
        method_version_id = method_version_id.strip()

    if strategy_type not in _TEACHING_STRATEGY_TYPES:
        raise ValueError("无效的 strategy_type")

    for field, value in (
        ("target_stage", target_stage),
        ("target_grade", target_grade),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串或 None")

    if difficulty_level is not None:
        if (
            isinstance(difficulty_level, bool)
            or not isinstance(difficulty_level, int)
            or not 1 <= difficulty_level <= 5
        ):
            raise ValueError("difficulty_level 必须是 1 到 5 之间的整数或 None")

    if strategy_config is None:
        strategy_config = {}
    if not isinstance(strategy_config, dict):
        raise ValueError("strategy_config 必须是 JSON 对象（dict）")

    if not isinstance(is_active, bool):
        raise ValueError("is_active 必须是 bool")

    config_json = encode_json(strategy_config)
    strategy_id = generate_id()

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO teaching_strategies (
                id, name, description, subject_id, method_version_id,
                strategy_type, target_stage, target_grade,
                difficulty_level, strategy_config, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
                name.strip(),
                description,
                subject_id,
                method_version_id,
                strategy_type,
                target_stage,
                target_grade,
                difficulty_level,
                config_json,
                int(is_active),
            ),
        )

        row = conn.execute(
            "SELECT * FROM teaching_strategies WHERE id = ?",
            (strategy_id,),
        ).fetchone()

        return _decode_teaching_strategy(row)


def get_teaching_strategy(
    strategy_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据 ID 查询教学策略。"""

    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("strategy_id 必须是非空字符串")

    with write_transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM teaching_strategies WHERE id = ?",
            (strategy_id.strip(),),
        ).fetchone()

        return _decode_teaching_strategy(row) if row else None


def list_teaching_strategies(
    subject_id: int | None = None,
    method_version_id: str | None = None,
    strategy_type: str | None = None,
    target_stage: str | None = None,
    target_grade: str | None = None,
    difficulty_level: int | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """按条件筛选并分页查询教学策略。"""

    if subject_id is not None:
        if isinstance(subject_id, bool) or not isinstance(subject_id, int):
            raise ValueError("subject_id 必须是整数或 None")

    if method_version_id is not None:
        if not isinstance(method_version_id, str) or not method_version_id.strip():
            raise ValueError("method_version_id 必须是非空字符串或 None")

    if strategy_type is not None and strategy_type not in _TEACHING_STRATEGY_TYPES:
        raise ValueError("无效的 strategy_type")

    for field, value in (
        ("target_stage", target_stage),
        ("target_grade", target_grade),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串或 None")

    if difficulty_level is not None:
        if (
            isinstance(difficulty_level, bool)
            or not isinstance(difficulty_level, int)
            or not 1 <= difficulty_level <= 5
        ):
            raise ValueError("difficulty_level 必须是 1 到 5 之间的整数或 None")

    if is_active is not None and not isinstance(is_active, bool):
        raise ValueError("is_active 必须是 bool 或 None")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = []
    params = []

    filters = (
        ("subject_id", subject_id),
        ("method_version_id", method_version_id.strip() if method_version_id else None),
        ("strategy_type", strategy_type),
        ("target_stage", target_stage),
        ("target_grade", target_grade),
        ("difficulty_level", difficulty_level),
    )

    for column, value in filters:
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value)

    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(int(is_active))

    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    params.extend((limit, offset))

    with write_transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM teaching_strategies
            {where_clause}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        return [_decode_teaching_strategy(row) for row in rows]


def update_teaching_strategy(
    strategy_id: str,
    name=_UNSET,
    description=_UNSET,
    subject_id=_UNSET,
    method_version_id=_UNSET,
    strategy_type=_UNSET,
    target_stage=_UNSET,
    target_grade=_UNSET,
    difficulty_level=_UNSET,
    strategy_config=_UNSET,
    is_active=_UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """部分更新教学策略；None 表示显式清空可空字段。"""

    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("strategy_id 必须是非空字符串")

    values = {}

    if name is not _UNSET:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name 必须是非空字符串")
        values["name"] = name.strip()

    if description is not _UNSET:
        if not isinstance(description, str):
            raise ValueError("description 必须是字符串")
        values["description"] = description

    if subject_id is not _UNSET:
        if subject_id is not None and (
            isinstance(subject_id, bool) or not isinstance(subject_id, int)
        ):
            raise ValueError("subject_id 必须是整数或 None")
        values["subject_id"] = subject_id

    if method_version_id is not _UNSET:
        if method_version_id is not None:
            if not isinstance(method_version_id, str) or not method_version_id.strip():
                raise ValueError("method_version_id 必须是非空字符串或 None")
            method_version_id = method_version_id.strip()
        values["method_version_id"] = method_version_id

    if strategy_type is not _UNSET:
        if strategy_type not in _TEACHING_STRATEGY_TYPES:
            raise ValueError("无效的 strategy_type")
        values["strategy_type"] = strategy_type

    for field, value in (
        ("target_stage", target_stage),
        ("target_grade", target_grade),
    ):
        if value is not _UNSET:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")
            values[field] = value

    if difficulty_level is not _UNSET:
        if difficulty_level is not None and (
            isinstance(difficulty_level, bool)
            or not isinstance(difficulty_level, int)
            or not 1 <= difficulty_level <= 5
        ):
            raise ValueError("difficulty_level 必须是 1 到 5 之间的整数或 None")
        values["difficulty_level"] = difficulty_level

    if strategy_config is not _UNSET:
        if not isinstance(strategy_config, dict):
            raise ValueError("strategy_config 必须是 JSON 对象（dict）")
        values["strategy_config"] = encode_json(strategy_config)

    if is_active is not _UNSET:
        if not isinstance(is_active, bool):
            raise ValueError("is_active 必须是 bool")
        values["is_active"] = int(is_active)

    if not values:
        return get_teaching_strategy(strategy_id, db_path)

    assignments = ", ".join(f"{column} = ?" for column in values)
    params = list(values.values()) + [strategy_id.strip()]

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE teaching_strategies
            SET {assignments}
            WHERE id = ?
            """,
            params,
        )

        if cursor.rowcount == 0:
            return None

        row = conn.execute(
            "SELECT * FROM teaching_strategies WHERE id = ?",
            (strategy_id.strip(),),
        ).fetchone()

        return _decode_teaching_strategy(row)


def set_teaching_strategy_active(
    strategy_id: str,
    is_active: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """启用或停用教学策略。"""

    if not isinstance(is_active, bool):
        raise ValueError("is_active 必须是 bool")

    return update_teaching_strategy(
        strategy_id,
        is_active=is_active,
        db_path=db_path,
    )


# ============================================================
# Teaching Sessions DAL
# ============================================================

_TEACHING_SESSION_STATUSES = {
    "active", "paused", "completed", "abandoned"
}

_TEACHING_SESSION_MODES = {
    "adaptive", "explanation", "practice",
    "inquiry", "review", "mixed"
}

_TEACHING_SESSION_JSON_FIELDS = {
    "initial_state",
    "final_state",
    "strategy_snapshot",
    "learner_model_snapshot",
}


def _decode_teaching_session(row):
    """将教学会话记录转换为字典并解码 JSON 快照。"""
    if row is None:
        return None

    result = dict(row)
    for field in _TEACHING_SESSION_JSON_FIELDS:
        result[field] = decode_json(result.get(field), default={})
    return result


def create_teaching_session(
    profile_id: int,
    subject_id: int,
    *,
    chapter_id: str | None = None,
    knowledge_point_id: str | None = None,
    study_session_id: str | None = None,
    strategy_id: str | None = None,
    status: str = "active",
    teaching_mode: str = "adaptive",
    teaching_goal: str = "",
    initial_state: dict | None = None,
    final_state: dict | None = None,
    strategy_snapshot: dict | None = None,
    learner_model_snapshot: dict | None = None,
    started_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """创建教学会话。"""

    for field, value in (
        ("profile_id", profile_id),
        ("subject_id", subject_id),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} 必须是整数")

    for field in (
        "chapter_id",
        "knowledge_point_id",
        "study_session_id",
        "strategy_id",
    ):
        value = locals()[field]
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} 必须是非空字符串或 None")
            if field == "chapter_id":
                chapter_id = value.strip()
            elif field == "knowledge_point_id":
                knowledge_point_id = value.strip()
            elif field == "study_session_id":
                study_session_id = value.strip()
            elif field == "strategy_id":
                strategy_id = value.strip()

    if status not in {"active", "paused", "abandoned"}:
        raise ValueError(
            "创建教学会话时 status 只能是 active、paused 或 abandoned；"
            "completed 必须通过 complete_teaching_session() 设置"
        )

    if teaching_mode not in _TEACHING_SESSION_MODES:
        raise ValueError("无效的 teaching_mode")

    if not isinstance(teaching_goal, str):
        raise ValueError("teaching_goal 必须是字符串")

    snapshots = {
        "initial_state": {} if initial_state is None else initial_state,
        "final_state": {} if final_state is None else final_state,
        "strategy_snapshot": (
            {} if strategy_snapshot is None else strategy_snapshot
        ),
        "learner_model_snapshot": (
            {} if learner_model_snapshot is None else learner_model_snapshot
        ),
    }

    for field, value in snapshots.items():
        if not isinstance(value, dict):
            raise ValueError(f"{field} 必须是 dict")

    if started_at is not None:
        if not isinstance(started_at, str) or not started_at.strip():
            raise ValueError("started_at 必须是非空字符串或 None")

    encoded = {
        field: encode_json(value)
        for field, value in snapshots.items()
    }

    session_id = generate_id()

    with write_transaction(db_path) as conn:
        if started_at is None:
            conn.execute(
                """
                INSERT INTO teaching_sessions (
                    id, profile_id, subject_id, chapter_id,
                    knowledge_point_id, study_session_id, strategy_id,
                    status, teaching_mode, teaching_goal,
                    initial_state, final_state, strategy_snapshot,
                    learner_model_snapshot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, profile_id, subject_id, chapter_id,
                    knowledge_point_id, study_session_id, strategy_id,
                    status, teaching_mode, teaching_goal,
                    encoded["initial_state"],
                    encoded["final_state"],
                    encoded["strategy_snapshot"],
                    encoded["learner_model_snapshot"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO teaching_sessions (
                    id, profile_id, subject_id, chapter_id,
                    knowledge_point_id, study_session_id, strategy_id,
                    status, teaching_mode, teaching_goal,
                    initial_state, final_state, strategy_snapshot,
                    learner_model_snapshot, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, profile_id, subject_id, chapter_id,
                    knowledge_point_id, study_session_id, strategy_id,
                    status, teaching_mode, teaching_goal,
                    encoded["initial_state"],
                    encoded["final_state"],
                    encoded["strategy_snapshot"],
                    encoded["learner_model_snapshot"],
                    started_at.strip(),
                ),
            )

        row = conn.execute(
            "SELECT * FROM teaching_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        return _decode_teaching_session(row)


def get_teaching_session(
    session_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按 ID 获取教学会话。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()
        return _decode_teaching_session(row)
    finally:
        conn.close()


def list_teaching_sessions(
    *,
    profile_id: int | None = None,
    subject_id: int | None = None,
    status: str | None = None,
    teaching_mode: str | None = None,
    strategy_id: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """按条件筛选教学会话，按开始时间倒序分页。"""

    for field, value in (
        ("profile_id", profile_id),
        ("subject_id", subject_id),
    ):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} 必须是整数或 None")

    if status is not None and status not in _TEACHING_SESSION_STATUSES:
        raise ValueError("无效的 status")

    if (
        teaching_mode is not None
        and teaching_mode not in _TEACHING_SESSION_MODES
    ):
        raise ValueError("无效的 teaching_mode")

    if strategy_id is not None:
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise ValueError("strategy_id 必须是非空字符串或 None")
        strategy_id = strategy_id.strip()

    for field, value in (
        ("started_after", started_after),
        ("started_before", started_before),
    ):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} 必须是非空字符串或 None")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = []
    params = []

    for column, value in (
        ("profile_id", profile_id),
        ("subject_id", subject_id),
        ("status", status),
        ("teaching_mode", teaching_mode),
        ("strategy_id", strategy_id),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value)

    if started_after is not None:
        conditions.append("started_at >= ?")
        params.append(started_after.strip())

    if started_before is not None:
        conditions.append("started_at <= ?")
        params.append(started_before.strip())

    where_sql = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    params.extend((limit, offset))

    conn = connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM teaching_sessions
            {where_sql}
            ORDER BY started_at DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()

        return [_decode_teaching_session(row) for row in rows]
    finally:
        conn.close()


def update_teaching_session(
    session_id: str,
    *,
    chapter_id=_UNSET,
    knowledge_point_id=_UNSET,
    study_session_id=_UNSET,
    strategy_id=_UNSET,
    status=_UNSET,
    teaching_mode=_UNSET,
    teaching_goal=_UNSET,
    initial_state=_UNSET,
    final_state=_UNSET,
    strategy_snapshot=_UNSET,
    learner_model_snapshot=_UNSET,
    ended_at=_UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """部分更新教学会话；使用 None 清空允许为空的字段。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")

    values = {}

    nullable_text_fields = (
        "chapter_id",
        "knowledge_point_id",
        "study_session_id",
        "strategy_id",
    )

    for field in nullable_text_fields:
        value = locals()[field]
        if value is not _UNSET:
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field} 必须是非空字符串或 None")
                value = value.strip()
            values[field] = value

    if status is not _UNSET:
        if status not in {"active", "paused", "abandoned"}:
            raise ValueError(
                "update_teaching_session() 不允许设置 completed；"
                "请使用 complete_teaching_session()"
            )
        values["status"] = status

    if teaching_mode is not _UNSET:
        if teaching_mode not in _TEACHING_SESSION_MODES:
            raise ValueError("无效的 teaching_mode")
        values["teaching_mode"] = teaching_mode

    if teaching_goal is not _UNSET:
        if not isinstance(teaching_goal, str):
            raise ValueError("teaching_goal 必须是字符串")
        values["teaching_goal"] = teaching_goal

    for field in _TEACHING_SESSION_JSON_FIELDS:
        value = locals()[field]
        if value is not _UNSET:
            if not isinstance(value, dict):
                raise ValueError(f"{field} 必须是 dict")
            values[field] = encode_json(value)

    if ended_at is not _UNSET:
        if ended_at is not None:
            if not isinstance(ended_at, str) or not ended_at.strip():
                raise ValueError("ended_at 必须是非空字符串或 None")
            ended_at = ended_at.strip()
        values["ended_at"] = ended_at

    if not values:
        return get_teaching_session(session_id, db_path=db_path)

    assignments = ", ".join(f"{field} = ?" for field in values)
    params = list(values.values()) + [session_id.strip()]

    with write_transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT status FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()

        if existing is None:
            return None

        if existing["status"] == "completed":
            raise ValueError("已完成的教学会话不能再更新")

        conn.execute(
            f"""
            UPDATE teaching_sessions
            SET {assignments}
            WHERE id = ?
            """,
            params,
        )

        row = conn.execute(
            "SELECT * FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()

        return _decode_teaching_session(row)


def complete_teaching_session(
    session_id: str,
    *,
    final_state: dict | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """原子完成教学会话并记录最终状态和结束时间。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")

    if final_state is None:
        final_state = {}

    if not isinstance(final_state, dict):
        raise ValueError("final_state 必须是 dict")

    final_state_json = encode_json(final_state)

    with write_transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT status FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()

        if existing is None:
            return None

        if existing["status"] == "completed":
            raise ValueError("教学会话已经完成")

        conn.execute(
            """
            UPDATE teaching_sessions
            SET status = 'completed',
                final_state = ?,
                ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id = ?
            """,
            (final_state_json, session_id.strip()),
        )

        row = conn.execute(
            "SELECT * FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()

        return _decode_teaching_session(row)

_TEACHING_SESSION_EVENT_TYPES = {
    "explanation", "question", "answer", "feedback",
    "exercise", "hint", "assessment", "strategy_change",
    "student_signal", "other",
}

_TEACHING_SESSION_EVENT_ACTORS = {"muse", "student", "system"}


def _decode_teaching_session_event(row: sqlite3.Row) -> dict:
    """解码教学会话事件记录。"""
    event = dict(row)
    event["structured_data"] = decode_json(
        event.get("structured_data"), default={}
    )
    return event



def add_teaching_session_event(
    teaching_session_id: str,
    event_type: str,
    *,
    actor: str = "muse",
    content: str = "",
    structured_data: dict | None = None,
    knowledge_point_id: str | None = None,
    sequence_no: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """追加教学会话事件；未指定序号时自动分配下一个序号。"""

    if not isinstance(teaching_session_id, str) or not teaching_session_id.strip():
        raise ValueError("teaching_session_id 必须是非空字符串")

    if not isinstance(event_type, str) or event_type not in _TEACHING_SESSION_EVENT_TYPES:
        raise ValueError("无效的 event_type")

    if not isinstance(actor, str) or actor not in _TEACHING_SESSION_EVENT_ACTORS:
        raise ValueError("无效的 actor")

    if not isinstance(content, str):
        raise ValueError("content 必须是字符串")

    if structured_data is None:
        structured_data = {}
    if not isinstance(structured_data, dict):
        raise ValueError("structured_data 必须是 dict")

    if knowledge_point_id is not None:
        if not isinstance(knowledge_point_id, str) or not knowledge_point_id.strip():
            raise ValueError("knowledge_point_id 必须是非空字符串或 None")
        knowledge_point_id = knowledge_point_id.strip()

    if sequence_no is not None:
        if isinstance(sequence_no, bool) or not isinstance(sequence_no, int) or sequence_no < 1:
            raise ValueError("sequence_no 必须是正整数")

    structured_json = encode_json(structured_data)

    with write_transaction(db_path) as conn:
        if sequence_no is None:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(sequence_no), 0) + 1
                FROM teaching_session_events
                WHERE teaching_session_id = ?
                """,
                (teaching_session_id.strip(),),
            ).fetchone()
            assigned_sequence = row[0]
        else:
            assigned_sequence = sequence_no

        cursor = conn.execute(
            """
            INSERT INTO teaching_session_events (
                teaching_session_id,
                event_type,
                actor,
                content,
                structured_data,
                knowledge_point_id,
                sequence_no
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                teaching_session_id.strip(),
                event_type,
                actor,
                content,
                structured_json,
                knowledge_point_id,
                assigned_sequence,
            ),
        )

        row = conn.execute(
            "SELECT * FROM teaching_session_events WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

        return _decode_teaching_session_event(row)


def get_teaching_session_event(
    event_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """根据事件 ID 获取教学会话事件。"""

    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
        raise ValueError("event_id 必须是正整数")

    if not Path(db_path).is_file():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM teaching_session_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return _decode_teaching_session_event(row) if row else None
    finally:
        conn.close()


def list_teaching_session_events(
    teaching_session_id: str,
    *,
    event_type: str | None = None,
    actor: str | None = None,
    after_sequence: int | None = None,
    before_sequence: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """按会话查询事件，支持类型、参与者、序号范围和分页筛选。"""

    if not isinstance(teaching_session_id, str) or not teaching_session_id.strip():
        raise ValueError("teaching_session_id 必须是非空字符串")

    if event_type is not None:
        if not isinstance(event_type, str) or event_type not in _TEACHING_SESSION_EVENT_TYPES:
            raise ValueError("无效的 event_type")

    if actor is not None:
        if not isinstance(actor, str) or actor not in _TEACHING_SESSION_EVENT_ACTORS:
            raise ValueError("无效的 actor")

    for name, value in (
        ("after_sequence", after_sequence),
        ("before_sequence", before_sequence),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"{name} 必须是正整数或 None")

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit 必须是正整数")

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    if not Path(db_path).is_file():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    conditions = ["teaching_session_id = ?"]
    params = [teaching_session_id.strip()]

    if event_type is not None:
        conditions.append("event_type = ?")
        params.append(event_type)

    if actor is not None:
        conditions.append("actor = ?")
        params.append(actor)

    if after_sequence is not None:
        conditions.append("sequence_no > ?")
        params.append(after_sequence)

    if before_sequence is not None:
        conditions.append("sequence_no < ?")
        params.append(before_sequence)

    params.extend([limit, offset])
    sql = f"""
        SELECT *
        FROM teaching_session_events
        WHERE {" AND ".join(conditions)}
        ORDER BY sequence_no ASC
        LIMIT ? OFFSET ?
    """

    conn = connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_decode_teaching_session_event(row) for row in rows]
    finally:
        conn.close()


def get_teaching_session_history(
    session_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """一次读取教学会话及其完整事件时间线。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")

    if not Path(db_path).is_file():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    conn = connect(db_path)
    try:
        session_row = conn.execute(
            "SELECT * FROM teaching_sessions WHERE id = ?",
            (session_id.strip(),),
        ).fetchone()

        if session_row is None:
            return None

        event_rows = conn.execute(
            """
            SELECT *
            FROM teaching_session_events
            WHERE teaching_session_id = ?
            ORDER BY sequence_no ASC
            """,
            (session_id.strip(),),
        ).fetchall()

        session = _decode_teaching_session(session_row)
        events = [
            _decode_teaching_session_event(row)
            for row in event_rows
        ]

        return {
            "session": session,
            "events": events,
            "event_count": len(events),
        }
    finally:
        conn.close()


def get_teaching_session_history_delta(
    session_id: str,
    *,
    after_sequence: int = 0,
    limit: int = 100,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """增量读取教学会话事件，支持断点续读和分页。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")

    if (
        isinstance(after_sequence, bool)
        or not isinstance(after_sequence, int)
        or after_sequence < 0
    ):
        raise ValueError("after_sequence 必须是非负整数")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 500
    ):
        raise ValueError("limit 必须是 1 到 500 之间的整数")

    if not Path(db_path).is_file():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    normalized_id = session_id.strip()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")

        session_row = conn.execute(
            "SELECT id FROM teaching_sessions WHERE id = ?",
            (normalized_id,),
        ).fetchone()

        if session_row is None:
            return None

        max_sequence = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0)
            FROM teaching_session_events
            WHERE teaching_session_id = ?
            """,
            (normalized_id,),
        ).fetchone()[0]

        rows = conn.execute(
            """
            SELECT *
            FROM teaching_session_events
            WHERE teaching_session_id = ?
              AND sequence_no > ?
            ORDER BY sequence_no ASC
            LIMIT ?
            """,
            (normalized_id, after_sequence, limit + 1),
        ).fetchall()

        has_more = len(rows) > limit
        events = [
            _decode_teaching_session_event(row)
            for row in rows[:limit]
        ]

        next_sequence = (
            events[-1]["sequence_no"] if events else after_sequence
        )

        return {
            "session_id": normalized_id,
            "events": events,
            "event_count": len(events),
            "after_sequence": after_sequence,
            "next_sequence": next_sequence,
            "max_sequence": max_sequence,
            "has_more": has_more,
        }
    finally:
        conn.close()


_LEARNER_MASTERY_CHECK_TYPES = {
    "chapter", "comprehensive", "cross_chapter", "spaced_review",
}
_LEARNER_MASTERY_RESULTS = {
    "mastered", "partial", "not_mastered", "insufficient",
}


def _decode_learner_mastery_check(row: sqlite3.Row) -> dict:
    """解码学习掌握度评估记录。"""
    item = dict(row)
    item["evidence"] = decode_json(item.pop("evidence_json"), default={})
    return item


def create_learner_mastery_check(
    learner_profile_id: str,
    check_type: str,
    *,
    knowledge_point_id: str | None = None,
    chapter_id: str | None = None,
    teaching_session_id: str | None = None,
    result: str = "insufficient",
    mastery_score: float | None = None,
    confidence_score: float | None = None,
    evidence_sufficiency: str = "insufficient",
    question_count: int = 0,
    correct_count: int = 0,
    independent_performance: bool | None = None,
    evidence: dict | None = None,
    checked_at: str | None = None,
    next_review_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """追加一条学习掌握度评估记录。"""

    if not isinstance(learner_profile_id, str) or not learner_profile_id.strip():
        raise ValueError("learner_profile_id 必须是非空字符串")

    if not isinstance(check_type, str) or check_type not in _LEARNER_MASTERY_CHECK_TYPES:
        raise ValueError("无效的 check_type")

    if not isinstance(result, str) or result not in _LEARNER_MASTERY_RESULTS:
        raise ValueError("无效的 result")

    for name, value in (
        ("mastery_score", mastery_score),
        ("confidence_score", confidence_score),
    ):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} 必须是 0 到 1 之间的数字或 None")
            if not 0 <= value <= 1:
                raise ValueError(f"{name} 必须是 0 到 1 之间的数字或 None")

    if not isinstance(evidence_sufficiency, str) or evidence_sufficiency not in {"sufficient", "insufficient"}:
        raise ValueError("无效的 evidence_sufficiency")

    for name, value in (
        ("question_count", question_count),
        ("correct_count", correct_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} 必须是非负整数")

    if correct_count > question_count:
        raise ValueError("correct_count 不能大于 question_count")

    if independent_performance is not None and not isinstance(
        independent_performance, bool
    ):
        raise ValueError("independent_performance 必须是 bool 或 None")

    for name, value in (
        ("knowledge_point_id", knowledge_point_id),
        ("chapter_id", chapter_id),
        ("teaching_session_id", teaching_session_id),
    ):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串或 None")

    if checked_at is not None and not isinstance(checked_at, str):
        raise ValueError("checked_at 必须是字符串或 None")

    if next_review_at is not None and not isinstance(next_review_at, str):
        raise ValueError("next_review_at 必须是字符串或 None")

    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ValueError("evidence 必须是 dict")

    record_id = generate_id()
    evidence_json = encode_json(evidence)

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO learner_mastery_checks (
                id, learner_profile_id, knowledge_point_id, chapter_id,
                teaching_session_id, check_type, result, mastery_score,
                confidence_score, evidence_sufficiency, question_count,
                correct_count, independent_performance, evidence_json,
                checked_at, next_review_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ','now')), ?)
            """,
            (
                record_id,
                learner_profile_id.strip(),
                knowledge_point_id.strip() if knowledge_point_id else None,
                chapter_id.strip() if chapter_id else None,
                teaching_session_id.strip() if teaching_session_id else None,
                check_type,
                result,
                mastery_score,
                confidence_score,
                evidence_sufficiency,
                question_count,
                correct_count,
                None if independent_performance is None
                else int(independent_performance),
                evidence_json,
                checked_at,
                next_review_at,
            ),
        )

        row = conn.execute(
            "SELECT * FROM learner_mastery_checks WHERE id = ?",
            (record_id,),
        ).fetchone()

        return _decode_learner_mastery_check(row)


def get_learner_mastery_check(
    check_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    if not isinstance(check_id, str) or not check_id.strip():
        raise ValueError("check_id 必须是非空字符串")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM learner_mastery_checks WHERE id = ?",
            (check_id.strip(),),
        ).fetchone()
        return _decode_learner_mastery_check(row) if row else None
    finally:
        conn.close()


def list_learner_mastery_checks(
    learner_profile_id: str,
    *,
    check_type: str | None = None,
    result: str | None = None,
    knowledge_point_id: str | None = None,
    chapter_id: str | None = None,
    teaching_session_id: str | None = None,
    evidence_sufficiency: str | None = None,
    checked_after: str | None = None,
    checked_before: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    if not isinstance(learner_profile_id, str) or not learner_profile_id.strip():
        raise ValueError("learner_profile_id 必须是非空字符串")

    enum_filters = (
        ("check_type", check_type, _LEARNER_MASTERY_CHECK_TYPES),
        ("result", result, _LEARNER_MASTERY_RESULTS),
        (
            "evidence_sufficiency",
            evidence_sufficiency,
            {"sufficient", "insufficient"},
        ),
    )
    for name, value, allowed in enum_filters:
        if value is not None and (
            not isinstance(value, str) or value not in allowed
        ):
            raise ValueError(f"{name} 不合法")

    text_filters = (
        ("knowledge_point_id", knowledge_point_id),
        ("chapter_id", chapter_id),
        ("teaching_session_id", teaching_session_id),
        ("checked_after", checked_after),
        ("checked_before", checked_before),
    )
    for name, value in text_filters:
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"{name} 必须是非空字符串或 None")

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必须是 1 到 500 的整数")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须是非负整数")

    conditions = ["learner_profile_id = ?"]
    params = [learner_profile_id.strip()]

    for column, value in (
        ("check_type", check_type),
        ("result", result),
        ("knowledge_point_id", knowledge_point_id),
        ("chapter_id", chapter_id),
        ("teaching_session_id", teaching_session_id),
        ("evidence_sufficiency", evidence_sufficiency),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value.strip() if isinstance(value, str) else value)

    if checked_after is not None:
        conditions.append("checked_at >= ?")
        params.append(checked_after.strip())
    if checked_before is not None:
        conditions.append("checked_at <= ?")
        params.append(checked_before.strip())

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    sql = f"""
        SELECT *
        FROM learner_mastery_checks
        WHERE {" AND ".join(conditions)}
        ORDER BY checked_at DESC, id DESC
        LIMIT ? OFFSET ?
    """
    params.extend((limit, offset))

    conn = connect(path)
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_decode_learner_mastery_check(row) for row in rows]
    finally:
        conn.close()


def _require_v4_read(conn: sqlite3.Connection) -> None:
    """V4 学段目录读取接口的版本保护。"""
    require_schema_version(conn, CURRENT_SCHEMA_VERSION)


def list_education_stages(
    include_inactive: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """列出教育学段，默认只返回启用项。"""
    if not isinstance(include_inactive, bool):
        raise ValueError("include_inactive 必须是布尔值")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    with database(path) as conn:
        _require_v4_read(conn)
        where = "" if include_inactive else "WHERE is_active = 1"
        rows = conn.execute(
            f"""
            SELECT id, code, name, sort_order, is_active, created_at
            FROM education_stages
            {where}
            ORDER BY sort_order, id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_education_stage_by_code(
    code: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按学段编码获取学段。"""
    code = _validate_catalog_code(code, "学段编码")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    with database(path) as conn:
        _require_v4_read(conn)
        row = conn.execute(
            """
            SELECT id, code, name, sort_order, is_active, created_at
            FROM education_stages
            WHERE code = ?
            """,
            (code.strip(),),
        ).fetchone()
        return dict(row) if row else None


def list_subjects_for_stage(
    stage_code: str,
    include_inactive: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """按学段查询学科，并返回学段内排序。"""
    stage_code = _validate_catalog_code(stage_code, "学段编码")
    if not isinstance(include_inactive, bool):
        raise ValueError("include_inactive 必须是布尔值")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    active_filter = "" if include_inactive else "AND ss.is_active = 1 AND s.is_active = 1 AND es.is_active = 1"

    with database(path) as conn:
        _require_v4_read(conn)
        rows = conn.execute(
            f"""
            SELECT
                s.id, s.code, s.name, s.sort_order,
                s.is_active AS subject_is_active,
                ss.sort_order AS stage_sort_order,
                ss.is_active AS stage_subject_is_active
            FROM education_stage_subjects ss
            JOIN education_stages es
                ON es.id = ss.education_stage_id
            JOIN subjects s
                ON s.id = ss.subject_id
            WHERE es.code = ?
                {active_filter}
            ORDER BY ss.sort_order, s.id
            """,
            (stage_code.strip(),),
        ).fetchall()
        return [dict(row) for row in rows]


def list_stages_for_subject(
    subject_code: str,
    include_inactive: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """查询某门学科所属的学段。"""
    subject_code = _validate_catalog_code(subject_code, "学科编码")
    if not isinstance(include_inactive, bool):
        raise ValueError("include_inactive 必须是布尔值")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")

    active_filter = "" if include_inactive else "AND ss.is_active = 1 AND s.is_active = 1 AND es.is_active = 1"

    with database(path) as conn:
        _require_v4_read(conn)
        rows = conn.execute(
            f"""
            SELECT
                es.id, es.code, es.name, es.sort_order,
                es.is_active,
                ss.sort_order AS stage_subject_sort_order,
                ss.is_active AS stage_subject_is_active
            FROM education_stage_subjects ss
            JOIN education_stages es
                ON es.id = ss.education_stage_id
            JOIN subjects s
                ON s.id = ss.subject_id
            WHERE s.code = ?
                {active_filter}
            ORDER BY es.sort_order, es.id
            """,
            (subject_code.strip(),),
        ).fetchall()
        return [dict(row) for row in rows]


def _validate_catalog_code(value: str, field: str = "编码") -> str:
    """校验可扩展目录编码。"""
    if not isinstance(value, str):
        raise ValueError(f"{field}必须是字符串")
    value = value.strip()
    if not 2 <= len(value) <= 64:
        raise ValueError(f"{field}长度必须为 2 到 64")
    if not value[0].islower() or not value[0].isascii() or not value[0].isalpha():
        raise ValueError(f"{field}必须以小写英文字母开头")
    if any(
        not (c.isascii() and (c.islower() or c.isdigit() or c == "_"))
        for c in value
    ):
        raise ValueError(f"{field}只能包含小写字母、数字和下划线")
    return value


def _validate_catalog_name(value: str, field: str = "名称") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}不能为空")
    value = value.strip()
    if len(value) > 100:
        raise ValueError(f"{field}不能超过 100 个字符")
    return value


def _validate_catalog_id(value: int, field: str = "ID") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field}必须是正整数")
    return value


def _validate_catalog_order(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("sort_order 必须是非负整数")
    return value


def create_education_stage(
    code: str,
    name: str,
    sort_order: int = 0,
    is_active: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """创建教育学段，返回新学段 ID。"""
    code = _validate_catalog_code(code, "学段编码")
    name = _validate_catalog_name(name, "学段名称")
    sort_order = _validate_catalog_order(sort_order)
    if not isinstance(is_active, bool):
        raise ValueError("is_active 必须是布尔值")

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO education_stages(code, name, sort_order, is_active)
            VALUES (?, ?, ?, ?)
            """,
            (code, name, sort_order, int(is_active)),
        )
        return cursor.lastrowid


def update_education_stage(
    stage_id: int,
    *,
    name: str | object = _UNSET,
    sort_order: int | object = _UNSET,
    is_active: bool | object = _UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """更新学段；未提供的字段保持不变。"""
    stage_id = _validate_catalog_id(stage_id, "学段 ID")
    updates = []

    if name is not _UNSET:
        updates.append(("name", _validate_catalog_name(name, "学段名称")))
    if sort_order is not _UNSET:
        updates.append(("sort_order", _validate_catalog_order(sort_order)))
    if is_active is not _UNSET:
        if not isinstance(is_active, bool):
            raise ValueError("is_active 必须是布尔值")
        updates.append(("is_active", int(is_active)))

    if not updates:
        raise ValueError("至少提供一个需要更新的字段")

    assignments = ", ".join(f"{column} = ?" for column, _ in updates)
    values = [value for _, value in updates]

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE education_stages SET {assignments} WHERE id = ?",
            (*values, stage_id),
        )
        return cursor.rowcount > 0


def set_education_stage_active(
    stage_id: int,
    is_active: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """启用或停用学段。"""
    return update_education_stage(
        stage_id, is_active=is_active, db_path=db_path
    )


def create_subject(
    code: str,
    name: str,
    sort_order: int = 0,
    is_active: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """创建全局学科，返回新学科 ID。"""
    code = _validate_catalog_code(code, "学科编码")
    name = _validate_catalog_name(name, "学科名称")
    sort_order = _validate_catalog_order(sort_order)
    if not isinstance(is_active, bool):
        raise ValueError("is_active 必须是布尔值")

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO subjects(code, name, sort_order, is_active)
            VALUES (?, ?, ?, ?)
            """,
            (code, name, sort_order, int(is_active)),
        )
        return cursor.lastrowid


def get_subject_by_code(
    code: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    """按学科编码查询全局学科。"""
    code = _validate_catalog_code(code, "学科编码")
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    with database(db_path) as conn:
        _require_v4_read(conn)
        row = conn.execute(
            """
            SELECT id, code, name, sort_order, is_active
            FROM subjects
            WHERE code = ?
            """,
            (code,),
        ).fetchone()
        return dict(row) if row else None


def add_subject_to_stage(
    education_stage_id: int,
    subject_id: int,
    sort_order: int = 0,
    is_active: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """将全局学科关联到学段；重复关联由数据库唯一约束拒绝。"""
    education_stage_id = _validate_catalog_id(education_stage_id, "学段 ID")
    subject_id = _validate_catalog_id(subject_id, "学科 ID")
    sort_order = _validate_catalog_order(sort_order)
    if not isinstance(is_active, bool):
        raise ValueError("is_active 必须是布尔值")

    with write_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO education_stage_subjects
                (education_stage_id, subject_id, sort_order, is_active)
            VALUES (?, ?, ?, ?)
            """,
            (education_stage_id, subject_id, sort_order, int(is_active)),
        )
        return True


def update_stage_subject(
    education_stage_id: int,
    subject_id: int,
    *,
    sort_order: int | object = _UNSET,
    is_active: bool | object = _UNSET,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """更新学段内学科关联的排序或启用状态。"""
    education_stage_id = _validate_catalog_id(education_stage_id, "学段 ID")
    subject_id = _validate_catalog_id(subject_id, "学科 ID")
    updates = []

    if sort_order is not _UNSET:
        updates.append(("sort_order", _validate_catalog_order(sort_order)))
    if is_active is not _UNSET:
        if not isinstance(is_active, bool):
            raise ValueError("is_active 必须是布尔值")
        updates.append(("is_active", int(is_active)))

    if not updates:
        raise ValueError("至少提供一个需要更新的字段")

    assignments = ", ".join(f"{column} = ?" for column, _ in updates)
    values = [value for _, value in updates]

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE education_stage_subjects
            SET {assignments}
            WHERE education_stage_id = ? AND subject_id = ?
            """,
            (*values, education_stage_id, subject_id),
        )
        return cursor.rowcount > 0


def remove_subject_from_stage(
    education_stage_id: int,
    subject_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """移除学段与学科的关联，不删除全局学科。"""
    education_stage_id = _validate_catalog_id(education_stage_id, "学段 ID")
    subject_id = _validate_catalog_id(subject_id, "学科 ID")

    with write_transaction(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM education_stage_subjects
            WHERE education_stage_id = ? AND subject_id = ?
            """,
            (education_stage_id, subject_id),
        )
        return cursor.rowcount > 0
