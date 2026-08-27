# -*- coding: utf-8 -*-
"""ZIP 写入 / 安全解压 / SHA256 校验 / zip-slip 与 zip 炸弹防护。"""
import hashlib
import os
import zipfile

import paths

FORMAT_ID = "workbuddy-migrate-export"
FORMAT_VERSION = 1

MAX_ENTRIES = 100000          # 条目数上限
MAX_TOTAL_UNCOMPRESSED = 10 * 1024 ** 3  # 解压总字节上限 10GB


class ArchiveError(Exception):
    pass


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(paths.long_path(path), "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------- 写侧 ----------------

class ZipWriter(object):
    """带进度的 ZIP 写入器（ZIP_DEFLATED）。"""

    def __init__(self, zip_path):
        self.zip_path = zip_path
        self.zf = zipfile.ZipFile(paths.long_path(zip_path), "w", zipfile.ZIP_DEFLATED)
        self.entries = 0
        self.bytes_in = 0  # 未压缩字节累计

    def write_bytes(self, arcname, data):
        self.zf.writestr(arcname, data)
        self.entries += 1
        self.bytes_in += len(data)

    def write_file(self, arcname, src_path):
        import time as _time
        st = os.stat(paths.long_path(src_path))
        dt = _time.localtime(st.st_mtime)[:6]
        info = zipfile.ZipInfo(arcname, date_time=dt)
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        with open(paths.long_path(src_path), "rb") as f:
            data = f.read()
        self.zf.writestr(info, data)
        self.entries += 1
        self.bytes_in += len(data)
        return len(data)

    def close(self):
        self.zf.close()


# ---------------- 读侧 ----------------

def check_zip_member(name):
    """校验 zip 成员名安全（防 zip-slip）。"""
    if not name:
        raise ArchiveError("zip 内存在空文件名")
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        raise ArchiveError("zip 内存在绝对路径条目: %s" % name)
    parts = n.split("/")
    if any(p == ".." for p in parts):
        raise ArchiveError("zip 内存在路径穿越条目: %s" % name)


def inspect_zip(zip_path, expected_totals=None):
    """打开前先做炸弹检查，返回 (zf, entries, total_uncompressed)。"""
    try:
        zf = zipfile.ZipFile(paths.long_path(zip_path), "r")
    except zipfile.BadZipFile:
        raise ArchiveError("文件不是有效的 ZIP（可能传输中损坏或被截断），请重新传输后再试。")
    try:
        infos = zf.infolist()
        entries = len(infos)
        total = sum(i.file_size for i in infos)
        if entries > MAX_ENTRIES:
            raise ArchiveError("zip 条目数异常（%d > %d），疑似压缩包异常，已拒绝。"
                               % (entries, MAX_ENTRIES))
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise ArchiveError("zip 解压后总大小异常（%.1fGB > 10GB），已拒绝。"
                               % (total / 1024.0 ** 3))
        for i in infos:
            check_zip_member(i.filename)
        if expected_totals:
            if "entries" in expected_totals and expected_totals["entries"] not in (None, -1):
                if abs(entries - expected_totals["entries"]) > 50:
                    raise ArchiveError("zip 条目数与 manifest 记录不符（%d vs %d），文件可能损坏。"
                                       % (entries, expected_totals["entries"]))
        return zf, entries, total
    except Exception:
        try:
            zf.close()
        except Exception:
            pass
        raise


def safe_extract_all(zf, dest_dir, on_progress=None):
    """逐条目安全解压到 dest_dir，带炸弹计数与进度回调。

    跨系统容错：源包内不符合本机文件系统规范的条目（如 macOS 包里的
    Windows 保留名）会跳过并记录，不中断整体解压。
    返回 (written_bytes, skipped_list)；skipped 每项 {"name", "reason"}。
    on_progress(done_entries, total_entries)
    """
    os.makedirs(paths.long_path(dest_dir), exist_ok=True)
    infos = [i for i in zf.infolist() if not i.is_dir()]
    total = len(infos)
    written = 0
    skipped = []
    for idx, info in enumerate(infos):
        name = info.filename.replace("\\", "/")
        check_zip_member(name)
        target = os.path.join(dest_dir, *name.split("/"))
        try:
            os.makedirs(paths.long_path(os.path.dirname(target)), exist_ok=True)
            with zf.open(info) as src, open(paths.long_path(target), "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_TOTAL_UNCOMPRESSED:
                        raise ArchiveError("解压总大小超限（>10GB），疑似 zip 炸弹，已中止。")
                    dst.write(chunk)
        except ArchiveError:
            raise
        except OSError as e:
            skipped.append({"name": name, "reason": str(e)})
            if on_progress and (idx % 20 == 0 or idx == total - 1):
                on_progress(idx + 1, total)
            continue
        # 恢复 mtime，merge 策略需要
        if info.date_time:
            try:
                import time as _time
                mtime = _time.mktime(info.date_time + (0, 0, -1))
                os.utime(paths.long_path(target), (mtime, mtime))
            except Exception:
                pass
        if on_progress and (idx % 20 == 0 or idx == total - 1):
            on_progress(idx + 1, total)
    return written, skipped


def read_json(zf, arcname):
    try:
        data = zf.read(arcname)
    except KeyError:
        raise ArchiveError("导出包缺少必需文件: %s" % arcname)
    import json
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise ArchiveError("导出包内 %s 解析失败: %s" % (arcname, e))


def load_manifest(zf):
    import json
    try:
        raw = zf.read("manifest.json")
    except KeyError:
        raise ArchiveError("缺少 manifest.json，这不是 WorkBuddy 迁移导出文件。")
    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ArchiveError("manifest.json 解析失败: %s" % e)
    if m.get("format") != FORMAT_ID:
        raise ArchiveError("文件格式不符（format=%r），请使用本工具导出的 .zip 文件。"
                           % m.get("format"))
    v = m.get("version")
    if not isinstance(v, int) or v < 1 or v > FORMAT_VERSION:
        raise ArchiveError("导出文件版本不支持（version=%s，本工具支持 1~%d）。"
                           % (v, FORMAT_VERSION))
    return m
