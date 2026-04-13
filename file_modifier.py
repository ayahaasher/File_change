#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import random
import re
from datetime import datetime
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file_modifier",
        description="文件名正则替换与时间戳修改工具",
    )
    parser.add_argument("--path", required=True, help="目标文件或目录")
    parser.add_argument("--name-pattern", help="文件名匹配正则")
    parser.add_argument("--name-repl", help="文件名替换内容")
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
    rename_requested = args.name_pattern is not None or args.name_repl is not None
    time_requested = args.time_start is not None or args.time_end is not None

    if not rename_requested and not time_requested:
        parser.error("请至少指定一种操作：文件名修改或时间戳修改")
    if (args.name_pattern is None) != (args.name_repl is None):
        parser.error("--name-pattern 和 --name-repl 必须同时提供")
    if (args.time_start is None) != (args.time_end is None):
        parser.error("--time-start 和 --time-end 必须同时提供")


def parse_time_range(start_text: str, end_text: str) -> tuple[float, float]:
    start_dt = datetime.strptime(start_text, TIME_FORMAT)
    end_dt = datetime.strptime(end_text, TIME_FORMAT)
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
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


def rename_file(
    path: Path,
    pattern: re.Pattern[str],
    replacement: str,
    dry_run: bool,
) -> tuple[Path, str]:
    new_name = pattern.sub(replacement, path.name)
    if new_name == path.name:
        return path, "unchanged"

    new_path = path.with_name(new_name)
    if new_path.exists():
        return path, "conflict"

    if not dry_run:
        path.rename(new_path)
    return new_path, "renamed"


def random_timestamp(start_ts: float, end_ts: float) -> float:
    if start_ts == end_ts:
        return start_ts
    return random.uniform(start_ts, end_ts)


def apply_timestamps(path: Path, timestamp_value: float, dry_run: bool) -> None:
    if dry_run:
        return
    os.utime(path, (timestamp_value, timestamp_value))


def process_file(
    path: Path,
    compiled_pattern: re.Pattern[str] | None,
    replacement: str | None,
    time_range: tuple[float, float] | None,
    dry_run: bool,
) -> None:
    final_path = path

    if compiled_pattern is not None and replacement is not None:
        final_path, rename_status = rename_file(path, compiled_pattern, replacement, dry_run)
        print(f"[rename] {path} -> {final_path} ({rename_status})")

    if time_range is not None:
        timestamp_value = random_timestamp(*time_range)
        timestamp_target = path if dry_run else final_path
        apply_timestamps(timestamp_target, timestamp_value, dry_run)
        formatted = datetime.fromtimestamp(timestamp_value).strftime(TIME_FORMAT)
        print(f"[time] {timestamp_target} -> {formatted}")


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

    for file_path in files:
        process_file(file_path, compiled_pattern, args.name_repl, time_range, args.dry_run)


if __name__ == "__main__":
    main()
