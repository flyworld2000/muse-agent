import hashlib
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proposal import build_proposal
from candidate import candidate_digest


class ProposalTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.proposals = self.base / "proposals"

        (self.project / "app").mkdir(parents=True)
        (self.project / "tests").mkdir()

        self.relative = "app/learning_db.py"
        self.original = b"VALUE = 1\n"
        self.modified = b"VALUE = 2\n"

        (self.project / self.relative).write_bytes(self.original)

    def build_proposal(self, changes):
        return build_proposal(
            self.project,
            self.proposals,
            changes,
            task_id="task-test-001",
            approved_plan_sha256="a" * 64,
            candidate_id="candidate-test-001",
            expected_candidate_sha256=candidate_digest(changes),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_proposal_does_not_modify_source(self):
        manifest = self.build_proposal(
            {self.relative: self.modified},
        )

        self.assertEqual(
            (self.project / self.relative).read_bytes(),
            self.original,
        )
        self.assertEqual(manifest["status"], "proposed")

    def test_manifest_hashes_can_be_recalculated(self):
        manifest = self.build_proposal(
            {self.relative: self.modified},
        )

        item = manifest["files"][self.relative]

        self.assertEqual(
            item["original_sha256"],
            hashlib.sha256(self.original).hexdigest(),
        )
        self.assertEqual(
            item["proposed_sha256"],
            hashlib.sha256(self.modified).hexdigest(),
        )

        proposal_dir = self.proposals / manifest["proposal_id"]
        patch = (proposal_dir / "patch.diff").read_bytes()
        saved_manifest = json.loads(
            (proposal_dir / "manifest.json").read_text()
        )

        self.assertEqual(
            manifest["patch_sha256"],
            hashlib.sha256(patch).hexdigest(),
        )
        self.assertEqual(saved_manifest, manifest)

    def test_manifest_contains_approval_bindings(self):
        manifest = self.build_proposal({self.relative: self.modified})

        self.assertEqual(manifest["task_id"], "task-test-001")
        self.assertEqual(manifest["approved_plan_sha256"], "a" * 64)
        self.assertEqual(manifest["candidate_id"], "candidate-test-001")
        self.assertEqual(
            manifest["candidate_sha256"],
            candidate_digest({self.relative: self.modified}),
        )
        self.assertEqual(manifest["status"], "proposed")

    def test_candidate_digest_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "候选摘要与审批票据不匹配"):
            build_proposal(
                self.project,
                self.proposals,
                {self.relative: self.modified},
                task_id="task-test-001",
                approved_plan_sha256="a" * 64,
                candidate_id="candidate-test-001",
                expected_candidate_sha256="b" * 64,
            )

        self.assertFalse(self.proposals.exists())

    def test_patch_contains_expected_change(self):
        manifest = self.build_proposal(
            {self.relative: self.modified},
        )

        patch = (
            self.proposals
            / manifest["proposal_id"]
            / "patch.diff"
        ).read_text()

        self.assertIn("-VALUE = 1", patch)
        self.assertIn("+VALUE = 2", patch)

    def test_empty_patch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "没有实际代码变更"):
            self.build_proposal(
            {self.relative: self.original},
            )

        self.assertFalse(self.proposals.exists())

    def test_oversized_patch_is_rejected(self):
        from policy import MAX_PATCH_SIZE

        # 新文件小于单文件限制，但生成的 unified diff 超过补丁限制。
        modified = b"VALUE = 2\n" + (
            b"#" + b"x" * 100 + b"\n"
        ) * 1400

        self.assertLess(len(modified), 256 * 1024)
        self.assertGreater(len(modified), MAX_PATCH_SIZE)

        with self.assertRaisesRegex(ValueError, "补丁大小超过限制"):
            self.build_proposal(
            {self.relative: modified},
            )

        self.assertFalse(self.proposals.exists())

    def test_partial_proposal_is_cleaned_after_write_failure(self):
        import proposal

        real_open = os.open

        def failing_open(path, flags, *args, **kwargs):
            if path == "manifest.json":
                raise OSError("模拟 manifest 写入失败")
            return real_open(path, flags, *args, **kwargs)

        with patch.object(proposal.os, "open", side_effect=failing_open):
            with self.assertRaisesRegex(ValueError, "提案目录无法安全创建或写入"):
                self.build_proposal(
            {self.relative: self.modified},
                )

        self.assertTrue(self.proposals.is_dir())
        self.assertEqual(list(self.proposals.iterdir()), [])

    def test_symlink_source_is_rejected(self):
        source = self.project / self.relative
        outside = self.base / "outside.py"
        outside.write_bytes(self.original)

        source.unlink()
        source.symlink_to(outside)

        with self.assertRaises(ValueError):
            self.build_proposal(
            {self.relative: self.modified},
            )

    def test_symlink_parent_directory_is_rejected(self):
        app_dir = self.project / "app"
        outside_dir = self.base / "outside"
        outside_dir.mkdir()
        (outside_dir / "learning_db.py").write_bytes(self.original)

        (app_dir / "learning_db.py").unlink()
        app_dir.rmdir()
        app_dir.symlink_to(outside_dir, target_is_directory=True)

        with self.assertRaises(ValueError):
            self.build_proposal(
            {self.relative: self.modified},
            )

    def test_symlink_proposal_root_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.proposals.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ValueError):
            self.build_proposal(
            {self.relative: self.modified},
            )

    def test_symlink_parent_of_proposal_root_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        link = self.base / "linked-parent"
        link.symlink_to(outside, target_is_directory=True)
        proposal_root = link / "proposals"

        with self.assertRaises(ValueError):
            build_proposal(
                self.project,
                proposal_root,
                {self.relative: self.modified},
                task_id="task-test-001",
                approved_plan_sha256="a" * 64,
                candidate_id="candidate-test-001",
                expected_candidate_sha256=candidate_digest({
                    self.relative: self.modified
                }),
            )

    def test_unapproved_file_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build_proposal(
            {"app/main.py": b"print('not allowed')\n"},
            )

    def test_non_utf8_content_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build_proposal(
            {self.relative: b"\xff\xfe"},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
