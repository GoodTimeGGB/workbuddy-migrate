# -*- coding: utf-8 -*-
"""WorkBuddy 迁移工具 - 本地 HTTP 服务入口。

用法：python server.py [端口]
默认端口 8765，被占用时自动 +1 递试（最多 20 个）。
"""
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import exporter
import importer
import jobs
import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD = 2 * 1024 ** 3  # 2GB

# ---------------- 状态缓存 ----------------
# scan_state 需要全量遍历各空间统计文件大小，大目录可能耗时几十秒。
# 因此后台线程扫描 + 缓存，/api/state 立即返回缓存，避免请求长时间挂起。
_state_lock = threading.Lock()
_state_cache = None      # 最近一次完整扫描结果
_state_scanning = False


def _scan_worker():
    global _state_cache, _state_scanning
    try:
        snap = exporter.scan_state()
        snap["scanning"] = False
        with _state_lock:
            _state_cache = snap
    except Exception as e:
        with _state_lock:
            _state_cache = {
                "scanning": False,
                "error": "扫描本机状态失败: %s" % e,
                "workspaces": [],
            }
    finally:
        with _state_lock:
            _state_scanning = False


def _start_scan():
    global _state_scanning
    with _state_lock:
        if _state_scanning:
            return
        _state_scanning = True
    threading.Thread(target=_scan_worker, daemon=True).start()


def _state_snapshot():
    """立即返回可用状态：有缓存给缓存；没缓存给轻量骨架（scanning=true）。"""
    with _state_lock:
        if _state_cache is not None:
            return dict(_state_cache)
    # 轻量骨架：不做任何目录遍历
    out_dir = exporter.get_output_dir()
    return {
        "scanning": True,
        "workbuddy_home": paths.get_workbuddy_home(),
        "workbuddy_root": paths.get_workbuddy_root(),
        "userprofile": os.path.expanduser("~"),
        "hostname": socket.gethostname(),
        "db_exists": db.db_exists(),
        "workspaces": [],
        "disk_free": db.disk_free(out_dir),
        "disk_free_path": out_dir,
        "workbuddy_process": False,
        "output_dir": out_dir,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WorkBuddyMigrate/1.0"

    # ---------------- helpers ----------------

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg, code=400):
        self._send_json({"error": str(msg)}, code)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_UPLOAD:
            raise ValueError("上传文件过大（>2GB）")
        return self.rfile.read(length)

    def log_message(self, fmt, *args):  # 安静模式
        pass

    # ---------------- GET ----------------

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._serve_index()
        if path == "/api/ping":
            # 轻量探活端点，供启动器健康检查使用，不做任何目录扫描
            return self._send_json({"ok": True})
        if path == "/api/state":
            return self._send_json(_state_snapshot())
        if path == "/api/state/refresh":
            _start_scan()
            return self._send_json({"scanning": True})
        if path.startswith("/api/job/"):
            job = jobs.get_job(path.split("/api/job/")[1])
            if not job:
                return self._error("任务不存在或已过期", 404)
            return self._send_json(job.snapshot())
        if path.startswith("/api/import/preview/"):
            job = jobs.get_job(path.split("/api/import/preview/")[1])
            if not job or job.status != "staged":
                return self._error("预览不存在（任务可能已完成或失败）", 404)
            preview = job.result
            public = json.loads(json.dumps(preview, ensure_ascii=False, default=str))
            public.pop("temp_dir", None)
            for w in public.get("workspaces", []):
                w.pop("_corrupt_full", None)
            return self._send_json(public)
        if path == "/api/open-folder":
            # 用浏览器自身无法打开本地文件夹，返回路径由前端提示；此处保留兼容
            return self._error("not supported", 404)
        return self._error("not found", 404)

    def _serve_index(self):
        idx = os.path.join(BASE_DIR, "web", "index.html")
        with open(idx, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---------------- POST ----------------

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/export/start":
                return self._export_start()
            if path == "/api/import/upload":
                return self._import_upload()
            if path == "/api/import/apply":
                return self._import_apply()
            if path.startswith("/api/import/cancel/"):
                jid = path.split("/api/import/cancel/")[1]
                ok = jobs.cancel_job(jid)
                return self._send_json({"canceled": ok})
            if path == "/api/shell-open":
                return self._shell_open()
            if path == "/api/pick-folder":
                return self._pick_folder()
            if path == "/api/disk-free":
                return self._disk_free()
            return self._error("not found", 404)
        except Exception as e:
            return self._error("服务器内部错误: %s" % e, 500)

    def _export_start(self):
        req = json.loads(self._read_body().decode("utf-8"))
        # 规范化路径：容忍正斜杠/双反斜杠等写法
        ws_paths = [os.path.normpath(p) for p in (req.get("workspace_paths") or []) if p]
        include_projects = bool(req.get("include_projects"))
        out_dir = req.get("out_dir") or None
        if out_dir:
            out_dir = os.path.normpath(out_dir)
        if not ws_paths:
            return self._error("请至少选择一个空间")
        job = jobs.new_job("export")
        jobs.run_in_thread(
            job,
            lambda j: exporter.run_export(j, ws_paths, include_projects, out_dir))
        self._send_json({"job_id": job.id})

    def _import_upload(self):
        import tempfile
        data = self._read_body()
        if not data:
            return self._error("上传内容为空")
        # 先落盘再校验，避免大文件占内存
        tmp = tempfile.NamedTemporaryFile(prefix="wbmigrate-upload-",
                                          suffix=".zip", delete=False)
        tmp.write(data)
        tmp.close()
        job = jobs.new_job("import-stage")

        def fn(j):
            try:
                importer.stage_import(j, tmp.name)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        jobs.run_in_thread(job, fn)
        self._send_json({"job_id": job.id})

    def _import_apply(self):
        req = json.loads(self._read_body().decode("utf-8"))
        job = jobs.get_job(req.get("job_id") or "")
        if not job or job.status != "staged":
            return self._error("任务不存在或不在可导入状态", 404)
        strategy = req.get("strategy") or "merge"
        if strategy not in importer.STRATEGIES:
            return self._error("无效策略: %s" % strategy)
        preview = job.result
        apply_job = jobs.new_job("import-apply")
        jobs.run_in_thread(apply_job,
                           lambda j: importer.apply_import(j, preview, strategy))
        # 原 staged 任务标记完成，避免重复 apply
        job.finish({"applied": True, "apply_job_id": apply_job.id})
        self._send_json({"job_id": apply_job.id})

    def _shell_open(self):
        req = json.loads(self._read_body().decode("utf-8"))
        target = req.get("path") or ""
        if not os.path.isabs(target):
            return self._error("无效路径")
        try:
            if sys.platform == "win32":
                os.startfile(target)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            self._send_json({"ok": True})
        except Exception as e:
            self._error("打开失败: %s" % e)

    def _pick_folder(self):
        req = json.loads(self._read_body().decode("utf-8"))
        initial = req.get("initial_dir") or os.path.expanduser("~")
        try:
            if sys.platform == "win32":
                path = _pick_folder_windows(initial)
            elif sys.platform == "darwin":
                path = _pick_folder_macos(initial)
            else:
                path = _pick_folder_linux(initial)
        except Exception as e:
            return self._error("选择文件夹失败: %s" % e)
        if path and os.path.isdir(path):
            self._send_json({"path": path, "disk_free": db.disk_free(path)})
        else:
            self._send_json({"path": "", "canceled": True})

    def _disk_free(self):
        req = json.loads(self._read_body().decode("utf-8"))
        p = req.get("path") or ""
        if p:
            p = os.path.normpath(p)
        else:
            p = exporter.get_output_dir()
        self._send_json({"path": p, "disk_free": db.disk_free(p)})


def _pick_folder_windows(initial):
    ps = (
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$d = New-Object System.Windows.Forms.FolderBrowserDialog; '
        '$d.Description = "选择导出保存位置"; '
        '$d.SelectedPath = "%s"; '
        '$d.ShowNewFolderButton = $true; '
        'if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { '
        '    Write-Output $d.SelectedPath '
        '} else { '
        '    Write-Output "" '
        '}'
    ) % initial.replace("\"", "`\"").replace("\n", " ")
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=30, encoding="utf-8")
    return r.stdout.strip().split("\n")[-1].strip()


def _pick_folder_macos(initial):
    initial = os.path.abspath(os.path.expanduser(initial))
    script = (
        'tell application "System Events"\n'
        '    activate\n'
        '    set f to choose folder with prompt "选择导出保存位置" '
        'default location (POSIX file "%s")\n'
        '    POSIX path of f\n'
        'end tell'
    ) % initial.replace('"', '\\"')
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=60, encoding="utf-8")
    return r.stdout.strip()


def _pick_folder_linux(initial):
    # 优先 zenity，没有则回退到手动输入
    if subprocess.run(["which", "zenity"], capture_output=True).returncode == 0:
        initial = os.path.abspath(os.path.expanduser(initial))
        r = subprocess.run(
            ["zenity", "--file-selection", "--directory",
             "--filename=%s" % initial],
            capture_output=True, text=True, timeout=60, encoding="utf-8")
        return r.stdout.strip()
    return ""


def find_port(start):
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    port = find_port(port) or (port + 100)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d" % port
    print("=" * 52)
    print("  WorkBuddy 迁移工具已启动")
    print("  请在浏览器访问: %s" % url)
    print("  关闭此窗口即退出工具（不影响 WorkBuddy 本体）")
    print("=" * 52)
    # 绑定成功后立即在后台开始扫描本机状态，/api/state 随时可秒回
    _start_scan()
    # 浏览器由 launch.ps1 / start.bat 统一打开，server.py 不再主动打开，避免重复标签页
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
