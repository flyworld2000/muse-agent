"""Muse Agent V2 -> V3 database migration.

V3 adds autonomous educational research, teaching methods,
adaptive teaching sessions, evaluation and autonomy audit logs.
Only Python standard library is required.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "learning.sqlite3"
DB_PATH = Path(os.environ.get("LEARNING_DB_PATH", str(DEFAULT_DB)))
TARGET_VERSION = 3


V3_SCHEMA = (
    """
    CREATE TABLE research_jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL DEFAULT 'teaching_method_discovery',
        topic TEXT NOT NULL,
        subject_id INTEGER,
        education_stage TEXT,
        grade_level TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN (
                'pending', 'running', 'completed', 'failed', 'cancelled'
            )),
        search_plan TEXT NOT NULL DEFAULT '',
        result_summary TEXT NOT NULL DEFAULT '',
        error_message TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_research_sources (
        id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL DEFAULT 'web'
            CHECK (source_type IN (
                'web', 'paper', 'book', 'course', 'video',
                'teacher_case', 'official_resource', 'other'
            )),
        title TEXT NOT NULL,
        url TEXT,
        canonical_url TEXT,
        content_hash TEXT,
        publisher TEXT,
        author TEXT,
        published_at TEXT,
        accessed_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        language TEXT,
        reliability_score REAL
            CHECK (
                reliability_score IS NULL
                OR reliability_score BETWEEN 0 AND 1
            ),
        source_quality TEXT NOT NULL DEFAULT 'unreviewed'
            CHECK (source_quality IN (
                'unreviewed', 'low', 'medium', 'high', 'verified'
            )),
        extracted_content TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE research_job_sources (
        research_job_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        relevance_score REAL
            CHECK (
                relevance_score IS NULL
                OR relevance_score BETWEEN 0 AND 1
            ),
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (research_job_id, source_id),
        FOREIGN KEY (research_job_id) REFERENCES research_jobs(id)
            ON DELETE CASCADE,
        FOREIGN KEY (source_id) REFERENCES teaching_research_sources(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE teaching_methods (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        subject_id INTEGER,
        method_category TEXT NOT NULL DEFAULT 'general',
        status TEXT NOT NULL DEFAULT 'candidate'
            CHECK (status IN (
                'candidate', 'active', 'disabled', 'deprecated'
            )),
        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),
        discovery_source TEXT NOT NULL DEFAULT 'research'
            CHECK (discovery_source IN (
                'research', 'manual', 'model_generated', 'imported'
            )),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_method_versions (
        id TEXT PRIMARY KEY,
        method_id TEXT NOT NULL,
        version_no INTEGER NOT NULL CHECK (version_no > 0),
        summary TEXT NOT NULL DEFAULT '',
        teaching_steps TEXT NOT NULL DEFAULT '[]',
        applicable_stages TEXT NOT NULL DEFAULT '[]',
        applicable_grades TEXT NOT NULL DEFAULT '[]',
        applicable_subjects TEXT NOT NULL DEFAULT '[]',
        applicable_scenarios TEXT NOT NULL DEFAULT '[]',
        prerequisites TEXT NOT NULL DEFAULT '[]',
        limitations TEXT NOT NULL DEFAULT '[]',
        expected_outcomes TEXT NOT NULL DEFAULT '[]',
        evidence_summary TEXT NOT NULL DEFAULT '',
        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),
        review_status TEXT NOT NULL DEFAULT 'candidate'
            CHECK (review_status IN (
                'candidate', 'approved', 'rejected', 'superseded'
            )),
        created_by TEXT NOT NULL DEFAULT 'muse',
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE (method_id, version_no),
        FOREIGN KEY (method_id) REFERENCES teaching_methods(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE teaching_method_evidence (
        id TEXT PRIMARY KEY,
        method_version_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        evidence_type TEXT NOT NULL DEFAULT 'supporting',
        finding TEXT NOT NULL DEFAULT '',
        limitations TEXT NOT NULL DEFAULT '',
        evidence_strength TEXT NOT NULL DEFAULT 'unknown'
            CHECK (evidence_strength IN (
                'very_low', 'low', 'moderate', 'high', 'very_high',
                'unknown'
            )),
        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (method_version_id)
            REFERENCES teaching_method_versions(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (source_id)
            REFERENCES teaching_research_sources(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE teaching_strategies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        subject_id INTEGER,
        method_version_id TEXT,
        strategy_type TEXT NOT NULL DEFAULT 'adaptive'
            CHECK (strategy_type IN (
                'explanation', 'guided_practice', 'inquiry',
                'practice', 'review', 'adaptive', 'mixed'
            )),
        target_stage TEXT,
        target_grade TEXT,
        difficulty_level INTEGER
            CHECK (
                difficulty_level IS NULL
                OR difficulty_level BETWEEN 1 AND 5
            ),
        strategy_config TEXT NOT NULL DEFAULT '{}',
        is_active INTEGER NOT NULL DEFAULT 1
            CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE SET NULL,
        FOREIGN KEY (method_version_id)
            REFERENCES teaching_method_versions(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_sessions (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        chapter_id TEXT,
        knowledge_point_id TEXT,
        study_session_id TEXT,
        strategy_id TEXT,
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN (
                'active', 'paused', 'completed', 'abandoned'
            )),
        teaching_mode TEXT NOT NULL DEFAULT 'adaptive'
            CHECK (teaching_mode IN (
                'adaptive', 'explanation', 'practice',
                'inquiry', 'review', 'mixed'
            )),
        teaching_goal TEXT NOT NULL DEFAULT '',
        initial_state TEXT NOT NULL DEFAULT '{}',
        final_state TEXT NOT NULL DEFAULT '{}',
        strategy_snapshot TEXT NOT NULL DEFAULT '{}',
        learner_model_snapshot TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        ended_at TEXT,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (profile_id) REFERENCES learning_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (chapter_id) REFERENCES chapters(id)
            ON DELETE SET NULL,
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
            ON DELETE SET NULL,
        FOREIGN KEY (study_session_id) REFERENCES study_sessions(id)
            ON DELETE SET NULL,
        FOREIGN KEY (strategy_id) REFERENCES teaching_strategies(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_session_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teaching_session_id TEXT NOT NULL,
        event_type TEXT NOT NULL
            CHECK (event_type IN (
                'explanation', 'question', 'answer', 'feedback',
                'exercise', 'hint', 'assessment', 'strategy_change',
                'student_signal', 'other'
            )),
        actor TEXT NOT NULL DEFAULT 'muse'
            CHECK (actor IN ('muse', 'student', 'system')),
        content TEXT NOT NULL DEFAULT '',
        structured_data TEXT NOT NULL DEFAULT '{}',
        knowledge_point_id TEXT,
        sequence_no INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE (teaching_session_id, sequence_no),
        FOREIGN KEY (teaching_session_id) REFERENCES teaching_sessions(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_method_evaluations (
        id TEXT PRIMARY KEY,
        teaching_session_id TEXT NOT NULL,
        method_version_id TEXT,
        strategy_id TEXT,
        evaluation_type TEXT NOT NULL DEFAULT 'session',
        learning_gain REAL CHECK (
            learning_gain IS NULL OR learning_gain BETWEEN -1 AND 1
        ),
        mastery_before REAL CHECK (
            mastery_before IS NULL OR mastery_before BETWEEN 0 AND 1
        ),
        mastery_after REAL CHECK (
            mastery_after IS NULL OR mastery_after BETWEEN 0 AND 1
        ),
        engagement_score REAL CHECK (
            engagement_score IS NULL OR engagement_score BETWEEN 0 AND 1
        ),
        completion_score REAL CHECK (
            completion_score IS NULL OR completion_score BETWEEN 0 AND 1
        ),
        outcome TEXT NOT NULL DEFAULT 'unknown'
            CHECK (outcome IN (
                'positive', 'neutral', 'negative', 'inconclusive', 'unknown'
            )),
        evaluation_summary TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        evaluated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (teaching_session_id) REFERENCES teaching_sessions(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (method_version_id)
            REFERENCES teaching_method_versions(id)
            ON DELETE SET NULL,
        FOREIGN KEY (strategy_id) REFERENCES teaching_strategies(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_autonomy_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teaching_session_id TEXT,
        research_job_id TEXT,
        action_type TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        method_version_id TEXT,
        strategy_id TEXT,
        input_snapshot TEXT NOT NULL DEFAULT '{}',
        outcome_snapshot TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (teaching_session_id) REFERENCES teaching_sessions(id)
            ON DELETE SET NULL,
        FOREIGN KEY (research_job_id) REFERENCES research_jobs(id)
            ON DELETE SET NULL,
        FOREIGN KEY (method_version_id)
            REFERENCES teaching_method_versions(id)
            ON DELETE SET NULL,
        FOREIGN KEY (strategy_id) REFERENCES teaching_strategies(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE learner_teaching_profiles (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,

        learning_state TEXT NOT NULL DEFAULT '{}',
        knowledge_mastery TEXT NOT NULL DEFAULT '{}',
        strengths TEXT NOT NULL DEFAULT '[]',
        difficulties TEXT NOT NULL DEFAULT '[]',
        learning_preferences TEXT NOT NULL DEFAULT '{}',
        learning_pace TEXT NOT NULL DEFAULT '{}',
        motivation_observations TEXT NOT NULL DEFAULT '{}',

        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),

        observation_count INTEGER NOT NULL DEFAULT 0
            CHECK (observation_count >= 0),

        last_assessed_at TEXT,
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

        UNIQUE (profile_id, subject_id),

        FOREIGN KEY (profile_id) REFERENCES learning_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE learner_method_stats (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        method_version_id TEXT NOT NULL,

        sessions_count INTEGER NOT NULL DEFAULT 0
            CHECK (sessions_count >= 0),

        positive_count INTEGER NOT NULL DEFAULT 0
            CHECK (positive_count >= 0),

        neutral_count INTEGER NOT NULL DEFAULT 0
            CHECK (neutral_count >= 0),

        negative_count INTEGER NOT NULL DEFAULT 0
            CHECK (negative_count >= 0),

        inconclusive_count INTEGER NOT NULL DEFAULT 0
            CHECK (inconclusive_count >= 0),

        average_learning_gain REAL CHECK (
            average_learning_gain IS NULL
            OR average_learning_gain BETWEEN -1 AND 1
        ),
        average_engagement REAL CHECK (
            average_engagement IS NULL
            OR average_engagement BETWEEN 0 AND 1
        ),
        average_completion REAL CHECK (
            average_completion IS NULL
            OR average_completion BETWEEN 0 AND 1
        ),

        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),

        last_used_at TEXT,
        last_evaluated_at TEXT,
        updated_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

        UNIQUE (profile_id, subject_id, method_version_id),

        FOREIGN KEY (profile_id) REFERENCES learning_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (subject_id) REFERENCES subjects(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (method_version_id)
            REFERENCES teaching_method_versions(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE learner_profile_history (
        id TEXT PRIMARY KEY,
        learner_profile_id TEXT NOT NULL,
        change_type TEXT NOT NULL DEFAULT 'assessment',
        previous_state TEXT NOT NULL DEFAULT '{}',
        new_state TEXT NOT NULL DEFAULT '{}',
        change_reason TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        teaching_session_id TEXT,
        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (learner_profile_id)
            REFERENCES learner_teaching_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (teaching_session_id)
            REFERENCES teaching_sessions(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE learner_mastery_checks (
        id TEXT PRIMARY KEY,
        learner_profile_id TEXT NOT NULL,
        knowledge_point_id TEXT,
        chapter_id TEXT,
        teaching_session_id TEXT,

        check_type TEXT NOT NULL
            CHECK (check_type IN (
                'chapter', 'comprehensive',
                'cross_chapter', 'spaced_review'
            )),

        result TEXT NOT NULL DEFAULT 'insufficient'
            CHECK (result IN (
                'mastered', 'partial',
                'not_mastered', 'insufficient'
            )),

        mastery_score REAL
            CHECK (
                mastery_score IS NULL
                OR mastery_score BETWEEN 0 AND 1
            ),

        confidence_score REAL
            CHECK (
                confidence_score IS NULL
                OR confidence_score BETWEEN 0 AND 1
            ),

        evidence_sufficiency TEXT NOT NULL DEFAULT 'insufficient'
            CHECK (evidence_sufficiency IN (
                'sufficient', 'insufficient'
            )),

        question_count INTEGER NOT NULL DEFAULT 0
            CHECK (question_count >= 0),

        correct_count INTEGER NOT NULL DEFAULT 0
            CHECK (
                correct_count >= 0
                AND correct_count <= question_count
            ),

        independent_performance INTEGER
            CHECK (
                independent_performance IS NULL
                OR independent_performance IN (0, 1)
            ),

        evidence_json TEXT NOT NULL DEFAULT '{}',
        checked_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        next_review_at TEXT,

        FOREIGN KEY (learner_profile_id)
            REFERENCES learner_teaching_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (knowledge_point_id)
            REFERENCES knowledge_points(id)
            ON DELETE SET NULL,
        FOREIGN KEY (chapter_id)
            REFERENCES chapters(id)
            ON DELETE SET NULL,
        FOREIGN KEY (teaching_session_id)
            REFERENCES teaching_sessions(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE learner_teaching_feedback (
        id TEXT PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        teaching_session_id TEXT,

        feedback_type TEXT NOT NULL DEFAULT 'method_request'
            CHECK (feedback_type IN (
                'method_request', 'difficulty',
                'pace', 'explanation',
                'practice', 'satisfaction', 'other'
            )),

        student_request TEXT NOT NULL DEFAULT '',
        satisfaction_score REAL
            CHECK (
                satisfaction_score IS NULL
                OR satisfaction_score BETWEEN 0 AND 1
            ),

        accepted INTEGER
            CHECK (
                accepted IS NULL
                OR accepted IN (0, 1)
            ),

        response_summary TEXT NOT NULL DEFAULT '',
        preference_snapshot TEXT NOT NULL DEFAULT '{}',

        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

        FOREIGN KEY (profile_id)
            REFERENCES learning_profiles(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (subject_id)
            REFERENCES subjects(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (teaching_session_id)
            REFERENCES teaching_sessions(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE teaching_strategy_adjustments (
        id TEXT PRIMARY KEY,
        teaching_session_id TEXT NOT NULL,
        previous_strategy_id TEXT,
        new_strategy_id TEXT,

        adjustment_reason TEXT NOT NULL DEFAULT '',
        trigger_source TEXT NOT NULL DEFAULT 'performance'
            CHECK (trigger_source IN (
                'student_request', 'performance',
                'teacher', 'research', 'other'
            )),

        feedback_id TEXT,
        previous_state TEXT NOT NULL DEFAULT '{}',
        new_state TEXT NOT NULL DEFAULT '{}',
        outcome_json TEXT NOT NULL DEFAULT '{}',

        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

        FOREIGN KEY (teaching_session_id)
            REFERENCES teaching_sessions(id)
            ON DELETE RESTRICT,
        FOREIGN KEY (previous_strategy_id)
            REFERENCES teaching_strategies(id)
            ON DELETE SET NULL,
        FOREIGN KEY (new_strategy_id)
            REFERENCES teaching_strategies(id)
            ON DELETE SET NULL,
        FOREIGN KEY (feedback_id)
            REFERENCES learner_teaching_feedback(id)
            ON DELETE SET NULL
    )
    """,
)


V3_INDEXES = (
    "CREATE INDEX idx_profile_history_profile ON learner_profile_history(learner_profile_id, created_at)",
    "CREATE INDEX idx_mastery_checks_profile ON learner_mastery_checks(learner_profile_id, checked_at)",
    "CREATE INDEX idx_teaching_feedback_profile ON learner_teaching_feedback(profile_id, subject_id, created_at)",
    "CREATE INDEX idx_strategy_adjustments_session ON teaching_strategy_adjustments(teaching_session_id, created_at)",

    "CREATE INDEX idx_research_jobs_status ON research_jobs(status, created_at)",
    "CREATE INDEX idx_research_jobs_subject ON research_jobs(subject_id)",
    "CREATE INDEX idx_research_sources_quality ON teaching_research_sources(source_quality)",
    "CREATE INDEX idx_research_sources_hash ON teaching_research_sources(content_hash)",
    "CREATE INDEX idx_job_sources_source ON research_job_sources(source_id)",
    "CREATE INDEX idx_methods_status ON teaching_methods(status, subject_id)",
    "CREATE INDEX idx_method_versions_method ON teaching_method_versions(method_id, version_no)",
    "CREATE INDEX idx_method_versions_review ON teaching_method_versions(review_status)",
    "CREATE INDEX idx_method_evidence_version ON teaching_method_evidence(method_version_id)",
    "CREATE INDEX idx_method_evidence_source ON teaching_method_evidence(source_id)",
    "CREATE INDEX idx_strategies_subject ON teaching_strategies(subject_id, is_active)",
    "CREATE INDEX idx_teaching_sessions_profile ON teaching_sessions(profile_id, started_at)",
    "CREATE INDEX idx_teaching_sessions_subject ON teaching_sessions(subject_id, started_at)",
    "CREATE INDEX idx_teaching_sessions_status ON teaching_sessions(status)",
    "CREATE INDEX idx_session_events_session ON teaching_session_events(teaching_session_id, sequence_no)",
    "CREATE INDEX idx_method_evaluations_session ON teaching_method_evaluations(teaching_session_id)",
    "CREATE INDEX idx_method_evaluations_method ON teaching_method_evaluations(method_version_id)",
    "CREATE INDEX idx_autonomy_logs_session ON teaching_autonomy_logs(teaching_session_id, created_at)",
    "CREATE INDEX idx_autonomy_logs_research ON teaching_autonomy_logs(research_job_id)",
    "CREATE INDEX idx_learner_profiles_profile_subject ON learner_teaching_profiles(profile_id, subject_id)",
    "CREATE INDEX idx_learner_method_stats_profile_subject ON learner_method_stats(profile_id, subject_id)",
    "CREATE INDEX idx_learner_method_stats_method ON learner_method_stats(method_version_id)",
)


V3_TRIGGERS = (
    "CREATE TRIGGER trg_profile_history_no_update BEFORE UPDATE ON learner_profile_history BEGIN SELECT RAISE(ABORT, 'learner profile history is append-only'); END",
    "CREATE TRIGGER trg_profile_history_no_delete BEFORE DELETE ON learner_profile_history BEGIN SELECT RAISE(ABORT, 'learner profile history is append-only'); END",
    "CREATE TRIGGER trg_mastery_checks_no_update BEFORE UPDATE ON learner_mastery_checks BEGIN SELECT RAISE(ABORT, 'mastery checks are append-only'); END",
    "CREATE TRIGGER trg_mastery_checks_no_delete BEFORE DELETE ON learner_mastery_checks BEGIN SELECT RAISE(ABORT, 'mastery checks are append-only'); END",
    "CREATE TRIGGER trg_teaching_feedback_no_update BEFORE UPDATE ON learner_teaching_feedback BEGIN SELECT RAISE(ABORT, 'teaching feedback is append-only'); END",
    "CREATE TRIGGER trg_teaching_feedback_no_delete BEFORE DELETE ON learner_teaching_feedback BEGIN SELECT RAISE(ABORT, 'teaching feedback is append-only'); END",
    "CREATE TRIGGER trg_strategy_adjustments_no_update BEFORE UPDATE ON teaching_strategy_adjustments BEGIN SELECT RAISE(ABORT, 'strategy adjustments are append-only'); END",
    "CREATE TRIGGER trg_strategy_adjustments_no_delete BEFORE DELETE ON teaching_strategy_adjustments BEGIN SELECT RAISE(ABORT, 'strategy adjustments are append-only'); END",

    """
    CREATE TRIGGER trg_teaching_event_no_update
    BEFORE UPDATE ON teaching_session_events
    BEGIN
        SELECT RAISE(ABORT, 'teaching session events are append-only');
    END
    """,
    """
    CREATE TRIGGER trg_teaching_event_no_delete
    BEFORE DELETE ON teaching_session_events
    BEGIN
        SELECT RAISE(ABORT, 'teaching session events are append-only');
    END
    """,
)


def migrate() -> None:
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        raise RuntimeError(
            f"数据库不存在或为空：{DB_PATH}。"
            "V3 迁移不负责创建 V1/V2 数据库。"
        )

    conn = sqlite3.connect(DB_PATH, timeout=15)
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
                f"数据库版本 {current_version} 高于本脚本版本 {TARGET_VERSION}"
            )

        if current_version == TARGET_VERSION:
            print("数据库已经是 V3，无需重复迁移")
            return

        if current_version != 2:
            raise RuntimeError(
                f"只支持从 V2 升级到 V3，当前版本为 {current_version}"
            )

        conn.execute("BEGIN IMMEDIATE")

        try:
            for statement in V3_SCHEMA:
                conn.execute(statement)

            for statement in V3_INDEXES:
                conn.execute(statement)

            for statement in V3_TRIGGERS:
                conn.execute(statement)

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

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        tables = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        print("V3 数据库迁移成功")
        print("数据库版本:", TARGET_VERSION)
        print("业务数据表数量:", len(tables))
        print("新增 V3 数据表数量:", len(V3_SCHEMA))
        print("新增索引数量:", len(V3_INDEXES))
        print("新增触发器数量:", len(V3_TRIGGERS))
        print("外键检查通过")

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
