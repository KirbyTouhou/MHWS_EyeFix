# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 KirbyTouhou
"""打发布包（开发用）。

    python tools/package.py
        输出 dist/MHWS_EyeFix.zip

用普通 Python 跑即可，不需要 Blender。

打包规则：
  * 排除 __pycache__ / *.pyc
  * 排除 refs/ 里的内容 —— 那是卡普空的游戏资产，不能随包分发
    （只保留 refs/README.txt 作为说明）
  * dist/ 已在 .gitignore 里，不会被提交

这个 zip 可以直接作为 GitHub Release 的附件，别人下载后用
Blender 的「安装」指向它就能装。
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.basename(ROOT)
OUT_DIR = os.path.join(os.path.dirname(ROOT), "dist")
OUT = os.path.join(OUT_DIR, PKG + ".zip")

SKIP_DIRS = {"__pycache__", "dist", ".git"}
SKIP_EXT = {".pyc", ".pyo"}
#: refs/ 下只放行这一个说明文件
REFS_ALLOW = {"README.txt"}


def keep(rel):
    parts = rel.replace("\\", "/").split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return False
    if os.path.splitext(parts[-1])[1] in SKIP_EXT:
        return False
    if len(parts) >= 3 and parts[1] == "refs" and parts[-1] not in REFS_ALLOW:
        return False
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    n = total = 0
    skipped = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, os.path.dirname(ROOT))
                if not keep(rel):
                    if "refs" in rel.replace("\\", "/").split("/"):
                        skipped.append(rel)
                    continue
                z.write(p, rel.replace("\\", "/"))
                n += 1
                total += os.path.getsize(p)
    print("打包 %d 个文件，源码 %.1f KB" % (n, total / 1024))
    if skipped:
        print("已排除 refs/ 下的游戏资产 %d 个：" % len(skipped))
        for s in skipped:
            print("    " + s)
    print("-> %s  (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


main()
