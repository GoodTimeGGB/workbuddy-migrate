# -*- coding: utf-8 -*-
"""导出：扫描空间/会话/任务/对话 -> manifest -> 单个 ZIP 文件。"""
import datetime
import json
import os
import socket
import sys

import archive
import db
import paths


def platform_info():
    """当前运行平台信息（写入 manifest 与 /api/state）。"""
    return {"platform": sys.platform, "platform_name": paths._platform_name(sys.platform)}

# 忽略的空间内子目录/文件（缓存类，无迁移价值）
IGNORE_NAMES = set()


def get_output_dir():
    env = os.environ.get("WBMIGRATE_OUT")
    if env:
        d = os.path.normpath(env)
    else:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        d = desktop if os.path.isdir(desktop) else os.path.expanduser("~")
    out = os.path.join(d, "workbuddy-export")
    os.makedirs(paths.long_path(out), exist_ok=True)
    return out


def _dir_stats(root):
    """统计目录文件数与总字节。"""
    count, total = 0, 0
    for dirpath, _dirnames, filenames in os.walk(paths.long_path(root)):
        for fn in filenames:
            try:
                count += 1
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return count, total


def scan_state():
    """环境快照 + 空间发现（注册 ∪ 扫描）。"""
    root = paths.get_workbuddy_root()
    registered = {}
    try:
        for w in db.list_workspaces():
            registered[paths.norm_key(w["path"])] = w
    except Exception as e:
        registered = {}

    sessions = []
    try:
        sessions = db.list_sessions()
    except Exception:
        sessions = []

    tasks_dir = paths.get_tasks_dir()
    task_counts = {}
    if os.path.isdir(tasks_dir):
        for sid in os.listdir(tasks_dir):
            p = os.path.join(tasks_dir, sid)
            if os.path.isdir(p):
                task_counts[sid] = len([f for f in os.listdir(p) if f.endswith(".json")])

    # 会话按 cwd 归组
    sessions_by_ws = {}
    for s in sessions:
        cwd = s.get("cwd") or ""
        sessions_by_ws.setdefault(paths.norm_key(cwd), []).append(s)

    workspaces = []
    seen = set()
    # 1) 已注册空间（可能在 root 下也可能不在）
    for w in sorted(registered.values(), key=lambda x: -(x.get("last_opened_at") or 0)):
        key = paths.norm_key(w["path"])
        if key in seen:
            continue
        seen.add(key)
        exists = os.path.isdir(paths.long_path(w["path"]))
        fc, tb = _dir_stats(w["path"]) if exists else (0, 0)
        sids = sessions_by_ws.get(key, [])
        workspaces.append(_ws_entry(w["path"], w.get("last_opened_at"), True, exists, fc, tb, sids, task_counts))
    # 2) root 下未注册的文件夹
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if not os.path.isdir(paths.long_path(full)):
                continue
            key = paths.norm_key(full)
            if key in seen:
                continue
            seen.add(key)
            fc, tb = _dir_stats(full)
            sids = sessions_by_ws.get(key, [])
            workspaces.append(_ws_entry(full, None, False, True, fc, tb, sids, task_counts))

    proc = db.workbuddy_running()
    st = {
        "workbuddy_home": paths.get_workbuddy_home(),
        "workbuddy_root": root,
        "userprofile": os.path.expanduser("~"),
        "hostname": socket.gethostname(),
        "db_exists": db.db_exists(),
        "workspaces": workspaces,
        "disk_free": db.disk_free(get_output_dir()),
        "disk_free_path": get_output_dir(),
        "workbuddy_process": (proc if isinstance(proc, str) else bool(proc)),
        "output_dir": get_output_dir(),
    }
    st.update(platform_info())
    return st


def _ws_entry(path, last_opened, registered, exists, file_count, total_bytes, sids, task_counts):
    task_total = sum(task_counts.get(s["id"], 0) for s in sids)
    return {
        "path": path,
        "dir_name": os.path.basename(path.rstrip("\\/")),
        "registered": registered,
        "exists": exists,
        "last_opened_at": last_opened,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "session_count": len(sids),
        "task_count": task_total,
    }


def _walk_files(root):
    """返回 [(绝对路径, 相对正斜杠路径, size)]。"""
    out = []
    lroot = paths.long_path(root)
    for dirpath, dirnames, filenames in os.walk(lroot):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, lroot).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append((full, rel, size))
    return out


def run_export(job, workspace_paths, include_projects, out_dir=None):
    """执行导出主流程（在线程中运行）。"""
    root = paths.get_workbuddy_root()
    ws_registry = {paths.norm_key(w["path"]): w for w in db.list_workspaces()} if db.db_exists() else {}
    all_sessions = db.list_sessions() if db.db_exists() else []
    tasks_dir = paths.get_tasks_dir()
    projects_dir = paths.get_projects_dir()

    if out_dir:
        out_dir = os.path.normpath(out_dir)
        os.makedirs(paths.long_path(out_dir), exist_ok=True)
    else:
        out_dir = get_output_dir()

    job.update("扫描", 0, 0, "正在扫描选中的空间…")
    selected = []
    for p in workspace_paths:
        if not os.path.isdir(paths.long_path(p)):
            raise ValueError("空间文件夹不存在: %s" % p)
        selected.append(p)
    sel_keys = [paths.norm_key(p) for p in selected]

    # 文件清单
    file_lists = {}     # dir_name -> [(full, rel, size)]
    total_bytes = 0
    total_files = 0
    for p in selected:
        fl = _walk_files(p)
        file_lists[os.path.basename(p.rstrip("\\/"))] = fl
        total_files += len(fl)
        total_bytes += sum(x[2] for x in fl)

    # 相关会话（cwd 位于任一选中空间之下）
    rel_sessions = [s for s in all_sessions
                    if any(paths.path_startswith(s.get("cwd") or "", k) for k in
                           [sel for sel in selected])]
    session_ids = [s["id"] for s in rel_sessions]

    # 任务
    task_dirs = {}
    for sid in session_ids:
        p = os.path.join(tasks_dir, sid)
        if os.path.isdir(p):
            files = sorted(f for f in os.listdir(p) if f.endswith(".json"))
            if files:
                task_dirs[sid] = (p, files)

    # 对话转录（仅该会话自己的 jsonl，按会话归档避免重复）
    project_files = []   # (src_path, escaped_name, filename)
    if include_projects:
        seen_proj = set()
        for s in rel_sessions:
            cwd = s.get("cwd") or ""
            esc = paths.escape_project_name(cwd)
            fname = s["id"] + ".jsonl"
            src = os.path.join(projects_dir, esc, fname)
            if not os.path.isfile(src):
                # 官方 compressPath 不做大小写归一，磁盘文件夹名的大小写跟随
                # 会话进程当时的 cwd（如 'c-Users-...' vs 'C-Users-...'），
                # Win/Mac 文件系统不区分大小写，这里做一次忽略大小写的兜底。
                low = esc.lower()
                try:
                    for d in os.listdir(projects_dir):
                        if d.lower() == low and os.path.isdir(os.path.join(projects_dir, d)):
                            src = os.path.join(projects_dir, d, fname)
                            break
                except OSError:
                    pass
            if os.path.isfile(src) and (esc, fname) not in seen_proj:
                seen_proj.add((esc, fname))
                project_files.append((src, esc, fname))

    # manifest
    ws_meta = []
    for p in selected:
        dn = os.path.basename(p.rstrip("\\/"))
        fl = file_lists[dn]
        reg = ws_registry.get(paths.norm_key(p))
        ws_meta.append({
            "path": p,
            "dir_name": dn,
            "last_opened_at": reg.get("last_opened_at") if reg else None,
            "file_count": len(fl),
            "total_bytes": sum(x[2] for x in fl),
        })
    task_summary = {}
    for sid in session_ids:
        d = task_dirs.get(sid)
        ses = next((s for s in rel_sessions if s["id"] == sid), {})
        task_summary[sid] = {
            "task_count": len(d[1]) if d else 0,
            "cwd": ses.get("cwd"),
            "title": ses.get("custom_title") or ses.get("title"),
        }

    entries = 1 + 3 + sum(len(fl) for fl in file_lists.values()) + len(file_lists) \
        + sum(len(v[1]) for v in task_dirs.values()) + len(project_files)
    src_info = {
        "userprofile": os.path.expanduser("~"),
        "workbuddy_root": root,
        "hostname": socket.gethostname(),
    }
    src_info.update(platform_info())
    manifest = {
        "format": archive.FORMAT_ID,
        "version": archive.FORMAT_VERSION,
        "created_at": db.now_ms(),
        "source": src_info,
        "include_projects": include_projects,
        "workspaces": ws_meta,
        "session_ids": session_ids,
        "task_summary": task_summary,
        "totals": {
            "files": total_files,
            "bytes": total_bytes,
            "entries": entries,
        },
    }

    # 打包
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(out_dir, "workbuddy-export-%s.zip" % ts)
    job.update("打包", 0, max(total_bytes, 1), "正在打包…")
    zw = archive.ZipWriter(zip_path)
    done_bytes = [0]

    def bump(n):
        done_bytes[0] += n
        job.update("打包", done_bytes[0], max(total_bytes, 1), "")

    try:
        zw.write_bytes("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        zw.write_bytes("db/workspaces.json",
                       json.dumps([w for w in (ws_registry.get(paths.norm_key(p)) for p in selected) if w],
                                  ensure_ascii=False).encode("utf-8"))
        zw.write_bytes("db/sessions.json",
                       json.dumps(rel_sessions, ensure_ascii=False, default=str).encode("utf-8"))
        zw.write_bytes("db/automations.json", b"[]")
        for dn, fl in file_lists.items():
            lines = []
            for full, rel, _size in fl:
                lines.append("%s  %s" % (archive.sha256_file(full), rel))
                job.check_cancel()
            zw.write_bytes("files/%s.sha256" % dn, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))
            for full, rel, size in fl:
                job.check_cancel()
                arc = "files/%s/%s" % (dn, rel)
                n = zw.write_file(arc, full)
                bump(n)
        for sid, (p, files) in task_dirs.items():
            for f in files:
                job.check_cancel()
                zw.write_file("tasks/%s/%s" % (sid, f), os.path.join(p, f))
        for src, esc, f in project_files:
            job.check_cancel()
            zw.write_file("projects/%s/%s" % (esc, f), src)
    finally:
        zw.close()

    zip_size = os.path.getsize(zip_path)
    job.update("校验", 1, 1, "正在校验导出包…")
    zf, n_entries, _ = archive.inspect_zip(zip_path, expected_totals=manifest["totals"])
    zf.close()

    job.finish({
        "zip_path": zip_path,
        "zip_size": zip_size,
        "entries": n_entries,
        "workspaces": len(selected),
        "sessions": len(session_ids),
        "tasks": sum(len(v[1]) for v in task_dirs.values()),
        "files": total_files,
        "bytes": total_bytes,
        "sha256": archive.sha256_file(zip_path),
        "include_projects": include_projects,
    })
