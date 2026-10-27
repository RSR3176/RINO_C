"""Unit tests for Step 6 patch safety checks."""

from __future__ import annotations

import unittest

from app.fix.safety import is_test_path, validate_patch_files


class FixSafetyTests(unittest.TestCase):
    def test_rejects_test_file_paths(self) -> None:
        self.assertTrue(is_test_path("tests/test_foo.py"))
        self.assertTrue(is_test_path("test/test_foo.py"))
        self.assertTrue(is_test_path("test_foo.py"))
        self.assertTrue(is_test_path("pkg/foo_test.py"))
        self.assertFalse(is_test_path("shellutil.py"))
        self.assertFalse(is_test_path("src/app.py"))

        result = validate_patch_files({"tests/test_x.py": "assert True\n"})
        self.assertFalse(result.ok)
        self.assertTrue(any("test file" in v.lower() for v in result.violations))

    def test_rejects_skip_xfail(self) -> None:
        old = "def test_a():\n    assert 1\n"
        new = "import pytest\n@pytest.mark.skip\ndef test_a():\n    assert 1\n"
        # even on non-test path name — skip markers are banned anywhere
        result = validate_patch_files({"app.py": new}, originals={"app.py": old})
        self.assertFalse(result.ok)
        self.assertTrue(any("skip" in v.lower() for v in result.violations))

    def test_rejects_empty_except(self) -> None:
        old = "def f():\n    return 1\n"
        new = "def f():\n    try:\n        return 1\n    except:\n        pass\n"
        result = validate_patch_files({"app.py": new}, originals={"app.py": old})
        self.assertFalse(result.ok)
        self.assertTrue(any("empty except" in v.lower() for v in result.violations))

    def test_rejects_more_than_three_files(self) -> None:
        files = {f"m{i}.py": f"x={i}\n" for i in range(4)}
        result = validate_patch_files(files)
        self.assertFalse(result.ok)
        self.assertTrue(any("more than 3" in v.lower() for v in result.violations))

    def test_accepts_safe_single_file_fix(self) -> None:
        old = "import subprocess\nsubprocess.run(cmd, shell=True)\n"
        new = (
            "import shlex, subprocess\n"
            "subprocess.run(shlex.split(cmd), shell=False)\n"
        )
        result = validate_patch_files(
            {"shellutil.py": new}, originals={"shellutil.py": old}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.violations, [])


if __name__ == "__main__":
    unittest.main()
