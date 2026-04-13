import os
import re
import math
import time
import json
import asyncio
import subprocess
import platform
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import core logic from file_modifier.py
import file_modifier

app = FastAPI(title="File Modifier Pro Web")

# Directories
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Files
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class RunRequest(BaseModel):
    path: str
    recursive: bool = False
    
    # Selective modifications
    mod_name: bool = True
    mod_mtime: bool = True
    mod_atime: bool = False
    mod_ctime: bool = False
    
    rename_pattern: Optional[str] = None
    rename_replace: str = ""
    mtime: Optional[str] = None
    atime: Optional[str] = None
    ctime: Optional[str] = None
    
    include: Optional[str] = None
    exclude: Optional[str] = None
    include_exts: Optional[str] = None
    exclude_exts: Optional[str] = None
    dry_run: bool = True

class Settings(BaseModel):
    default_suffixes: str = "doc, docx, xlsx, csv, xls, pdf"
    recursive_default: bool = True
    dry_run_default: bool = False
    ignore_hidden: bool = True

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(path: Path, data: Any):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index file not found")
    return index_path.read_text(encoding="utf-8")

# --- Native Shell APIs ---

@app.get("/api/shell/pick-folder")
async def pick_folder():
    system = platform.system()
    try:
        if system == "Darwin":
            cmd = "osascript -e 'POSIX path of (choose folder with prompt \"请选择目标文件夹\")'"
        elif system == "Windows":
            cmd = 'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; if($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$f.SelectedPath}"'
        else:
            return {"path": "/", "msg": "当前平台不支持原生选择，请手动输入路径"}
        
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        path = proc.stdout.strip()
        return {"path": path} if path else {"path": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/shell/pick-file")
async def pick_file():
    system = platform.system()
    try:
        if system == "Darwin":
            cmd = "osascript -e 'POSIX path of (choose file with prompt \"请选择目标文件\")'"
        elif system == "Windows":
            cmd = 'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.OpenFileDialog; if($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$f.FileName}"'
        else:
            return {"path": "/", "msg": "当前平台不支持原生选择，请手动输入路径"}
        
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        path = proc.stdout.strip()
        return {"path": path} if path else {"path": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Settings & History APIs ---

@app.get("/api/settings")
async def get_settings():
    return load_json(SETTINGS_FILE, Settings().model_dump())

@app.post("/api/settings")
async def save_settings(s: Settings):
    save_json(SETTINGS_FILE, s.model_dump())
    return {"status": "ok"}

@app.get("/api/history")
async def get_history():
    return load_json(HISTORY_FILE, [])

@app.post("/api/run")
async def run_task(req: RunRequest):
    async def event_generator():
        try:
            root = Path(req.path).expanduser().resolve()
            if not root.exists():
                yield f"data: {json.dumps({'type': 'error', 'msg': f'路径不存在: {root}'})}\n\n"
                return

            # Statistics & Logs
            renamed_cnt = 0
            ts_cnt = 0
            task_logs = []

            # Parse times (Only if requested)
            mtime_range = file_modifier.parse_datetime(req.mtime) if (req.mod_mtime and req.mtime) else None
            atime_range = file_modifier.parse_datetime(req.atime) if (req.mod_atime and req.atime) else None
            ctime_range = file_modifier.parse_datetime(req.ctime) if (req.mod_ctime and req.ctime) else None
            
            # Regex
            rename_pattern = req.rename_pattern if (req.mod_name and req.rename_pattern) else None
            include_re = re.compile(req.include) if req.include else None
            exclude_re = re.compile(req.exclude) if req.exclude else None
            
            # Ext filters
            include_exts = [e.strip().lower() for e in req.include_exts.split(",") if e.strip()] if req.include_exts else []
            exclude_exts = [e.strip().lower() for e in req.exclude_exts.split(",") if e.strip()] if req.exclude_exts else []

            files = file_modifier.collect_files(root, req.recursive)
            
            # Filtering
            def should_process(p: Path) -> bool:
                name = p.name
                ext = p.suffix[1:].lower() if p.suffix else ""
                if include_re and not include_re.search(name): return False
                if exclude_re and exclude_re.search(name): return False
                if include_exts and ext not in include_exts: return False
                if exclude_exts and ext in exclude_exts: return False
                if load_json(SETTINGS_FILE, Settings().model_dump()).get("ignore_hidden") and name.startswith('.'):
                    return False
                return True

            target_files = [f for f in files if should_process(f)]
            total = len(target_files)
            
            mode_text = "【预览模式】" if req.dry_run else "【正式执行】"
            yield f"data: {json.dumps({'type': 'info', 'msg': f'确认任务: {mode_text}，找到 {total} 个匹配文件'})}\n\n"
            
            if total == 0:
                yield f"data: {json.dumps({'type': 'done', 'msg': '无文件可处理'})}\n\n"
                return

            for i, file_path in enumerate(target_files):
                old_name = file_path.name
                try:
                    current_path = file_path
                    rename_op = False
                    ts_op = False
                    
                    # 1. Rename logic
                    if rename_pattern:
                        new_name = re.sub(rename_pattern, req.rename_replace, old_name)
                        if new_name != old_name:
                            new_path = file_path.parent / new_name
                            if not req.dry_run:
                                file_path.rename(new_path)
                            current_path = new_path
                            renamed_cnt += 1
                            rename_op = True
                    
                    # 2. Timestamp logic
                    t_mtime = file_modifier.get_random_timestamp(mtime_range) if mtime_range else None
                    t_atime = file_modifier.get_random_timestamp(atime_range) if atime_range else None
                    t_ctime = file_modifier.get_random_timestamp(ctime_range) if ctime_range else None
                    
                    if any([t_mtime, t_atime, t_ctime]):
                        if not req.dry_run:
                            file_modifier.set_timestamp(current_path, t_atime, t_mtime, t_ctime, False)
                        ts_cnt += 1
                        ts_op = True
                    
                    log_entry = f"{datetime.now().strftime('%H:%M:%S')} - 处理: {old_name} | 重命名: {'YES' if rename_op else 'NO'} | 时间修改: {'YES' if ts_op else 'NO'}"
                    task_logs.append(log_entry)
                    
                    # Only send summary data to dashboard to keep it clean
                    yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': total, 'renamed_cnt': renamed_cnt, 'ts_cnt': ts_cnt})}\n\n"
                    
                except Exception as e:
                    task_logs.append(f"{datetime.now().strftime('%H:%M:%S')} - 错误 {old_name}: {str(e)}")
                await asyncio.sleep(0.001)

            # Save to history with detailed logs
            history = load_json(HISTORY_FILE, [])
            history.insert(0, {
                "id": int(time.time()),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "path": req.path,
                "config": req.model_dump(),
                "summary": {"renamed": renamed_cnt, "ts_updated": ts_cnt, "total": total},
                "logs": task_logs,
                "status": "Success"
            })
            save_json(HISTORY_FILE, history[:100]) # Cap at 100

            yield f"data: {json.dumps({'type': 'done', 'msg': f'任务完成，共重命名 {renamed_cnt} 个，修改时间 {ts_cnt} 个'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': f'系统错误: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
