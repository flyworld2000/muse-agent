import sqlite3

from app.learning_db import (
    list_education_stages,
    list_subjects_for_stage,
    list_stages_for_subject,
    get_subject_by_code,
    get_education_stage_by_code,
)


def test_v4_migration_and_catalog_basics(v4_db):
    conn = sqlite3.connect(v4_db)
    try:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == "4"

        assert conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

        assert conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []
    finally:
        conn.close()

    stages = list_education_stages(db_path=v4_db)
    assert [stage["code"] for stage in stages] == [
        "primary", "senior_high", "university"
    ]

    assert len(list_subjects_for_stage("primary", db_path=v4_db)) == 4
    assert len(list_subjects_for_stage("senior_high", db_path=v4_db)) == 10
    assert len(list_subjects_for_stage("university", db_path=v4_db)) == 1

    assert [stage["code"] for stage in list_stages_for_subject(
        "english", db_path=v4_db
    )] == ["primary", "senior_high"]

    assert get_subject_by_code("morality_law", db_path=v4_db)["name"] == "道德与法治"
    assert get_education_stage_by_code("university", db_path=v4_db)["name"] == "大学"


from app.learning_db import (
    create_education_stage,
    update_education_stage,
    set_education_stage_active,
    create_subject,
    add_subject_to_stage,
    update_stage_subject,
    remove_subject_from_stage,
)


def test_v4_catalog_write_operations(v4_db):
    stage_id = create_education_stage(
        "test_stage", "测试学段", 100, db_path=v4_db
    )
    subject_id = create_subject(
        "test_subject", "测试学科", 99, db_path=v4_db
    )

    assert stage_id > 0
    assert subject_id > 0

    assert add_subject_to_stage(
        stage_id, subject_id, 1, db_path=v4_db
    ) is True

    assert [item["code"] for item in list_subjects_for_stage(
        "test_stage", db_path=v4_db
    )] == ["test_subject"]

    assert update_stage_subject(
        stage_id, subject_id, sort_order=8, db_path=v4_db
    ) is True

    assert update_stage_subject(
        stage_id, subject_id, is_active=False, db_path=v4_db
    ) is True

    assert list_subjects_for_stage("test_stage", db_path=v4_db) == []
    assert len(list_subjects_for_stage(
        "test_stage", include_inactive=True, db_path=v4_db
    )) == 1

    assert remove_subject_from_stage(
        stage_id, subject_id, db_path=v4_db
    ) is True
    assert get_subject_by_code("test_subject", db_path=v4_db) is not None

    assert update_education_stage(
        stage_id, name="更新后的测试学段", db_path=v4_db
    ) is True
    assert set_education_stage_active(
        stage_id, False, db_path=v4_db
    ) is True
    assert get_education_stage_by_code(
        "test_stage", db_path=v4_db
    )["name"] == "更新后的测试学段"
    assert get_education_stage_by_code(
        "test_stage", db_path=v4_db
    )["is_active"] == 0


import pytest
import sqlite3


def test_v4_duplicate_records_are_rejected(v4_db):
    stage_id = create_education_stage(
        "duplicate_stage", "重复测试学段", db_path=v4_db
    )
    subject_id = create_subject(
        "duplicate_subject", "重复测试学科", db_path=v4_db
    )

    with pytest.raises(sqlite3.IntegrityError):
        create_education_stage(
            "duplicate_stage", "重复测试学段", db_path=v4_db
        )

    with pytest.raises(sqlite3.IntegrityError):
        create_subject(
            "duplicate_subject", "重复测试学科", db_path=v4_db
        )

    add_subject_to_stage(stage_id, subject_id, db_path=v4_db)

    with pytest.raises(sqlite3.IntegrityError):
        add_subject_to_stage(stage_id, subject_id, db_path=v4_db)

    with sqlite3.connect(v4_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM education_stages WHERE code = ?",
            ("duplicate_stage",),
        ).fetchone()[0] == 1

        assert conn.execute(
            "SELECT COUNT(*) FROM subjects WHERE code = ?",
            ("duplicate_subject",),
        ).fetchone()[0] == 1

        assert conn.execute(
            """
            SELECT COUNT(*) FROM education_stage_subjects
            WHERE education_stage_id = ? AND subject_id = ?
            """,
            (stage_id, subject_id),
        ).fetchone()[0] == 1


def test_v4_missing_records_and_empty_updates(v4_db):
    stage_id = create_education_stage(
        "boundary_stage", "边界测试学段", db_path=v4_db
    )

    assert update_education_stage(
        99999999, name="不存在", db_path=v4_db
    ) is False

    assert update_stage_subject(
        99999999, 99999999, sort_order=1, db_path=v4_db
    ) is False

    assert remove_subject_from_stage(
        99999999, 99999999, db_path=v4_db
    ) is False

    with pytest.raises(ValueError):
        update_education_stage(stage_id, db_path=v4_db)

    with pytest.raises(ValueError):
        update_stage_subject(
            stage_id, 99999999, db_path=v4_db
        )


@pytest.mark.parametrize(
    "invalid_code",
    ["A1", "bad-code", "中文", "a", "", None, 123],
)
def test_v4_invalid_catalog_codes_are_rejected(v4_db, invalid_code):
    with pytest.raises(ValueError):
        create_education_stage(
            invalid_code, "非法编码测试", db_path=v4_db
        )


@pytest.mark.parametrize(
    "invalid_name",
    ["", "   ", "名" * 101, None, 123],
)
def test_v4_invalid_catalog_names_are_rejected(v4_db, invalid_name):
    with pytest.raises(ValueError):
        create_education_stage(
            "invalid_name_stage", invalid_name, db_path=v4_db
        )


def test_v4_catalog_names_are_trimmed(v4_db):
    stage_id = create_education_stage(
        "trimmed_stage", "  测试学段  ", db_path=v4_db
    )
    stage = get_education_stage_by_code("trimmed_stage", db_path=v4_db)
    assert stage["id"] == stage_id
    assert stage["name"] == "测试学段"


@pytest.mark.parametrize("invalid_id", [0, -1, True, False, 1.5, "1", None])
def test_v4_invalid_catalog_ids_are_rejected(v4_db, invalid_id):
    with pytest.raises(ValueError):
        add_subject_to_stage(
            invalid_id, 1, db_path=v4_db
        )

    with pytest.raises(ValueError):
        add_subject_to_stage(
            1, invalid_id, db_path=v4_db
        )


@pytest.mark.parametrize("invalid_order", [-1, True, False, 1.5, "1", None])
def test_v4_invalid_sort_orders_are_rejected(v4_db, invalid_order):
    with pytest.raises(ValueError):
        add_subject_to_stage(
            1, 1, sort_order=invalid_order, db_path=v4_db
        )


@pytest.mark.parametrize("invalid_active", [0, 1, "true", None])
def test_v4_invalid_active_flags_are_rejected(v4_db, invalid_active):
    with pytest.raises(ValueError):
        add_subject_to_stage(
            1, 1, is_active=invalid_active, db_path=v4_db
        )
