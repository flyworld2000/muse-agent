"""Muse learning database V2 migration.

仅负责数据库结构升级，不启动服务，不操作其他容器。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from learning_db import initialize_database

DB_PATH = Path(
    os.environ.get("LEARNING_DB_PATH", "/data/learning.sqlite3")
)

V2_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS questions (
        id TEXT PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        question_type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        answer_key TEXT NOT NULL DEFAULT '',
        explanation TEXT NOT NULL DEFAULT '',
        difficulty INTEGER NOT NULL DEFAULT 1
            CHECK (difficulty BETWEEN 1 AND 5),
        source_kind TEXT NOT NULL DEFAULT 'ai_generated'
            CHECK (source_kind IN (
                'textbook', 'uploaded_material',
                'ai_generated', 'teacher_added'
            )),
        source_document_id TEXT,
        source_page INTEGER,
        education_stage TEXT
            CHECK (education_stage IS NULL OR education_stage IN (
                'primary', 'junior_high', 'senior_high'
            )),
        grade_level TEXT,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(subject_id) REFERENCES subjects(id),
        FOREIGN KEY(source_document_id) REFERENCES documents(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS question_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id TEXT NOT NULL,
        option_key TEXT NOT NULL,
        option_content TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        UNIQUE(question_id, option_key),
        FOREIGN KEY(question_id)
            REFERENCES questions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS question_knowledge_points (
        question_id TEXT NOT NULL,
        knowledge_point_id TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0,
        PRIMARY KEY(question_id, knowledge_point_id),
        FOREIGN KEY(question_id)
            REFERENCES questions(id) ON DELETE CASCADE,
        FOREIGN KEY(knowledge_point_id)
            REFERENCES knowledge_points(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS question_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(question_id)
            REFERENCES questions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_records (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        question_id TEXT NOT NULL,
        question_snapshot TEXT NOT NULL,
        user_answer TEXT NOT NULL DEFAULT '',
        correct_answer_snapshot TEXT NOT NULL DEFAULT '',
        is_correct INTEGER CHECK (
            is_correct IS NULL OR is_correct IN (0, 1)
        ),
        score REAL NOT NULL DEFAULT 0,
        max_score REAL NOT NULL DEFAULT 0,
        time_spent_seconds INTEGER NOT NULL DEFAULT 0,
        answered_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(question_id) REFERENCES questions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wrong_questions (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        question_id TEXT NOT NULL,
        first_answer_record_id TEXT,
        latest_answer_record_id TEXT,
        error_type TEXT NOT NULL DEFAULT 'unknown',
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'mastered', 'archived')),
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        last_wrong_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        mastered_at TEXT,
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(question_id) REFERENCES questions(id),
        FOREIGN KEY(first_answer_record_id)
            REFERENCES answer_records(id),
        FOREIGN KEY(latest_answer_record_id)
            REFERENCES answer_records(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wrong_question_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wrong_question_id TEXT NOT NULL,
        note_type TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(wrong_question_id)
            REFERENCES wrong_questions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_plans (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        knowledge_point_id TEXT,
        wrong_question_id TEXT,
        scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'completed', 'skipped')),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        CHECK (
            knowledge_point_id IS NOT NULL
            OR wrong_question_id IS NOT NULL
        ),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(knowledge_point_id)
            REFERENCES knowledge_points(id),
        FOREIGN KEY(wrong_question_id)
            REFERENCES wrong_questions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_records (
        id TEXT PRIMARY KEY,
        review_plan_id TEXT NOT NULL,
        profile_id INTEGER NOT NULL,
        result TEXT NOT NULL
            CHECK (result IN ('again', 'hard', 'good', 'easy')),
        score REAL,
        feedback TEXT NOT NULL DEFAULT '',
        reviewed_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(review_plan_id) REFERENCES review_plans(id),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS courses (
        id TEXT PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        education_stage TEXT
            CHECK (education_stage IS NULL OR education_stage IN (
                'primary', 'junior_high', 'senior_high'
            )),
        grade_level TEXT,
        source_kind TEXT NOT NULL DEFAULT 'ai_generated',
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft', 'active', 'completed', 'archived')),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_lessons (
        id TEXT PRIMARY KEY,
        course_id TEXT NOT NULL,
        chapter_id TEXT,
        title TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(course_id)
            REFERENCES courses(id) ON DELETE CASCADE,
        FOREIGN KEY(chapter_id) REFERENCES chapters(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_sessions (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        course_id TEXT,
        started_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        ended_at TEXT,
        duration_seconds INTEGER NOT NULL DEFAULT 0,
        summary TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        knowledge_point_id TEXT,
        reference_id TEXT,
        content TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(session_id)
            REFERENCES study_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(knowledge_point_id)
            REFERENCES knowledge_points(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exams (
        id TEXT PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        exam_type TEXT NOT NULL
            CHECK (exam_type IN ('chapter', 'comprehensive')),
        education_stage TEXT
            CHECK (education_stage IS NULL OR education_stage IN (
                'primary', 'junior_high', 'senior_high'
            )),
        grade_level TEXT,
        duration_minutes INTEGER,
        total_score REAL NOT NULL DEFAULT 100,
        settings_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft', 'published', 'archived')),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_chapters (
        exam_id TEXT NOT NULL,
        chapter_id TEXT NOT NULL,
        PRIMARY KEY(exam_id, chapter_id),
        FOREIGN KEY(exam_id)
            REFERENCES exams(id) ON DELETE CASCADE,
        FOREIGN KEY(chapter_id) REFERENCES chapters(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id TEXT NOT NULL,
        question_id TEXT NOT NULL,
        question_snapshot TEXT NOT NULL,
        score REAL NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(exam_id)
            REFERENCES exams(id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions(id),
        UNIQUE(exam_id, sort_order)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_attempts (
        id TEXT PRIMARY KEY,
        exam_id TEXT NOT NULL,
        profile_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'in_progress'
            CHECK (status IN (
                'in_progress', 'submitted', 'graded', 'cancelled'
            )),
        total_score REAL,
        max_score REAL,
        started_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        submitted_at TEXT,
        FOREIGN KEY(exam_id) REFERENCES exams(id),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id TEXT NOT NULL,
        exam_question_id INTEGER NOT NULL,
        user_answer TEXT NOT NULL DEFAULT '',
        correct_answer_snapshot TEXT NOT NULL DEFAULT '',
        is_correct INTEGER CHECK (
            is_correct IS NULL OR is_correct IN (0, 1)
        ),
        score REAL NOT NULL DEFAULT 0,
        feedback TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(attempt_id)
            REFERENCES exam_attempts(id) ON DELETE CASCADE,
        FOREIGN KEY(exam_question_id)
            REFERENCES exam_questions(id),
        UNIQUE(attempt_id, exam_question_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vocabulary (
        id TEXT PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        word TEXT NOT NULL,
        phonetic TEXT NOT NULL DEFAULT '',
        meaning TEXT NOT NULL DEFAULT '',
        example_sentence TEXT NOT NULL DEFAULT '',
        audio_path TEXT,
        source_kind TEXT NOT NULL DEFAULT 'ai_supplement',
        UNIQUE(subject_id, word),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vocabulary_progress (
        profile_id INTEGER NOT NULL,
        vocabulary_id TEXT NOT NULL,
        mastery_score REAL NOT NULL DEFAULT 0
            CHECK (mastery_score BETWEEN 0 AND 1),
        review_count INTEGER NOT NULL DEFAULT 0,
        correct_count INTEGER NOT NULL DEFAULT 0,
        next_review_at TEXT,
        updated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(profile_id, vocabulary_id),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY(vocabulary_id)
            REFERENCES vocabulary(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grammar_topics (
        id TEXT PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        explanation TEXT NOT NULL DEFAULT '',
        examples TEXT NOT NULL DEFAULT '',
        source_kind TEXT NOT NULL DEFAULT 'ai_supplement',
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS language_practice (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        practice_type TEXT NOT NULL
            CHECK (practice_type IN (
                'listening', 'speaking', 'reading', 'writing'
            )),
        prompt TEXT NOT NULL DEFAULT '',
        response TEXT NOT NULL DEFAULT '',
        feedback TEXT NOT NULL DEFAULT '',
        score REAL,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_reports (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER,
        report_type TEXT NOT NULL,
        period_start TEXT,
        period_end TEXT,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY(profile_id)
            REFERENCES learning_profiles(id),
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_wrong_active_unique
        ON wrong_questions(profile_id, question_id)
        WHERE status = 'active'
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_exam_answer_insert_check
    BEFORE INSERT ON exam_answers
    FOR EACH ROW
    WHEN
        (SELECT exam_id FROM exam_attempts WHERE id = NEW.attempt_id)
        IS NOT
        (SELECT exam_id FROM exam_questions WHERE id = NEW.exam_question_id)
    BEGIN
        SELECT RAISE(ABORT, 'exam question does not belong to this attempt');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_exam_answer_update_check
    BEFORE UPDATE OF attempt_id, exam_question_id ON exam_answers
    FOR EACH ROW
    WHEN
        (SELECT exam_id FROM exam_attempts WHERE id = NEW.attempt_id)
        IS NOT
        (SELECT exam_id FROM exam_questions WHERE id = NEW.exam_question_id)
    BEGIN
        SELECT RAISE(ABORT, 'exam question does not belong to this attempt');
    END
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_questions_subject
        ON questions(subject_id, difficulty)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_answers_profile
        ON answer_records(profile_id, answered_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_wrong_profile
        ON wrong_questions(profile_id, status, last_wrong_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_schedule
        ON review_plans(profile_id, status, scheduled_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_exam_attempts_profile
        ON exam_attempts(profile_id, started_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_study_sessions_profile
        ON study_sessions(profile_id, started_at)
    """,
]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def migrate() -> None:
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        print("首次创建学习数据库，先初始化 V1 结构")
        initialize_database(DB_PATH)

    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")

    try:
        if not table_exists(conn, "schema_meta"):
            raise RuntimeError("数据库缺少 schema_meta，停止迁移")

        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()

        current_version = int(row[0]) if row else 0

        if current_version > 2:
            raise RuntimeError(
                f"数据库版本 {current_version} 高于本脚本版本 2"
            )

        if current_version == 2:
            print("数据库已经是 V2，无需重复迁移")
            return

        if current_version != 1:
            raise RuntimeError(
                f"不支持从数据库版本 {current_version} 迁移"
            )

        conn.execute("BEGIN IMMEDIATE")

        try:
            # 为学习者和教材增加学段、年级信息。
            for table in ("learning_profiles", "documents"):
                columns = {
                    item[1]
                    for item in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }

                if "education_stage" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN education_stage TEXT"
                    )

                if "grade_level" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN grade_level TEXT"
                    )

            for statement in V2_SCHEMA:
                conn.execute(statement)

            conn.execute(
                """
                UPDATE schema_meta
                SET value='2'
                WHERE key='schema_version'
                """
            )

            # 在提交事务之前检查外键；失败时可以完整回滚。
            violations = conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violations:
                raise RuntimeError(
                    f"外键检查失败，迁移已回滚: {violations}"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        print("V2 数据库迁移成功")
        print("数据库版本: 2")

        tables = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
            """
        ).fetchall()

        print("当前数据表数量:", len(tables))
        for item in tables:
            print(" -", item[0])

        print("外键检查通过（已在事务提交前完成）")

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
