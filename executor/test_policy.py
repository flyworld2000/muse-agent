import unittest

from policy import (
    ALLOWED_FILES,
    MAX_FILE_SIZE,
    validate_relative_path,
    validate_proposal_paths,
    validate_content_size,
)


class PolicyTests(unittest.TestCase):

    def test_all_authorized_files_are_accepted(self):
        for path in ALLOWED_FILES:
            with self.subTest(path=path):
                self.assertEqual(validate_relative_path(path), path)

    def test_path_traversal_is_rejected(self):
        for path in (
            "../app/main.py",
            "app/../../etc/passwd",
            "app/./learning_db.py",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_relative_path(path)

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_relative_path("/etc/passwd")

    def test_noncanonical_paths_are_rejected(self):
        for path in (
            "app//learning_db.py",
            "app/./learning_db.py",
            "./app/learning_db.py",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_relative_path(path)

    def test_windows_path_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_relative_path(r"app\main.py")

    def test_unapproved_file_is_rejected(self):
        for path in ("app/main.py", ".env", "data/learning.sqlite3"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_relative_path(path)

    def test_empty_and_null_paths_are_rejected(self):
        for path in ("", None, "app/learning_db.py\x00"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_relative_path(path)

    def test_duplicate_paths_are_rejected(self):
        path = "app/learning_db.py"
        with self.assertRaises(ValueError):
            validate_proposal_paths([path, path])

    def test_empty_proposal_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_proposal_paths([])

    def test_too_many_files_are_rejected(self):
        paths = list(ALLOWED_FILES) + ["app/learning_db.py"]
        with self.assertRaises(ValueError):
            validate_proposal_paths(paths)

    def test_oversized_file_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_content_size(b"x" * (MAX_FILE_SIZE + 1))

    def test_valid_content_size_is_accepted(self):
        validate_content_size(b"valid content")


if __name__ == "__main__":
    unittest.main(verbosity=2)
