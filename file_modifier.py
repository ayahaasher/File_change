#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
file_modifier.py
================
支持对单个文件或目录下所有文件进行：
  1. 正则匹配 + 替换文件名
  2. 修改文件的访问时间 / 修改时间（时间戳）

用法示例
--------
# 单文件 —— 删除前缀 "12313--"，同时把修改时间改为 2026-03-07
python file_modifier.py -p "12313--test.doc" \
    --rename-pattern "^12313--" --rename-replace "" \
    --mtime "2026-03-07"

# 目录 —— 递归处理所有文件，把时间戳中的年份 2025 改为 2026
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern "^(\d{5}--)" --rename-replace "" \
    --mtime "2026-03-07 10:30:00"

# 只改时间戳，不改文件名
python file_modifier.py -p ./my_folder --recursive \
    --mtime "2026-06-01 08:00:00"

# 只改文件名，不改时间戳
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern "\s+" --rename-replace "_"

# 预览模式（不真正执行）
python file_modifier.py -p ./my_folder --recursive \
    --rename-pattern "^12313--" --rename-replace "" \
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
        t1 = _parse_single(parts[0])
        t2 = _parse_single(parts[1])
        return (min(t1, t2), max(t1, t2))
    else:
        t = _parse_single(dt_str)
        return (t, t)


def _parse_single(dt_str: str) -> float:
    dt_str = dt_str.strip()
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
        print(f"  [跳过重命名] 目标已存在：{new_path}")
        return path

    print(f"  [重命名] {old_name}  →  {new_name}")
    if not dry_run:
        path.rename(new_path)
    return new_path


def set_birthtime_macos(path: Path, ctime: float) -> bool:
    """使用 SetFile 命令在 macOS 上修改创建时间。"""
    # SetFile 格式是 "mm/dd/yyyy hh:mm:ss"
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

    # Windows FILETIME 是从 1601-01-01 开始的 100 纳秒间隔数
    # Unix epoch (1970) 偏移量为 11644473600 秒
    wintime = int((ctime + 11644473600) * 10000000)
    low = wintime & 0xFFFFFFFF
    high = wintime >> 32
    ft = wintypes.FILETIME(low, high)

    # 常量定义
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x01
    FILE_SHARE_WRITE = 0x02
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # 允许打开目录

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

        # SetFileTime(handle, lpCreationTime, lpLastAccessTime, lpLastWriteTime)
        success = set_file_time(handle, ctypes.byref(ft), None, None)
        close_handle(handle)
        return bool(success)
    except Exception:
        return False


def get_current_birthtime(stat_result) -> float:
    """从 stat 结果中获取跨平台最接近 '诞生时间' 的数值。"""
    # macOS/FreeBSD 具有 st_birthtime
    if hasattr(stat_result, "st_birthtime"):
        return stat_result.st_birthtime
    # Windows 下 st_ctime 是物理创建时间
    if sys.platform == "win32":
        return stat_result.st_ctime
    # Linux 下基本无法获取/修改 birthtime，fallback 到 mtime 或 ctime (改动时间)
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

    # 约束校验：ctime 必须早于 mtime
    final_ctime = ctime
    current_birthtime = get_current_birthtime(current)

    if final_ctime is None:
        if new_mtime < current_birthtime:
            # 自动调整 ctime 为 mtime 之前的随机时间 (10-60分钟)
            final_ctime = new_mtime - random.randint(600, 3600)
    elif final_ctime > new_mtime:
        # 如果用户指定的 ctime 晚于 mtime，强制修正
        print(f"  [修正] 创建时间强制设为早于修改时间。")
        final_ctime = new_mtime - 60

    fmt = "%Y-%m-%d %H:%M:%S"
    msg = []
    if final_ctime is not None:
        msg.append(f"ctime: {datetime.fromtimestamp(current_birthtime).strftime(fmt)} → {datetime.fromtimestamp(final_ctime).strftime(fmt)}")
    msg.append(f"mtime: {datetime.fromtimestamp(current.st_mtime).strftime(fmt)} → {datetime.fromtimestamp(new_mtime).strftime(fmt)}")

    print(f"  [时间戳] {' | '.join(msg)}")

    if not dry_run:
        # 1. 设置 mtime/atime (跨平台标准)
        os.utime(path, (new_atime, new_mtime))
        # 2. 设置 ctime (平台相关)
        if final_ctime is not None:
            success = False
            if sys.platform == "darwin":
                success = set_birthtime_macos(path, final_ctime)
            elif sys.platform == "win32":
                success = set_birthtime_windows(path, final_ctime)
            else:
                print(f"  [警告] 当前平台 ({sys.platform}) 不支持修改创建时间。")
                return

            if not success:
                if sys.platform == "darwin":
                    print(f"  [警告] 无法修改创建时间，请确保已安装 Xcode 命令行工具 (SetFile)。")
                else:
                    print(f"  [警告] 无法修改创建时间，请检查权限。")


def process_file(
    path: Path,
    rename_pattern: Optional[str],
    rename_replace: str,
    atime_range: Optional[Tuple[float, float]],
    mtime_range: Optional[Tuple[float, float]],
    ctime_range: Optional[Tuple[float, float]],
    dry_run: bool,
) -> None:
    """对单个文件执行重命名 + 时间戳修改（支持随机范围）。"""
    print(f"\n处理文件：{path}")

    # 1. 重命名
    current_path = path
    if rename_pattern is not None:
        current_path = rename_file(path, rename_pattern, rename_replace, dry_run)

    # 2. 生成具体时间点
    target_atime = get_random_timestamp(atime_range) if atime_range else None
    target_mtime = get_random_timestamp(mtime_range) if mtime_range else None
    target_ctime = get_random_timestamp(ctime_range) if ctime_range else None

    # 如果是预览模式，重命名并没有发生，所以获取状态必须用旧路径 (path)
    stats_path = path if dry_run else current_path
    set_timestamp(stats_path, target_atime, target_mtime, target_ctime, dry_run)


def collect_files(root: Path, recursive: bool) -> list[Path]:
    """收集目标路径下的所有文件（不含目录本身）。"""
    if root.is_file():
        return [root]

    if recursive:
        return sorted([p for p in root.rglob("*") if p.is_file()])
    else:
        return sorted([p for p in root.iterdir() if p.is_file()])


# ─────────────────────────── CLI ───────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file_modifier",
        description="文件名正则替换 & 时间戳修改工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "-p", "--path",
        required=True,
        metavar="PATH",
        help="单个文件路径 或 目录路径",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=False,
        help="递归处理子目录下的所有文件（仅对目录有效）",
    )

    # ── 重命名 ──
    rename_group = parser.add_argument_group("重命名选项")
    rename_group.add_argument(
        "--rename-pattern",
        metavar="REGEX",
        help="用于匹配文件名的正则表达式（Python re 语法）",
    )
    rename_group.add_argument(
        "--rename-replace",
        metavar="REPLACEMENT",
        default="",
        help="替换字符串（默认空字符串，即删除匹配部分）；支持反向引用 \\1 等",
    )
    rename_group.add_argument(
        "--rename-flags",
        metavar="FLAGS",
        default="",
        help="正则标志：i=忽略大小写, s=点匹配换行, m=多行模式（可组合，如 'is'）",
    )

    # ── 时间戳 ──
    ts_group = parser.add_argument_group("时间戳选项")
    ts_group.add_argument(
        "--mtime",
        metavar="DATETIME",
        help="修改时间。支持单日期或范围 'start,end'",
    )
    ts_group.add_argument(
        "--atime",
        metavar="DATETIME",
        help="访问时间。支持单日期或范围 'start,end'",
    )
    ts_group.add_argument(
        "--ctime",
        metavar="DATETIME",
        help="创建时间 (macOS)。支持单日期或范围 'start,end'",
    )

    # ── 其他 ──
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="预览模式：只打印将要执行的操作，不真正修改文件",
    )
    parser.add_argument(
        "--include",
        metavar="REGEX",
        help="仅处理文件名匹配该正则的文件（可与 --rename-pattern 独立使用）",
    )
    parser.add_argument(
        "--exclude",
        metavar="REGEX",
        help="跳过文件名匹配该正则的文件",
    )

    return parser


def parse_re_flags(flag_str: str) -> int:
    """将字符串标志转换为 re 模块常量的组合。"""
    mapping = {"i": re.IGNORECASE, "s": re.DOTALL, "m": re.MULTILINE}
    flags = 0
    for ch in flag_str.lower():
        if ch in mapping:
            flags |= mapping[ch]
        else:
            print(f"[警告] 未知正则标志：{ch!r}，已忽略", file=sys.stderr)
    return flags


# ─────────────────────────── 入口 ───────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        parser.error(f"路径不存在：{root}")

    # 解析时间戳
    mtime_range: Optional[Tuple[float, float]] = None
    atime_range: Optional[Tuple[float, float]] = None
    ctime_range: Optional[Tuple[float, float]] = None
    try:
        if args.mtime:
            mtime_range = parse_datetime(args.mtime)
        if args.atime:
            atime_range = parse_datetime(args.atime)
        if args.ctime:
            ctime_range = parse_datetime(args.ctime)
    except ValueError as e:
        parser.error(str(e))

    # 解析正则
    re_flags = parse_re_flags(args.rename_flags)
    rename_pattern: Optional[str] = None
    if args.rename_pattern:
        try:
            re.compile(args.rename_pattern, re_flags)  # 验证语法
            rename_pattern = args.rename_pattern
        except re.error as e:
            parser.error(f"正则表达式语法错误：{e}")

    include_re = re.compile(args.include, re_flags) if args.include else None
    exclude_re = re.compile(args.exclude, re_flags) if args.exclude else None

    if rename_pattern is None and mtime_range is None and atime_range is None and ctime_range is None:
        parser.error("请至少指定 --rename-pattern 或 --mtime / --atime / --ctime 中的一个")

    # 收集文件
    files = collect_files(root, args.recursive)

    # 过滤
    def should_process(p: Path) -> bool:
        name = p.name
        if include_re and not include_re.search(name):
            return False
        if exclude_re and exclude_re.search(name):
            return False
        return True

    files = [f for f in files if should_process(f)]

    if not files:
        print("未找到符合条件的文件。")
        return

    mode_label = "【预览模式 - 不会实际修改文件】" if args.dry_run else ""
    print(f"共找到 {len(files)} 个文件待处理。{mode_label}")

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

    print(f"\n✅ 完成。共处理 {len(files)} 个文件。")


if __name__ == "__main__":
    main()
