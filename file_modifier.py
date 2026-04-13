#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
WEB_TIME_FORMATS = (
    TIME_FORMAT,
    "%Y-%m-%d",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file_modifier",
        description="文件名正则替换与时间戳修改工具",
    )
    parser.add_argument("--path", required=True, help="目标文件或目录")
    parser.add_argument("--name-pattern", help="文件名匹配正则")
    parser.add_argument("--name-repl", help="文件名替换内容")
    parser.add_argument("--append-suffix", help="在文件名末尾追加后缀，例如 misc -> file.txt.misc")
    parser.add_argument("--time-start", help="时间范围起点，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--time-end", help="时间范围终点，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际修改")
    parser.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        default=True,
        help="递归处理目录中的所有文件（默认开启）",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="仅处理目录下的直接文件",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    rename_requested = (
        args.name_pattern is not None
        or args.name_repl is not None
        or args.append_suffix is not None
    )
    time_requested = args.time_start is not None or args.time_end is not None

    if not rename_requested and not time_requested:
        parser.error("请至少指定一种操作：文件名修改或时间戳修改")
    if (args.name_pattern is None) != (args.name_repl is None):
        parser.error("--name-pattern 和 --name-repl 必须同时提供")
    if (args.time_start is None) != (args.time_end is None):
        parser.error("--time-start 和 --time-end 必须同时提供")


def parse_time_value(value: str, option_name: str) -> float:
    try:
        parsed = datetime.strptime(value, TIME_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"{option_name} 时间格式非法，必须为 {TIME_FORMAT}"
        ) from exc
    return parsed.timestamp()


def parse_datetime(value: str) -> tuple[float, float]:
    parts = [part.strip() for part in value.split(",", 1)] if "," in value else [value.strip()]
    if len(parts) == 1:
        timestamp = parse_web_time_value(parts[0])
        return (timestamp, timestamp)
    return tuple(sorted((parse_web_time_value(parts[0]), parse_web_time_value(parts[1]))))


def parse_web_time_value(value: str) -> float:
    for time_format in WEB_TIME_FORMATS:
        try:
            return datetime.strptime(value, time_format).timestamp()
        except ValueError:
            continue
    raise ValueError(
        f"无法解析时间字符串：{value!r}，支持格式: {', '.join(WEB_TIME_FORMATS)}"
    )


def parse_time_range(start_text: str, end_text: str) -> tuple[float, float]:
    start_ts = parse_time_value(start_text, "--time-start")
    end_ts = parse_time_value(end_text, "--time-end")
    if start_ts > end_ts:
        raise ValueError("--time-start 必须早于或等于 --time-end")
    return start_ts, end_ts


def collect_files(root: Path, recursive: bool) -> list[Path]:
    if root.is_file():
        return [root]
    if root.is_dir() and recursive:
        return sorted(path for path in root.rglob("*") if path.is_file())
    if root.is_dir():
        return sorted(path for path in root.iterdir() if path.is_file())
    raise ValueError(f"路径既不是文件也不是目录：{root}")


def validate_generated_name(new_name: str) -> None:
    separators = {"/", "\\"}
    if not new_name or new_name in {".", ".."}:
        raise ValueError(f"生成的新文件名无效：{new_name!r}")
    if any(separator in new_name for separator in separators):
        raise ValueError(f"生成的新文件名包含路径分隔符：{new_name!r}")


def rename_file(
    path: Path,
    pattern: re.Pattern[str],
    replacement: str,
    dry_run: bool,
) -> tuple[Path, str]:
    new_name = pattern.sub(replacement, path.name)
    if new_name == path.name:
        return path, "unchanged"

    validate_generated_name(new_name)
    new_path = path.with_name(new_name)
    if new_path.exists():
        return path, "conflict"

    if not dry_run:
        path.rename(new_path)
    return new_path, "renamed"


def append_suffix_to_file(path: Path, suffix: str, dry_run: bool) -> tuple[Path, str]:
    normalized_suffix = suffix.strip().lstrip(".")
    if not normalized_suffix:
        raise ValueError("追加后缀不能为空")

    suffix_marker = f".{normalized_suffix}"
    if path.name.endswith(suffix_marker):
        return path, "unchanged"

    new_name = f"{path.name}{suffix_marker}"
    validate_generated_name(new_name)
    new_path = path.with_name(new_name)
    if new_path.exists():
        return path, "conflict"

    if not dry_run:
        path.rename(new_path)
    return new_path, "appended"


def random_timestamp(start_ts: float, end_ts: float) -> float:
    if start_ts == end_ts:
        return start_ts
    return random.uniform(start_ts, end_ts)


def get_random_timestamp(ts_range: tuple[float, float]) -> float:
    return random_timestamp(*ts_range)


def apply_timestamps(path: Path, timestamp_value: float, dry_run: bool) -> None:
    if dry_run:
        return
    os.utime(path, (timestamp_value, timestamp_value))


def set_birthtime_macos(path: Path, ctime: float) -> bool:
    dt = datetime.fromtimestamp(ctime)
    ts_str = dt.strftime("%m/%d/%Y %H:%M:%S")
    try:
        subprocess.run(["SetFile", "-d", ts_str, str(path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def set_birthtime_windows(path: Path, ctime: float) -> bool:
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    wintime = int((ctime + 11644473600) * 10000000)
    low = wintime & 0xFFFFFFFF
    high = wintime >> 32
    ft = wintypes.FILETIME(low, high)

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x01
    FILE_SHARE_WRITE = 0x02
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

    try:
        create_file = ctypes.windll.kernel32.CreateFileW
        set_file_time = ctypes.windll.kernel32.SetFileTime
        close_handle = ctypes.windll.kernel32.CloseHandle

        handle = create_file(
            str(path),
            GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )

        if handle == -1:
            return False

        success = set_file_time(handle, ctypes.byref(ft), None, None)
        close_handle(handle)
        return bool(success)
    except Exception:
        return False


def get_current_birthtime(stat_result: os.stat_result) -> float:
    if hasattr(stat_result, "st_birthtime"):
        return stat_result.st_birthtime
    if sys.platform == "win32":
        return stat_result.st_ctime
    return stat_result.st_ctime


def set_timestamp(
    path: Path,
    atime: float | None,
    mtime: float | None,
    ctime: float | None,
    dry_run: bool,
) -> None:
    if atime is None and mtime is None and ctime is None:
        return
    if dry_run:
        return

    current = path.stat()
    new_atime = atime if atime is not None else current.st_atime
    new_mtime = mtime if mtime is not None else current.st_mtime
    os.utime(path, (new_atime, new_mtime))

    if ctime is None:
        return
    if sys.platform == "darwin":
        set_birthtime_macos(path, ctime)
    elif sys.platform == "win32":
        set_birthtime_windows(path, ctime)


def format_result_line(
    original_path: Path,
    final_path: Path,
    rename_status: str,
    time_status: str,
    reason: str,
) -> str:
    return (
        f"[result] original={original_path} final={final_path} "
        f"rename={rename_status} time={time_status} reason={reason}"
    )


def process_file(
    path: Path,
    compiled_pattern: re.Pattern[str] | None,
    replacement: str | None,
    append_suffix: str | None,
    time_range: tuple[float, float] | None,
    dry_run: bool,
) -> str:
    final_path = path
    rename_status = "not-requested"
    time_status = "not-requested"
    reason = "-"

    if compiled_pattern is not None and replacement is not None:
        final_path, rename_status = rename_file(path, compiled_pattern, replacement, dry_run)
        if rename_status == "conflict":
            time_status = "skipped"
            reason = "rename conflict"
            print(format_result_line(path, final_path, rename_status, time_status, reason))
            return "skipped"

    if append_suffix is not None:
        final_path, append_status = append_suffix_to_file(final_path, append_suffix, dry_run)
        if append_status == "conflict":
            time_status = "skipped"
            reason = "append suffix conflict"
            print(format_result_line(path, final_path, append_status, time_status, reason))
            return "skipped"
        if append_status == "appended":
            rename_status = "appended"
        elif rename_status == "not-requested":
            rename_status = "unchanged"

    if time_range is not None:
        timestamp_value = random_timestamp(*time_range)
        apply_timestamps(final_path, timestamp_value, dry_run)
        formatted = datetime.fromtimestamp(timestamp_value).strftime(TIME_FORMAT)
        time_status = f"planned:{formatted}" if dry_run else f"updated:{formatted}"

    if rename_status == "not-requested" and compiled_pattern is not None:
        rename_status = "unchanged"

    if rename_status in {"renamed", "appended"} or time_range is not None:
        print(format_result_line(path, final_path, rename_status, time_status, reason))
        return "success"

    print(format_result_line(path, final_path, rename_status, time_status, "no change"))
    return "skipped"


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        parser.error(f"路径不存在：{root}")

    compiled_pattern = None
    if args.name_pattern is not None:
        try:
            compiled_pattern = re.compile(args.name_pattern)
        except re.error as exc:
            parser.error(f"正则表达式非法：{exc}")

    time_range = None
    if args.time_start is not None and args.time_end is not None:
        try:
            time_range = parse_time_range(args.time_start, args.time_end)
        except ValueError as exc:
            parser.error(str(exc))

    try:
        files = collect_files(root, args.recursive)
    except ValueError as exc:
        parser.error(str(exc))

    success_count = 0
    skipped_count = 0
    failed_count = 0

    for file_path in files:
        try:
            result = process_file(
                file_path,
                compiled_pattern,
                args.name_repl,
                args.append_suffix,
                time_range,
                args.dry_run,
            )
        except (OSError, ValueError) as exc:
            failed_count += 1
            print(
                format_result_line(
                    file_path,
                    file_path,
                    "failed",
                    "not-run",
                    str(exc),
                )
            )
            continue

        if result == "success":
            success_count += 1
        else:
            skipped_count += 1

    print(
        f"summary: total={len(files)} success={success_count} "
        f"skipped={skipped_count} failed={failed_count}"
    )


if __name__ == "__main__":
    main()
