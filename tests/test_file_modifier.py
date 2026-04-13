from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import json
import asyncio
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
            expected_final_path = target_file.resolve().with_name("sample.txt")
            self.assertIn(f"final={expected_final_path}", result.stdout)
            self.assertIn("time=planned:", result.stdout)

    def test_skips_rename_conflict_and_does_not_update_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "123--report.txt"
            target_file = root / "report.txt"
            source_file.write_text("source", encoding="utf-8")
            target_file.write_text("target", encoding="utf-8")
            original_timestamp = datetime.strptime(
                "2024-01-02 03:04:05", TIME_FORMAT
            ).timestamp()
            expected_timestamp_ns = int(round(original_timestamp * 1_000_000_000))
            os.utime(source_file, (original_timestamp, original_timestamp))

            result = run_cli(
                "--path",
                str(source_file),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
                "--time-start",
                "2025-03-07 00:00:00",
                "--time-end",
                "2025-03-07 23:59:59",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(source_file.exists())
            self.assertTrue(target_file.exists())
            source_stat = source_file.stat()
            self.assertEqual(source_stat.st_atime_ns, expected_timestamp_ns)
            self.assertEqual(source_stat.st_mtime_ns, expected_timestamp_ns)
            self.assertIn("conflict", result.stdout.lower())
            self.assertIn("summary: total=1 success=0 skipped=1 failed=0", result.stdout)

    def test_rejects_partial_rename_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--name-pattern",
                r"^\d+--",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--name-pattern 和 --name-repl 必须同时提供", result.stderr)

    def test_rejects_partial_time_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--time-start",
                "2025-03-07 00:00:00",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--time-start 和 --time-end 必须同时提供", result.stderr)

    def test_rejects_time_range_with_start_after_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--time-start",
                "2026-03-07 00:00:00",
                "--time-end",
                "2025-03-07 00:00:00",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--time-start 必须早于或等于 --time-end", result.stderr)

    def test_rejects_invalid_time_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--time-start",
                "2025/03/07",
                "--time-end",
                "2025-03-07 00:00:00",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--time-start 时间格式非法", result.stderr)

    def test_rejects_invalid_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--name-pattern",
                "(",
                "--name-repl",
                "",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("正则表达式非法", result.stderr)

    def test_reports_unchanged_when_rename_pattern_has_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target_file.exists())
            self.assertIn("unchanged", result.stdout)
            self.assertIn("summary: total=1 success=0 skipped=1 failed=0", result.stdout)

    def test_appends_suffix_after_existing_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_file = root / "123.txt"
            updated_file = root / "123.txt.misc"
            original_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(original_file),
                "--append-suffix",
                "misc",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(original_file.exists())
            self.assertTrue(updated_file.exists())
            self.assertIn("summary: total=1 success=1 skipped=0 failed=0", result.stdout)

    def test_skips_append_suffix_when_suffix_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "123.txt.misc"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--append-suffix",
                "misc",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target_file.exists())
            self.assertIn("summary: total=1 success=0 skipped=1 failed=0", result.stdout)

    def test_combined_rename_and_timestamp_updates_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_file = root / "123--sample.txt"
            renamed_file = root / "sample.txt"
            original_file.write_text("sample", encoding="utf-8")
            timestamp_text = "2025-03-07 12:34:56"
            timestamp_value = datetime.strptime(timestamp_text, TIME_FORMAT).timestamp()
            expected_timestamp_ns = int(round(timestamp_value * 1_000_000_000))

            result = run_cli(
                "--path",
                str(original_file),
                "--name-pattern",
                r"^\d+--",
                "--name-repl",
                "",
                "--time-start",
                timestamp_text,
                "--time-end",
                timestamp_text,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(original_file.exists())
            self.assertTrue(renamed_file.exists())
            renamed_stat = renamed_file.stat()
            self.assertEqual(renamed_stat.st_atime_ns, expected_timestamp_ns)
            self.assertEqual(renamed_stat.st_mtime_ns, expected_timestamp_ns)
            self.assertIn("summary: total=1 success=1 skipped=0 failed=0", result.stdout)

    def test_reports_invalid_generated_name_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            result = run_cli(
                "--path",
                str(target_file),
                "--name-pattern",
                r"sample",
                "--name-repl",
                "folder/sample",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target_file.exists())
            self.assertIn("rename=failed", result.stdout)
            self.assertIn("time=not-run", result.stdout)
            self.assertIn("生成的新文件名", result.stdout)
            self.assertIn("summary: total=1 success=0 skipped=0 failed=1", result.stdout)

    def test_continues_processing_other_files_after_single_file_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            failing_file = root / "bad-sample.txt"
            success_file = root / "123--good.txt"
            renamed_success_file = root / "good.txt"
            failing_file.write_text("bad", encoding="utf-8")
            success_file.write_text("good", encoding="utf-8")

            result = run_cli(
                "--path",
                str(root),
                "--name-pattern",
                r"^(?:bad-sample\.txt|123--)",
                "--name-repl",
                "",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(failing_file.exists())
            self.assertFalse(success_file.exists())
            self.assertTrue(renamed_success_file.exists())
            self.assertIn("rename=failed", result.stdout)
            self.assertIn("summary: total=2 success=1 skipped=0 failed=1", result.stdout)


class WebRunTaskCompatibilityTests(unittest.TestCase):
    def test_run_task_dry_run_streams_progress_without_missing_compatibility_functions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            async def collect_events() -> list[dict[str, object]]:
                from app import RunRequest, run_task

                response = await run_task(
                    RunRequest(
                        path=str(target_file),
                        recursive=False,
                        mod_name=False,
                        mod_mtime=True,
                        mod_atime=False,
                        mod_ctime=False,
                        rename_pattern="",
                        rename_replace="",
                        mtime="2025-03-07 00:00:00,2025-03-07 23:59:59",
                        dry_run=True,
                        include_exts="",
                        exclude_exts="",
                    )
                )

                events: list[dict[str, object]] = []
                async for chunk in response.body_iterator:
                    payload = chunk.decode() if isinstance(chunk, bytes) else chunk
                    for line in payload.split("\n\n"):
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
                return events

            events = asyncio.run(collect_events())
            event_types = [event["type"] for event in events]

            self.assertNotIn("error", event_types)
            self.assertIn("progress", event_types)
            self.assertEqual(events[-1]["type"], "done")

    def test_run_task_dry_run_supports_append_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = root / "sample.txt"
            target_file.write_text("sample", encoding="utf-8")

            async def collect_events() -> list[dict[str, object]]:
                from app import RunRequest, run_task

                response = await run_task(
                    RunRequest(
                        path=str(target_file),
                        recursive=False,
                        mod_name=True,
                        mod_mtime=False,
                        mod_atime=False,
                        mod_ctime=False,
                        rename_pattern="",
                        rename_replace="",
                        append_suffix="misc",
                        dry_run=True,
                        include_exts="",
                        exclude_exts="",
                    )
                )

                events: list[dict[str, object]] = []
                async for chunk in response.body_iterator:
                    payload = chunk.decode() if isinstance(chunk, bytes) else chunk
                    for line in payload.split("\n\n"):
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
                return events

            events = asyncio.run(collect_events())
            event_types = [event["type"] for event in events]

            self.assertNotIn("error", event_types)
            self.assertIn("progress", event_types)
            self.assertEqual(events[-1]["type"], "done")


if __name__ == "__main__":
    unittest.main()
