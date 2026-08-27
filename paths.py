# -*- coding: utf-8 -*-
"""路径发现、projects 转义/反转义、跨机路径重写。

支持两个环境变量用于沙箱测试（真机运行时不设置即可）：
  WBMIGRATE_HOME  -> 重定向 ~/.workbuddy 数据目录
  WBMIGRATE_ROOT  -> 重定向 C:\\Users\\<user>\\WorkBuddy 空间根目录
"""
import os
import re
import sys

WORKBUDDY_DIR_NAME = "WorkBuddy"


def get_workbuddy_home():
    """返回 .workbuddy 数据目录（数据库、tasks、projects 所在地）。"""
    env = os.environ.get("WBMIGRATE_HOME")
    if env:
        return os.path.normpath(env)
    return os.path.normpath(os.path.join(os.path.expanduser("~"), ".workbuddy"))


def get_workbuddy_root():
    """返回空间根目录（各空间文件夹的父目录，默认 <userprofile>/WorkBuddy）。"""
    env = os.environ.get("WBMIGRATE_ROOT")
    if env:
        return os.path.normpath(env)
    home = os.path.expanduser("~")
    return os.path.normpath(os.path.join(home, WORKBUDDY_DIR_NAME))


def get_db_path():
    return os.path.join(get_workbuddy_home(), "workbuddy.db")


def get_tasks_dir():
    return os.path.join(get_workbuddy_home(), "tasks")


def get_projects_dir():
    return os.path.join(get_workbuddy_home(), "projects")


def get_backup_base():
    return os.path.join(get_workbuddy_home(), "migrate-backup")


def is_windows_path(p):
    """按路径字符串形态判断是否 Windows 风格（盘符或反斜杠）。"""
    p = p or ""
    if len(p) >= 2 and p[1] == ":":   # C:\...
        return True
    return "\\" in p


def _platform_name(sys_platform):
    """sys.platform -> 人类可读系统名。"""
    if sys_platform == "win32":
        return "Windows"
    if sys_platform == "darwin":
        return "macOS"
    return "Linux"


def long_path(p):
    """为超长路径加 \\\\?\\ 前缀（仅 Windows 绝对路径）。"""
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):  # UNC
            return "\\\\?\\UNC" + p[1:]
        return "\\\\?\\" + p
    return p


def escape_project_name(cwd_path):
    """把 cwd 绝对路径转成 projects/ 下的文件夹名（对齐官方 PathUtils.compressPath）。

    官方实现（WorkBuddy 客户端 codebuddy.js / edge-sync server index.cjs:40461
    反编译核对，2026-08-27）：
      path.replace(/[/\\:]/g, "-")   # / \\ : 全部替换为 '-'
          .replace(/^-+/, "")        # 去前导 '-'
          .replace(/-+$/, "")        # 去尾随 '-'
          .replace(/-+/g, "-")       # 连续 '-' 折叠为一个

    真机/源码双重验证：
      - Windows: cwd='c:\\Users\\tom\\WorkBuddy\\xxx'
                 -> 'c-Users-tom-WorkBuddy-xxx'
        （无独立"盘符小写化"步骤；本机磁盘上盘符小写是因为会话进程记录的
          cwd 本身就是小写盘符，compressPath 只是原样压缩）
      - macOS:   '/Users/zhanghao/WorkBuddy/2026-08-16-00-24-19'
                 -> 'Users-zhanghao-WorkBuddy-2026-08-16-00-24-19'
        （前导 '/' 变 '-' 后被去前导规则剥掉，故 POSIX 无前导 '-'；
          样本来自 edge-sync 源码内注释的磁盘验证记录）

    注意：本函数必须与官方实现逐字节一致——目标机的 WorkBuddy 将来就是用
    compressPath(重写后的 cwd) 来定位导入的 transcript 的。
    """
    p = (cwd_path or "").strip()
    p = p.replace("/", "-").replace("\\", "-").replace(":", "-")
    return re.sub("-+", "-", p.lstrip("-").rstrip("-"))


def norm_key(p):
    """路径归一化匹配键：统一正斜杠、去尾部斜杠、小写（跨系统可比）。"""
    p = (p or "").strip().replace("\\", "/")
    while p.endswith("/"):
        p = p[:-1]
    return p.lower()


def path_startswith(path, root):
    """判断 path 是否位于 root 之下（大小写不敏感，分隔符无关）。"""
    nk = norm_key(path)
    nr = norm_key(root)
    return nk == nr or nk.startswith(nr + "/")


def rewrite_path(src_path, src_root, dst_root):
    """把源机器的路径前缀重写为目标机器前缀（支持跨系统）。

    仅当 src_path 位于 src_root 之下时重写；结果使用 dst_root 所在系统的
    分隔符风格（Windows -> '\\'，POSIX -> '/'）。
    """
    if not src_path or not src_root:
        return src_path
    sp = src_path.replace("\\", "/").rstrip("/")
    sr = src_root.replace("\\", "/").rstrip("/")
    lsp, lsr = sp.lower(), sr.lower()
    if lsp == lsr:
        return dst_root
    if lsp.startswith(lsr + "/"):
        rel = sp[len(sr):].lstrip("/")   # 保留原始大小写
        rel = rel.strip("/")
        if not rel:
            return dst_root
        if is_windows_path(dst_root):
            return dst_root.rstrip("\\/") + "\\" + rel.replace("/", "\\")
        return dst_root.rstrip("/") + "/" + rel.replace("\\", "/")
    return src_path


def self_check():
    """内置自检：用真实 projects 文件夹名验证转义规则。

    优先以 sessions 表里的 cwd 为基准做正向比对（这些文件夹就是 WorkBuddy
    按 compressPath(cwd) 创建的，属于权威样本）；DB 不可用时退化为
    反转义->再转义的往返一致性检查。
    """
    projects_dir = get_projects_dir()
    if not os.path.isdir(projects_dir):
        print("[selfcheck] projects 目录不存在，跳过：%s" % projects_dir)
        return True
    # 权威样本：sessions 表全部 cwd 的官方压缩名
    known = set()
    try:
        import db as _db
        for s in _db.list_sessions():
            c = s.get("cwd")
            if c:
                known.add(escape_project_name(c))
    except Exception:
        pass
    known_lower = {k.lower() for k in known}
    ok = True
    checked = 0
    for name in os.listdir(projects_dir):
        folder = os.path.join(projects_dir, name)
        if not os.path.isdir(folder):
            continue
        if not any(f.endswith(".jsonl") for f in os.listdir(folder)):
            continue
        checked += 1
        if known:
            good = name in known or name.lower() in known_lower
        else:
            expected = escape_project_name(_unescape_project_name(name))
            good = expected == name or expected.lower() == name.lower()
        if not good:
            print("[selfcheck] FAIL: %r 不符合 compressPath 规则" % name)
            ok = False
    print("[selfcheck] projects 转义规则检查: %d 个样本, %s"
          % (checked, "通过" if ok else "失败"))
    return ok


def _unescape_project_name(name, assume_windows=None):
    """把转义名还原回绝对路径（仅用于自检与预览显示）。

    反转射不唯一（连续 '-' 已折叠），且 Windows/POSIX 形态可能同构，
    因此按平台假设还原：assume_windows 缺省时取当前运行平台。
    """
    if assume_windows is None:
        assume_windows = os.name == "nt"
    if assume_windows:
        if len(name) > 1:
            return name[0].upper() + ":\\" + name[1:].replace("-", "\\")
        return name
    return "/" + name.replace("-", "/")


if __name__ == "__main__":
    print("workbuddy_home =", get_workbuddy_home())
    print("workbuddy_root =", get_workbuddy_root())
    print("db_path       =", get_db_path())
    sys.exit(0 if self_check() else 1)
