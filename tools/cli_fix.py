# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 KirbyTouhou
"""命令行版：等价于在 N 面板上点一次「诊断」+「修复」。

    blender --factory-startup -b --python tools/cli_fix.py -- <输入.blend> [输出.blend]
            [--weight 0.5] [--lever-scale 1.0] [--no-reaim] [--no-face] [--dry-run]

    输出省略时写成 <输入名>_fixed.blend。
    加 --dry-run 只诊断、不写文件。

批处理或回归对比时用；日常直接用面板更直观。
"""

import bpy
import sys
import os
import importlib

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_PKG_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)


def parse_args(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    pos, opts = [], {}
    k = 0
    while k < len(args):
        a = args[k]
        if a.startswith("--"):
            key = a[2:]
            if key in ("dry-run", "no-reaim", "no-face", "no-body-eye"):
                opts[key] = True
            elif k + 1 < len(args):
                opts[key] = args[k + 1]
                k += 1
            else:
                raise SystemExit("参数 %s 缺值" % a)
        else:
            pos.append(a)
        k += 1
    if not pos:
        raise SystemExit("用法：-- <输入.blend> [输出.blend] [--weight 0.5] [--dry-run]")
    src = pos[0]
    if len(pos) > 1:
        dst = pos[1]
    else:
        stem, ext = os.path.splitext(src)
        dst = stem + "_fixed" + ext
    return src, dst, opts


def main():
    src, dst, opts = parse_args(sys.argv)
    if not os.path.isfile(src):
        raise SystemExit("找不到输入文件：%s" % src)

    pkg = importlib.import_module(os.path.basename(_PKG_DIR))
    pkg.register()

    ref, skel, _ = pkg.find_reference_files()
    print("[cli] 参照骨架 : %s" % (ref or "【没找到】"))
    print("[cli] 原版骨架 : %s" % (skel or "【没找到】"))

    bpy.ops.wm.open_mainfile(filepath=src)
    arm = pkg.find_armature()
    if arm is None:
        raise SystemExit("场景里找不到骨架")
    bpy.context.view_layer.objects.active = arm

    props = bpy.context.scene.mhws_eyefix
    if "weight" in opts:
        props.weight_eye = float(opts["weight"])
    if "lever-scale" in opts:
        props.lever_scale = float(opts["lever-scale"])
    if opts.get("no-reaim"):
        props.reaim_lever = False
    if opts.get("no-face"):
        props.fix_face_bones = False
    if opts.get("no-body-eye"):
        props.fix_body_eye = False
    print("[cli] 参数：权重=%.3f 瞄准=%s 倍率=%.2f 修面骨=%s 修L_Eye=%s" % (
        props.weight_eye, props.reaim_lever, props.lever_scale,
        props.fix_face_bones, props.fix_body_eye))

    print("\n---------- 诊断 ----------")
    bpy.ops.mhws.eye_fix_diagnose()

    if opts.get("dry-run"):
        print("\n[cli] --dry-run，未修改任何东西")
        return

    print("\n---------- 修复 ----------")
    bpy.ops.mhws.eye_fix_apply()
    bpy.ops.wm.save_as_mainfile(filepath=dst)
    print("\n[cli] 已保存 %s" % dst)


main()
