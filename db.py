# -*- coding: utf-8 -*-
"""workbuddy.db 访问：只读查询、进程检测、备份、事务写入。"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter

import paths


def _connect_ro():
    db = paths.get_db_path()
    if not os.path.exists(db):
        raise FileNotFoundError("未找到数据库: %s" % db)
    uri = "file:" + db.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def db_exists():
    return os.path.exists(paths.get_db_path())


def list_workspaces():
    """返回 [{path, last_opened_at}]，DB 不存在时返回空表。"""
    if not db_exists():
        return []
    conn = _connect_ro()
    try:
        rows = conn.execute("SELECT path, last_opened_at FROM workspaces").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_sessions():
    if not db_exists():
        return []
    conn = _connect_ro()
    try:
        rows = conn.execute("SELECT * FROM sessions").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_dominant_user_id():
    """目标机器 sessions 表出现最多的 user_id（导入行替换用）。"""
    sessions = list_sessions()
    if not sessions:
        return None
    ids = [s.get("user_id") for s in sessions if s.get("user_id")]
    if not ids:
        return None
    return Counter(ids).most_common(1)[0][0]


def workbuddy_running():
    """检测 WorkBuddy 桌面进程是否在运行。测试可用 WBMIGRATE_SKIP_PROC_CHECK=1 旁路。"""
    if os.environ.get("WBMIGRATE_SKIP_PROC_CHECK") == "1":
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV"], stderr=subprocess.DEVNULL, timeout=15
            ).decode("utf-8", "replace")
            for line in out.splitlines():
                low = line.lower()
                if "workbuddy" in low and ".exe" in low:
                    # 取镜像名
                    try:
                        name = line.split('","')[0].strip('"')
                    except Exception:
                        name = "WorkBuddy"
                    return name
        else:
            # macOS / Linux：ps aux，排除本迁移工具进程
            out = subprocess.check_output(
                ["ps", "aux"], stderr=subprocess.DEVNULL, timeout=15
            ).decode("utf-8", "replace")
            for line in out.splitlines():
                low = line.lower()
                if "workbuddy" in low and "workbuddy-migrate" not in low:
                    # 取命令字段
                    parts = line.split(None, 10)
                    if len(parts) > 10:
                        cmd = parts[10]
                        base = os.path.basename(cmd.split()[0]) if cmd else ""
                        return base or "WorkBuddy"
        return False
    except Exception:
        return None  # 无法判断时不阻止，仅提示


# ---------------- 写入 ----------------

def _connect_rw():
    db = paths.get_db_path()
    conn = sqlite3.connect(paths.long_path(db), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn, table):
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return [r["name"] for r in rows]


def upsert_workspaces(conn, rows):
    """rows: [{path, last_opened_at}]，调用方负责事务。"""
    cols = _table_columns(conn, "workspaces")
    for r in rows:
        data = {k: r.get(k) for k in ("path", "last_opened_at") if k in cols}
        keys = ",".join(data.keys())
        marks = ",".join(["?"] * len(data))
        conn.execute(
            "INSERT OR REPLACE INTO workspaces (%s) VALUES (%s)" % (keys, marks),
            list(data.values()),
        )


def upsert_sessions(conn, rows):
    """rows: 完整 sessions 行 dict（已做路径重写与 user_id 替换）。"""
    if not rows:
        return
    cols = _table_columns(conn, "sessions")
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    keys = [k for k in cols if k in all_keys]  # 仅写入目标表存在的列
    if not keys:
        return
    key_sql = ",".join('"%s"' % k for k in keys)
    marks = ",".join(["?"] * len(keys))
    sql = "INSERT OR REPLACE INTO sessions (%s) VALUES (%s)" % (key_sql, marks)
    for r in rows:
        conn.execute(sql, [r.get(k) for k in keys])


def fetch_sessions_map(conn):
    rows = conn.execute("SELECT id, updated_at FROM sessions").fetchall()
    return {r["id"]: r["updated_at"] for r in rows}


def fetch_workspace_keys(conn):
    rows = conn.execute("SELECT path, last_opened_at FROM workspaces").fetchall()
    return {r["path"]: r["last_opened_at"] for r in rows}


def backup_db(backup_dir):
    """备份 workbuddy.db（含 -wal/-shm，若存在）。"""
    db = paths.get_db_path()
    os.makedirs(backup_dir, exist_ok=True)
    copied = []
    for suffix in ("", "-wal", "-shm"):
        src = db + suffix
        if os.path.exists(src):
            dst = os.path.join(backup_dir, os.path.basename(src))
            shutil.copy2(paths.long_path(src), paths.long_path(dst))
            copied.append(dst)
    return copied


def disk_free(path):
    try:
        u = shutil.disk_usage(path if os.path.exists(path) else os.path.dirname(path) or path)
        return u.free
    except Exception:
        return None


def now_ms():
    return int(time.time() * 1000)
