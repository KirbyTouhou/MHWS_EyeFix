# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 KirbyTouhou
"""把本文件夹部署到 Blender 的插件目录（开发用）。

    blender --factory-startup -b --python tools/deploy.py
        部署到「正在运行的这版 Blender」的 addons 目录

    blender -b --python tools/deploy.py -- --target "<某个 addons 目录>"
        部署到指定目录（机器上装了多个 Blender 版本时用）

    ... -- --all
        部署到 %APPDATA% 下找到的每一个 Blender 版本的 addons 目录

采用「先清空再同步」——直接用插件安装器覆盖不会删掉旧版的残留文件
（改过名或删掉的文件会一直留在那里）。
refs/ 里的游戏原版文件会一并带过去，装完即可独立运行。
"""

import bpy
import os
import sys
import shutil

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.basename(SRC)
#: 不要同步进 Blender 插件目录的东西。
#: .git 尤其重要 —— 它是仓库元数据，插件运行不需要，躺在插件目录里既占地方
#: 又容易被别的打包脚本顺手收进去。
SKIP_DIRS = {"__pycache__", ".git", ".github", "dist", ".idea", ".vscode"}
SKIP_EXT = {".pyc", ".pyo"}
SKIP_FILES = {".gitignore", ".gitattributes"}


def parse_args(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    opts = {"target": None, "all": False}
    k = 0
    while k < len(args):
        if args[k] == "--all":
            opts["all"] = True
        elif args[k] == "--target" and k + 1 < len(args):
            opts["target"] = args[k + 1]
            k += 1
        k += 1
    return opts


def blender_addons_dirs():
    """%APPDATA% 下所有 Blender 版本的 scripts/addons 目录，版本高的在前。"""
    base = os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender")
    if not os.path.isdir(base):
        return []
    out = []
    for ver in sorted(os.listdir(base), reverse=True):
        p = os.path.join(base, ver, "scripts", "addons")
        if os.path.isdir(p):
            out.append(p)
    return out


def running_addons_dir():
    try:
        return bpy.utils.user_resource("SCRIPTS", path="addons")
    except Exception:
        return None


def rmtree_force(path):
    """删目录，遇到只读文件先把只读位去掉再删。

    Windows 上 git 的对象文件是只读的，直接 shutil.rmtree 会 PermissionError。
    （旧版本的 deploy 会把 .git 一起同步过去，然后下次部署就删不掉了 —— 踩过一次。）
    """
    import stat

    def on_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    # Python 3.12 起 onerror 改名成 onexc
    try:
        shutil.rmtree(path, onexc=lambda f, p, e: on_error(f, p, e))
    except TypeError:
        shutil.rmtree(path, onerror=on_error)


def sync(dst):
    target = os.path.join(dst, PKG)
    if os.path.isdir(target):
        rmtree_force(target)
    os.makedirs(target)
    n_files = n_bytes = 0
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, SRC)
        out_dir = target if rel == "." else os.path.join(target, rel)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        for f in files:
            if os.path.splitext(f)[1] in SKIP_EXT or f in SKIP_FILES:
                continue
            src_f = os.path.join(root, f)
            shutil.copy2(src_f, os.path.join(out_dir, f))
            n_files += 1
            n_bytes += os.path.getsize(src_f)
    return target, n_files, n_bytes


def main():
    opts = parse_args(sys.argv)
    targets = []
    if opts["target"]:
        targets = [opts["target"]]
    elif opts["all"]:
        targets = blender_addons_dirs()
    else:
        d = running_addons_dir()
        if d:
            targets = [d]

    if not targets:
        raise SystemExit("找不到目标 addons 目录，用 --target 手动指定")

    for dst in targets:
        if not os.path.isdir(dst):
            print("[deploy] 跳过（不存在）：%s" % dst)
            continue
        target, n, size = sync(dst)
        print("[deploy] %s  ->  %d 个文件，%.1f MB" % (target, n, size / 1048576))

    print("\n[deploy] 完成。重启 Blender 或在插件面板里重新启用即可生效。")


main()
