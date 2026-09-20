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
SKIP_DIRS = {"__pycache__"}
SKIP_EXT = {".pyc"}


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


def sync(dst):
    target = os.path.join(dst, PKG)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    n_files = n_bytes = 0
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, SRC)
        out_dir = target if rel == "." else os.path.join(target, rel)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        for f in files:
            if os.path.splitext(f)[1] in SKIP_EXT:
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
