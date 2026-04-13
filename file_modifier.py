#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
r"""
file_modifier.py
================
支持对单个文件或目录下所有文件进行：
  1. 正则匹配 + 替换文件名
  2. 修改文件的访问时间 / 修改时间（时间戳）

用法示例
--------
# 单文件 —— 删除前缀 "12313--"，同时把修改时间改为 2026-03-07
python file_modifier.py -p "12313--test.doc" \
    --rename-pattern r"^12313--" --rename-replace "" \
    --mtime "2026-03-07"

# 目录 —— 递归处理所有文件，把时间戳中的年份 2025 改为 2026
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern r"^(\d{5}--)" --rename-replace "" \
    --mtime "2026-03-07 10:30:00"

# 只改时间戳，不改文件名
python file_modifier.py -p ./my_folder --recursive \
    --mtime "2026-06-01 08:00:00"

# 只改文件名，不改时间戳
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern r"\s+" --rename-replace "_"

# 预览模式（不真正执行）
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern r"^12313--" --rename-replace "" \
    --mtime "2026-03-07" --dry-run
"""

import argparse
import os
import re
import sys
import time
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


# ─────────────────────────── 时间解析 ───────────────────────────

DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
]


def parse_datetime(dt_str: str) -> Tuple[float, float]:
    """
    将字符串解析为 (min_timestamp, max_timestamp)。
    支持单日期 或 "开始时间,结束时间" 格式。
    """
    if "," in dt_str:
        parts = [p.strip() for p in dt_str.split(",", 1)]
        t1 = _parse_single(parts[0]) if parts[0] else None
        t2 = _parse_single(parts[1]) if parts[1] else None
        
        if t1 is None and t2 is None: return None
        if t1 is None: return (t2, t2)
        if t2 is None: return (t1, t1)
        return (min(t1, t2), max(t1, t2))
    else:
        t = _parse_single(dt_str)
        return (t, t)


def _parse_single(dt_str: str) -> float:
    dt_str = dt_str.strip()
    if not dt_str: return None
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    raise ValueError(
        f"无法解析时间字符串：{dt_str!r}\n"
        f"支持格式：{', '.join(DATETIME_FORMATS)}"
    )


def get_random_timestamp(ts_range: Tuple[float, float]) -> float:
    """在范围内返回随机时间戳。"""
    if not ts_range: return None
    if ts_range[0] == ts_range[1]:
        return ts_range[0]
    return random.uniform(ts_range[0], ts_range[1])


# ─────────────────────────── 核心操作 ───────────────────────────

def rename_file(path: Path, pattern: str, replacement: str, dry_run: bool) -> Path:
    """
    对文件名（不含目录部分）做正则替换。
    返回操作后的新路径（如未改变则返回原路径）。
    """
    old_name = path.name
    new_name = re.sub(pattern, replacement, old_name)

    if new_name == old_name:
        return path  # 无需改名

    new_path = path.parent / new_name

    if new_path.exists():
        return path

    if not dry_run:
        path.rename(new_path)
    return new_path


def set_birthtime_macos(path: Path, ctime: float) -> bool:
    """使用 SetFile 命令在 macOS 上修改创建时间。"""
    dt = datetime.fromtimestamp(ctime)
    ts_str = dt.strftime("%m/%d/%Y %H:%M:%S")
    try:
        subprocess.run(["SetFile", "-d", ts_str, str(path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def set_birthtime_windows(path: Path, ctime: float) -> bool:
    """使用 ctypes 调用 Win32 API 在 Windows 上修改创建时间。"""
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
            str(path), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None
        )

        if handle == -1:
            return False

        success = set_file_time(handle, ctypes.byref(ft), None, None)
        close_handle(handle)
        return bool(success)
    except Exception:
        return False


def get_current_birthtime(stat_result) -> float:
    """从 stat 结果中获取跨平台最接近 '诞生时间' 的数值。"""
    if hasattr(stat_result, "st_birthtime"):
        return stat_result.st_birthtime
    if sys.platform == "win32":
        return stat_result.st_ctime
    return stat_result.st_ctime


def set_timestamp(
    path: Path,
    atime: Optional[float],
    mtime: Optional[float],
    ctime: Optional[float],
    dry_run: bool
) -> None:
    """修改文件的访问、修改及创建（macOS/Windows）时间。"""
    if atime is None and mtime is None and ctime is None:
        return

    current = path.stat()
    new_atime = atime if atime is not None else current.st_atime
    new_mtime = mtime if mtime is not None else current.st_mtime

    final_ctime = ctime
    current_birthtime = get_current_birthtime(current)

    if final_ctime is None:
        if new_mtime < current_birthtime:
            final_ctime = new_mtime - random.randint(600, 3600)
    elif final_ctime > new_mtime:
        final_ctime = new_mtime - 60

    if not dry_run:
        os.utime(path, (new_atime, new_mtime))
        if final_ctime is not None:
            if sys.platform == "darwin":
                set_birthtime_macos(path, final_ctime)
            elif sys.platform == "win32":
                set_birthtime_windows(path, final_ctime)


def process_file(
    path: Path,
    rename_pattern: Optional[str],
    rename_replace: str,
    atime_range: Optional[Tuple[float, float]],
    mtime_range: Optional[Tuple[float, float]],
    ctime_range: Optional[Tuple[float, float]],
    dry_run: bool,
) -> None:
    """对单个文件执行重命名 + 时间戳修改。"""
    current_path = path
    if rename_pattern is not None:
        current_path = rename_file(path, rename_pattern, rename_replace, dry_run)

    target_atime = get_random_timestamp(atime_range) if atime_range else None
    target_mtime = get_random_timestamp(mtime_range) if mtime_range else None
    target_ctime = get_random_timestamp(ctime_range) if ctime_range else None

    stats_path = path if dry_run else current_path
    set_timestamp(stats_path, target_atime, target_mtime, target_ctime, dry_run)


def collect_files(root: Path, recursive: bool) -> list[Path]:
    """收集目标路径下的所有文件。"""
    if root.is_file():
        return [root]

    if recursive:
        return sorted([p for p in root.rglob("*") if p.is_file()])
    else:
        return sorted([p for p in root.iterdir() if p.is_file()])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file_modifier",
        description="文件名正则替换 & 时间戳修改工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("-p", "--path", required=True, metavar="PATH", help="文件或目录路径")
    parser.add_argument("-r", "--recursive", action="store_true", default=False, help="递归处理")
    parser.add_argument("--rename-pattern", metavar="REGEX", help="重命名正则")
    parser.add_argument("--rename-replace", metavar="REPLACEMENT", default="", help="替换文本")
    parser.add_argument("--rename-flags", metavar="FLAGS", default="", help="正则标志")
    parser.add_argument("--mtime", metavar="DATETIME", help="修改时间范围")
    parser.add_argument("--atime", metavar="DATETIME", help="访问时间范围")
    parser.add_argument("--ctime", metavar="DATETIME", help="创建时间范围")
    parser.add_argument("--dry-run", action="store_true", default=False, help="预览模式")
    parser.add_argument("--include", metavar="REGEX", help="仅包含正则")
    parser.add_argument("--exclude", metavar="REGEX", help="排除正则")

    return parser


def parse_re_flags(flag_str: str) -> int:
    mapping = {"i": re.IGNORECASE, "s": re.DOTALL, "m": re.MULTILINE}
    flags = 0
    for ch in flag_str.lower():
        if ch in mapping:
            flags |= mapping[ch]
    return flags


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        parser.error(f"路径不存在：{root}")

    mtime_range = file_modifier.parse_datetime(args.mtime) if args.mtime else None
    atime_range = file_modifier.parse_datetime(args.atime) if args.atime else None
    ctime_range = file_modifier.parse_datetime(args.ctime) if args.ctime else None

    re_flags = parse_re_flags(args.rename_flags)
    rename_pattern = args.rename_pattern if args.rename_pattern else None
    include_re = re.compile(args.include, re_flags) if args.include else None
    exclude_re = re.compile(args.exclude, re_flags) if args.exclude else None

    files = collect_files(root, args.recursive)

    def should_process(p: Path) -> bool:
        name = p.name
        if include_re and not include_re.search(name): return False
        if exclude_re and exclude_re.search(name): return False
        return True

    files = [f for f in files if should_process(f)]

    if not files:
        print("未找到符合条件的文件。")
        return

    for file_path in files:
        process_file(
            path=file_path,
            rename_pattern=rename_pattern,
            rename_replace=args.rename_replace,
            atime_range=atime_range,
            mtime_range=mtime_range,
            ctime_range=ctime_range,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
