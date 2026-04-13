from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "file_modifier.py"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )


class FileModifierCliContractTests(unittest.TestCase):
    def test_recursive_rename_is_enabled_by_default_for_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_dir = root / "nested"
            nested_dir.mkdir()
            original_file = nested_dir / "123--child.txt"
            original_file.write_text("child", encoding="utf-8")

            result = run_cli(
                "--path",
                str(root),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(original_file.exists())
            self.assertTrue((nested_dir / "child.txt").exists())

    def test_no_recursive_limits_processing_to_direct_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_dir = root / "nested"
            nested_dir.mkdir()
            direct_file = root / "123--root.txt"
            nested_file = nested_dir / "123--child.txt"
            direct_file.write_text("root", encoding="utf-8")
            nested_file.write_text("child", encoding="utf-8")

            result = run_cli(
                "--path",
                str(root),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
                "--no-recursive",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(direct_file.exists())
            self.assertTrue((root / "root.txt").exists())
            self.assertTrue(nested_file.exists())
            self.assertFalse((nested_dir / "child.txt").exists())

    def test_time_start_and_time_end_update_atime_and_mtime_within_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")
            start_text = "2025-03-07 00:00:00"
            end_text = "2025-03-07 23:59:59"
            start_timestamp = datetime.strptime(start_text, TIME_FORMAT).timestamp()
            end_timestamp = datetime.strptime(end_text, TIME_FORMAT).timestamp()

            result = run_cli(
                "--path",
                str(target_file),
                "--time-start",
                start_text,
                "--time-end",
                end_text,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            stat_result = target_file.stat()
            self.assertGreaterEqual(stat_result.st_atime, start_timestamp)
            self.assertLessEqual(stat_result.st_atime, end_timestamp)
            self.assertGreaterEqual(stat_result.st_mtime, start_timestamp)
            self.assertLessEqual(stat_result.st_mtime, end_timestamp)

    def test_dry_run_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "123--sample.txt"
            target_file.write_text("sample", encoding="utf-8")
            before_stat = target_file.stat()

            result = run_cli(
                "--path",
                str(target_file),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
                "--time-start",
                "2025-03-07 00:00:00",
                "--time-end",
                "2025-03-07 23:59:59",
                "--dry-run",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target_file.exists())
            self.assertFalse((root / "sample.txt").exists())
            after_stat = target_file.stat()
            self.assertEqual(after_stat.st_atime_ns, before_stat.st_atime_ns)
            self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
