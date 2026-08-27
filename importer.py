# -*- coding: utf-8 -*-
"""导入：上传暂存 -> 解析预览 -> 冲突计算 -> 执行导入（备份 + 原子写 + 事务）。"""
import json
import os
import shutil
import sqlite3
import tempfile

import archive
import db
import paths

STRATEGIES = ("skip", "overwrite", "merge")


# ---------------------------------------------------------------- staging

def stage_import(job, zip_path):
    """解析并校验导出包，生成预览数据（线程中运行）。"""
    job.update("校验", 0, 3, "正在检查导出包…")
    zf, entries, total_unc = archive.inspect_zip(zip_path)
    temp_dir = None
    try:
        manifest = archive.load_manifest(zf)
        job.update("校验", 1, 3, "导出包格式正确，正在解压…")
        temp_dir = tempfile.mkdtemp(prefix="wbmigrate-")
        _written, skipped_entries = archive.safe_extract_all(
            zf, temp_dir, on_progress=lambda d, t: job.update("解压", d, t, ""))

        job.update("校验", 2, 3, "正在校验文件完整性（SHA256）…")
        corrupt = _verify_checksums(temp_dir, manifest, job)
        # 解压阶段无法写入的条目（跨系统文件名不兼容等）并入损坏清单，导入时跳过
        for ent in skipped_entries:
            dn = ent["name"].split("/", 2)[1] if "/" in ent["name"] else ""
            if dn:
                corrupt.setdefault(dn, []).append(
                    ent["name"].split("/", 2)[2] + " (本机系统不支持该文件名)")

        job.update("校验", 3, 3, "正在生成本机冲突对比…")
        preview = _build_preview(temp_dir, manifest, corrupt, entries, total_unc)
        job.stage(preview)
        return preview
    except Exception:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        try:
            zf.close()
        except Exception:
            pass


def _verify_checksums(temp_dir, manifest, job):
    """返回 {dir_name: [损坏相对路径...]}。"""
    corrupt = {}
    files_root = os.path.join(temp_dir, "files")
    for ws in manifest.get("workspaces", []):
        dn = ws["dir_name"]
        bad = []
        sha_file = os.path.join(files_root, dn + ".sha256")
        ws_dir = os.path.join(files_root, dn)
        if not os.path.isdir(ws_dir):
            corrupt[dn] = ["<整个空间文件夹缺失>"]
            continue
        if os.path.isfile(sha_file):
            with open(sha_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    parts = line.split("  ", 1)
                    if len(parts) != 2:
                        continue
                    expected, rel = parts
                    src = os.path.join(ws_dir, *rel.split("/"))
                    if not os.path.isfile(src):
                        bad.append(rel + " (缺失)")
                    elif archive.sha256_file(src) != expected:
                        bad.append(rel)
                    job.check_cancel()
        corrupt[dn] = bad
    return corrupt


def _source_platform(manifest):
    """源包平台：优先取 manifest.source.platform，缺失时按路径形态推断。"""
    src = manifest.get("source") or {}
    plat = src.get("platform")
    if plat:
        return plat
    samples = [ws.get("path", "") for ws in manifest.get("workspaces", [])]
    samples.append(src.get("workbuddy_root") or "")
    return "win32" if any(paths.is_windows_path(x) for x in samples) else "darwin"


def _build_preview(temp_dir, manifest, corrupt, entries, total_unc):
    src_root = (manifest.get("source") or {}).get("workbuddy_root") or ""
    dst_root = paths.get_workbuddy_root()
    ws_rows = []
    try:
        ws_rows = json.load(open(os.path.join(temp_dir, "db", "workspaces.json"),
                                 "r", encoding="utf-8"))
    except Exception:
        ws_rows = []
    local_ws = {}
    try:
        for w in db.list_workspaces():
            local_ws[paths.norm_key(w["path"])] = w
    except Exception:
        local_ws = {}
    local_sessions = {}
    try:
        for s in db.list_sessions():
            local_sessions[s["id"]] = s
    except Exception:
        local_sessions = {}
    tasks_dir = paths.get_tasks_dir()

    # 空间预览
    ws_preview = []
    for ws in manifest.get("workspaces", []):
        dn = ws["dir_name"]
        target = paths.rewrite_path(ws["path"], src_root, dst_root)
        if paths.norm_key(target) == paths.norm_key(ws["path"]) and src_root and \
                not paths.path_startswith(ws["path"], src_root):
            target = os.path.join(dst_root, dn)  # 源路径不在源根下时落到目标根
        tk = paths.norm_key(target)
        exists = os.path.isdir(paths.long_path(target))
        # 冲突文件数（同名文件）
        conflict_files = 0
        if exists:
            src_ws_dir = os.path.join(temp_dir, "files", dn)
            for _dirpath, _dn, filenames in os.walk(src_ws_dir):
                rel = os.path.relpath(_dirpath, src_ws_dir)
                for fn in filenames:
                    rel_fn = fn if rel == "." else os.path.join(rel, fn)
                    if os.path.exists(os.path.join(paths.long_path(target), rel_fn)):
                        conflict_files += 1
        ws_preview.append({
            "dir_name": dn,
            "source_path": ws["path"],
            "target_path": target,
            "exists_local": exists,
            "registered_local": tk in local_ws,
            "conflict_files": conflict_files,
            "corrupt_files": len(corrupt.get(dn, [])),
            "corrupt_list": corrupt.get(dn, [])[:20],
            "_corrupt_full": corrupt.get(dn, []),
            "file_count": ws.get("file_count", 0),
            "total_bytes": ws.get("total_bytes", 0),
        })

    # 会话/任务预览
    task_summary = manifest.get("task_summary", {})
    sess_preview = []
    for sid in manifest.get("session_ids", []):
        info = task_summary.get(sid, {})
        cwd_src = info.get("cwd") or ""
        cwd_dst = paths.rewrite_path(cwd_src, src_root, dst_root)
        local_task_dir = os.path.join(tasks_dir, sid)
        has_local_tasks = os.path.isdir(local_task_dir) and \
            any(f.endswith(".json") for f in os.listdir(local_task_dir))
        src_task_dir = os.path.join(temp_dir, "tasks", sid)
        src_task_count = 0
        if os.path.isdir(src_task_dir):
            src_task_count = len([f for f in os.listdir(src_task_dir) if f.endswith(".json")])
        sess_preview.append({
            "id": sid,
            "title": info.get("title") or "(无标题)",
            "cwd_source": cwd_src,
            "cwd_target": cwd_dst,
            "task_count": info.get("task_count", src_task_count),
            "exists_local": sid in local_sessions,
            "task_conflict": has_local_tasks,
        })

    # 对话记录预览
    proj_preview = []
    projects_src = os.path.join(temp_dir, "projects")
    if os.path.isdir(projects_src):
        for esc in sorted(os.listdir(projects_src)):
            pdir = os.path.join(projects_src, esc)
            if not os.path.isdir(pdir):
                continue
            for f in sorted(os.listdir(pdir)):
                if not f.endswith(".jsonl"):
                    continue
                sid = f[:-6]
                cwd_src = (task_summary.get(sid) or {}).get("cwd") or ""
                cwd_dst = paths.rewrite_path(cwd_src, src_root, dst_root)
                new_esc = paths.escape_project_name(cwd_dst) if cwd_dst else esc
                local_p = os.path.join(paths.get_projects_dir(), new_esc, f)
                proj_preview.append({
                    "session_id": sid,
                    "source_folder": esc,
                    "target_folder": new_esc,
                    "size": os.path.getsize(os.path.join(pdir, f)),
                    "exists_local": os.path.exists(local_p),
                })

    return {
        "temp_dir": temp_dir,
        "manifest_summary": {
            "created_at": manifest.get("created_at"),
            "source_host": (manifest.get("source") or {}).get("hostname"),
            "source_platform": _source_platform(manifest),
            "source_root": src_root,
            "target_root": dst_root,
            "include_projects": manifest.get("include_projects", False),
            "entries": entries,
            "uncompressed_bytes": total_unc,
        },
        "workspaces": ws_preview,
        "sessions": sess_preview,
        "projects": proj_preview,
    }


# ---------------------------------------------------------------- apply

def apply_import(job, preview, strategy):
    """执行导入（线程中运行）。"""
    if strategy not in STRATEGIES:
        raise ValueError("未知策略: %r" % strategy)
    temp_dir = preview["temp_dir"]
    manifest_summary = preview["manifest_summary"]
    src_root = manifest_summary["source_root"]
    dst_root = manifest_summary["target_root"]
    tasks_dir = paths.get_tasks_dir()
    projects_dir = paths.get_projects_dir()

    # WorkBuddy 进程检测
    job.update("预检", 0, 1, "正在检查 WorkBuddy 是否运行…")
    proc = db.workbuddy_running()
    if proc:
        raise RuntimeError("检测到 WorkBuddy 正在运行（%s）。请先完全退出 WorkBuddy（含托盘图标）再执行导入，"
                           "避免数据写入冲突。" % proc)

    # 磁盘空间：按预览总量 1.2 倍估算
    need = sum(w["total_bytes"] for w in preview["workspaces"]) * 1.2 + 64 * 1024 * 1024
    free = db.disk_free(dst_root)
    if free is not None and free < need:
        raise RuntimeError("目标磁盘空间不足：需要约 %.0fMB，剩余 %.0fMB。"
                           % (need / 1048576.0, free / 1048576.0))

    stats = {
        "workspaces_registered": 0, "workspaces_kept": 0,
        "files_copied": 0, "files_replaced": 0, "files_skipped": 0,
        "files_merged_kept_local": 0, "files_corrupt_skipped": 0,
        "bytes_copied": 0,
        "sessions_inserted": 0, "sessions_skipped": 0, "sessions_updated": 0,
        "tasks_written": 0, "tasks_skipped": 0,
        "projects_written": 0,
    }
    failures = []
    corrupt = {w["dir_name"]: set(w["corrupt_list"]) for w in preview["workspaces"]}

    # 读取导出包 DB 数据
    workspaces_rows = _load_json(temp_dir, "db/workspaces.json", [])
    sessions_rows = _load_json(temp_dir, "db/sessions.json", [])

    total_steps = sum(w["file_count"] for w in preview["workspaces"]) + \
        len(preview["sessions"]) + len(preview["projects"]) + 10
    step = [0]

    def tick(msg):
        step[0] += 1
        job.update("导入", step[0], total_steps, msg or "")

    # ---------- 备份 ----------
    tick("正在备份现有数据…")
    backup_dir = os.path.join(paths.get_backup_base(),
                              __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S"))
    _backup_existing(preview, tasks_dir, backup_dir, strategy)

    # ---------- 空间文件 ----------
    for wp in preview["workspaces"]:
        dn = wp["dir_name"]
        target = wp["target_path"]
        src_ws = os.path.join(temp_dir, "files", dn)
        corrupt_set = set(wp.get("_corrupt_full") or [])
        if not os.path.isdir(src_ws):
            tick("")
            continue
        if wp["exists_local"] and strategy == "skip":
            stats["files_skipped"] += wp["file_count"]
            tick("空间 %s 已存在，跳过" % dn)
            continue
        os.makedirs(paths.long_path(target), exist_ok=True)
        for dirpath, dirnames, filenames in os.walk(src_ws):
            dirnames.sort()
            rel_dir = os.path.relpath(dirpath, src_ws)
            dst_dir = target if rel_dir == "." else os.path.join(target, rel_dir)
            os.makedirs(paths.long_path(dst_dir), exist_ok=True)
            for fn in sorted(filenames):
                job.check_cancel()
                rel_fn = fn if rel_dir == "." else rel_dir.replace("\\", "/") + "/" + fn
                src_f = os.path.join(dirpath, fn)
                dst_f = os.path.join(dst_dir, fn)
                tick("复制 " + rel_fn)
                rel_norm = rel_fn.replace("\\", "/")
                if rel_norm in corrupt_set:
                    stats["files_corrupt_skipped"] += 1
                    failures.append({"item": dn + "/" + rel_fn, "reason": "校验和不符，已跳过"})
                    continue
                dst_exists = os.path.exists(paths.long_path(dst_f))
                if dst_exists:
                    if strategy == "merge":
                        src_mtime = os.path.getmtime(src_f)
                        dst_mtime = os.path.getmtime(paths.long_path(dst_f))
                        # ZIP 时间戳为 2 秒精度，加 2 秒容差：视为"相同或更新则保留本机"
                        if dst_mtime + 2 >= src_mtime:
                            stats["files_merged_kept_local"] += 1
                            continue
                    elif strategy == "skip":
                        stats["files_skipped"] += 1
                        continue
                try:
                    _atomic_copy(src_f, dst_f)
                    stats["bytes_copied"] += os.path.getsize(src_f)
                    if dst_exists:
                        stats["files_replaced"] += 1
                    else:
                        stats["files_copied"] += 1
                except Exception as e:
                    failures.append({"item": dn + "/" + rel_fn,
                                     "reason": "复制失败: %s" % e})

    # ---------- DB（空间注册 + 会话） ----------
    job.update("导入DB", step[0], total_steps, "正在写入数据库…")
    if db.db_exists():
        target_user_id = db.get_dominant_user_id()
        local_ws = db.list_workspaces()
        local_ws_keys = {paths.norm_key(w["path"]) for w in local_ws}
        local_ws_map = {paths.norm_key(w["path"]): w for w in local_ws}
        local_sessions = {s["id"]: s for s in db.list_sessions()}

        new_ws_rows = []
        for r in workspaces_rows:
            src_p = r.get("path") or ""
            if paths.path_startswith(src_p, src_root):
                tgt = paths.rewrite_path(src_p, src_root, dst_root)
            else:
                tgt = os.path.join(dst_root, os.path.basename(src_p.rstrip("\\/")))
            row = {"path": tgt, "last_opened_at": r.get("last_opened_at")}
            key = paths.norm_key(tgt)
            if key in local_ws_keys:
                stats["workspaces_kept"] += 1
                if strategy == "overwrite":
                    new_ws_rows.append(row)
                    stats["workspaces_registered"] += 1
                elif strategy == "merge":
                    old = local_ws_map[key].get("last_opened_at") or 0
                    if (row["last_opened_at"] or 0) > old:
                        new_ws_rows.append(row)
                        stats["workspaces_registered"] += 1
                # skip: 不动
            else:
                new_ws_rows.append(row)
                stats["workspaces_registered"] += 1

        new_sessions = []
        for s in sessions_rows:
            sid = s.get("id")
            if not sid:
                continue
            cwd = s.get("cwd") or ""
            s = dict(s)
            s["cwd"] = paths.rewrite_path(cwd, src_root, dst_root)
            if target_user_id:
                s["user_id"] = target_user_id
            if sid in local_sessions:
                if strategy == "skip":
                    stats["sessions_skipped"] += 1
                elif strategy == "overwrite":
                    new_sessions.append(s)
                    stats["sessions_updated"] += 1
                else:  # merge
                    old_updated = local_sessions[sid].get("updated_at") or 0
                    if (s.get("updated_at") or 0) > old_updated:
                        new_sessions.append(s)
                        stats["sessions_updated"] += 1
                    else:
                        stats["sessions_skipped"] += 1
            else:
                new_sessions.append(s)
                stats["sessions_inserted"] += 1

        conn = sqlite3.connect(paths.long_path(paths.get_db_path()), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            db.upsert_workspaces(conn, new_ws_rows)
            db.upsert_sessions(conn, new_sessions)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        step[0] += 5

    # ---------- 任务文件 ----------
    tasks_src = os.path.join(temp_dir, "tasks")
    if os.path.isdir(tasks_src):
        for sp in preview["sessions"]:
            sid = sp["id"]
            src_dir = os.path.join(tasks_src, sid)
            if not os.path.isdir(src_dir):
                continue
            for fn in sorted(os.listdir(src_dir)):
                if not fn.endswith(".json"):
                    continue
                job.check_cancel()
                tick("任务 %s/%s" % (sid[:8], fn))
                dst_f = os.path.join(tasks_dir, sid, fn)
                if os.path.exists(paths.long_path(dst_f)):
                    if strategy == "skip":
                        stats["tasks_skipped"] += 1
                        continue
                    if strategy == "merge":
                        newer = _src_task_newer(os.path.join(src_dir, fn), dst_f)
                        if not newer:
                            stats["tasks_skipped"] += 1
                            continue
                try:
                    os.makedirs(paths.long_path(os.path.dirname(dst_f)), exist_ok=True)
                    _atomic_copy(os.path.join(src_dir, fn), dst_f)
                    stats["tasks_written"] += 1
                except Exception as e:
                    failures.append({"item": "tasks/%s/%s" % (sid, fn),
                                     "reason": "写入失败: %s" % e})

    # ---------- 对话记录 ----------
    projects_src = os.path.join(temp_dir, "projects")
    if os.path.isdir(projects_src) and preview["projects"]:
        for pp in preview["projects"]:
            job.check_cancel()
            tick("对话记录 " + pp["session_id"][:8])
            src_f = os.path.join(projects_src, pp["source_folder"],
                                 pp["session_id"] + ".jsonl")
            dst_f = os.path.join(projects_dir, pp["target_folder"],
                                 pp["session_id"] + ".jsonl")
            try:
                if os.path.exists(paths.long_path(dst_f)) and strategy == "skip":
                    continue
                os.makedirs(paths.long_path(os.path.dirname(dst_f)), exist_ok=True)
                _atomic_copy(src_f, dst_f)
                stats["projects_written"] += 1
            except Exception as e:
                failures.append({"item": "projects/%s" % pp["session_id"],
                                 "reason": "写入失败: %s" % e})

    tick("收尾…")
    # 清理暂存
    shutil.rmtree(temp_dir, ignore_errors=True)

    job.finish({
        "strategy": strategy,
        "backup_dir": backup_dir,
        "stats": stats,
        "failures": failures,
    })


# ---------------------------------------------------------------- helpers

def _load_json(base, rel, default):
    p = os.path.join(base, *rel.split("/"))
    if not os.path.isfile(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_copy(src, dst):
    tmp = dst + ".migrate_tmp"
    shutil.copyfile(paths.long_path(src), paths.long_path(tmp))
    os.replace(paths.long_path(tmp), paths.long_path(dst))


def _src_task_newer(src, dst):
    def updated(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f).get("updatedAt") or 0
        except Exception:
            return 0
    return updated(src) > updated(dst)


def _backup_existing(preview, tasks_dir, backup_dir, strategy):
    """应用前备份：DB 三件套 + 将被覆盖的任务文件 + 空间内将被覆盖的文件清单。"""
    os.makedirs(paths.long_path(backup_dir), exist_ok=True)
    backed = []
    if db.db_exists():
        try:
            backed += db.backup_db(backup_dir)
        except Exception:
            pass
    if strategy == "skip":
        return backed
    # 任务文件
    for sp in preview["sessions"]:
        sid = sp["id"]
        src_dir = os.path.join(preview["temp_dir"], "tasks", sid)
        if not os.path.isdir(src_dir):
            continue
        for fn in os.listdir(src_dir):
            local = os.path.join(tasks_dir, sid, fn)
            if os.path.exists(local):
                rel = os.path.join("tasks", sid, fn)
                dst = os.path.join(backup_dir, "tasks", sid)
                os.makedirs(paths.long_path(dst), exist_ok=True)
                try:
                    shutil.copy2(paths.long_path(local), paths.long_path(os.path.join(dst, fn)))
                    backed.append(rel)
                except Exception:
                    pass
    # 空间内同名冲突文件（只备份已存在同名的，防覆盖丢失）
    if strategy == "overwrite":
        for wp in preview["workspaces"]:
            if not wp["exists_local"]:
                continue
            src_ws = os.path.join(preview["temp_dir"], "files", wp["dir_name"])
            for dirpath, _dn, filenames in os.walk(src_ws):
                for fn in filenames:
                    rel = os.path.relpath(os.path.join(dirpath, fn), src_ws)
                    local = os.path.join(wp["target_path"], rel)
                    if os.path.exists(local):
                        dst = os.path.join(backup_dir, "files", wp["dir_name"],
                                           os.path.dirname(rel))
                        os.makedirs(paths.long_path(dst), exist_ok=True)
                        try:
                            shutil.copy2(paths.long_path(local),
                                         paths.long_path(os.path.join(backup_dir, "files",
                                                                      wp["dir_name"], rel)))
                            backed.append(os.path.join(wp["dir_name"], rel))
                        except Exception:
                            pass
    with open(os.path.join(backup_dir, "backup-list.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(backed) + ("\n" if backed else ""))
    return backed
