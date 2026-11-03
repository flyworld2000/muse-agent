import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from candidate import validate_candidate, candidate_digest


TASK_ID = "task_test_001"
CANDIDATE_ID = "candidate_test_001"
PLAN_HASH = "a" * 64
RELATIVE_PATH = "app/learning_db.py"
CONTENT = b"print('candidate test')\n"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.candidates_root = Path(self.temp.name) / "candidates"
        self.task_dir = self.candidates_root / TASK_ID
        self.root = self.task_dir / CANDIDATE_ID
        (self.root / "files" / "app").mkdir(parents=True)

        self.file_path = self.root / "files" / RELATIVE_PATH
        self.file_path.write_bytes(CONTENT)

        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, **overrides):
        manifest = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "approved_plan_sha256": PLAN_HASH,
            "candidate_id": CANDIDATE_ID,
            "files": [{
                "path": RELATIVE_PATH,
                "size": len(CONTENT),
                "sha256": hashlib.sha256(CONTENT).hexdigest(),
            }],
        }
        manifest.update(overrides)
        (self.root / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def validate(self, **overrides):
        root_fd = os.open(
            self.candidates_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        try:
            args = {
                "expected_task_id": TASK_ID,
                "expected_plan_sha256": PLAN_HASH,
                "expected_candidate_id": CANDIDATE_ID,
            }
            args.update(overrides)
            return validate_candidate(root_fd, **args)
        finally:
            os.close(root_fd)

    def test_valid_candidate(self):
        result = self.validate()
        self.assertEqual(result[RELATIVE_PATH], CONTENT)

    def test_hash_mismatch(self):
        self.file_path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.validate()

    def test_path_traversal_rejected(self):
        self.write_manifest(files=[{
            "path": "../outside",
            "size": 1,
            "sha256": "a" * 64,
        }])
        with self.assertRaises(ValueError):
            self.validate()

    def test_file_symlink_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_bytes(CONTENT)
        self.file_path.unlink()
        self.file_path.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_intermediate_directory_symlink_rejected(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "learning_db.py").write_bytes(CONTENT)

        app_dir = self.root / "files" / "app"
        (app_dir / "learning_db.py").unlink()
        app_dir.rmdir()
        app_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_wrong_task_id_rejected(self):
        with self.assertRaises((ValueError, OSError)):
            self.validate(
                expected_task_id="another_task",
                expected_plan_sha256=PLAN_HASH,
                expected_candidate_id=CANDIDATE_ID,
            )

    def test_wrong_plan_hash_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(
                expected_task_id=TASK_ID,
                expected_plan_sha256="b" * 64,
                expected_candidate_id=CANDIDATE_ID,
            )

    def test_wrong_candidate_id_rejected(self):
        with self.assertRaises((ValueError, OSError)):
            self.validate(
                expected_task_id=TASK_ID,
                expected_plan_sha256=PLAN_HASH,
                expected_candidate_id="another_candidate",
            )

    def test_task_directory_symlink_rejected(self):
        real_task = self.candidates_root / "real_task"
        self.task_dir.rename(real_task)
        self.task_dir.symlink_to(real_task, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_candidate_directory_symlink_rejected(self):
        real_candidate = self.task_dir / "real_candidate"
        self.root.rename(real_candidate)
        self.root.symlink_to(real_candidate, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_extra_root_file_rejected(self):
        (self.root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.validate()

    def test_undeclared_file_rejected(self):
        extra = self.root / "files" / "app" / "unexpected.py"
        extra.write_text("unexpected", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.validate()

    def test_extra_empty_directory_rejected(self):
        (self.root / "files" / "unexpected").mkdir()
        with self.assertRaises(ValueError):
            self.validate()

    def test_empty_files_rejected(self):
        self.write_manifest(files=[])
        with self.assertRaises(ValueError):
            self.validate()


    def test_candidate_digest_is_order_independent(self):
        first = {
            "app/learning_db.py": b"version_a",
            "tests/conftest.py": b"test_data",
        }
        second = {
            "tests/conftest.py": b"test_data",
            "app/learning_db.py": b"version_a",
        }
        self.assertEqual(candidate_digest(first), candidate_digest(second))

    def test_candidate_digest_changes_with_content(self):
        first = {"app/learning_db.py": b"version_a"}
        second = {"app/learning_db.py": b"version_b"}
        self.assertNotEqual(candidate_digest(first), candidate_digest(second))

    def test_candidate_digest_rejects_empty_files(self):
        with self.assertRaises(ValueError):
            candidate_digest({})

    def test_candidate_digest_rejects_non_bytes_content(self):
        with self.assertRaises(ValueError):
            candidate_digest({"app/learning_db.py": "not bytes"})


if __name__ == "__main__":
    unittest.main()
