# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 KirbyTouhou
"""
MHWS Eye Fix —— 怪物猎人荒野二次元 mod 的眼球修复。

修三个问题：转向反向、眼角乱动、转动幅度过小或看不见。
用法：打开 mod 的 .blend -> N 面板 -> MHWS Eyefix -> 先「诊断」再「修复」。
原理与参数说明见 README。
"""

bl_info = {
    "name": "MHWS Eye Fix",
    "author": "KirbyTouhou",
    "version": (1, 0, 2),
    "blender": (4, 3, 0),
    "location": "View3D > Sidebar > MHWS Eyefix",
    "description": "修正怪物猎人荒野二次元 mod 的眼球转向反向 / 眼角乱动 / 转动幅度过小",
    "category": "Object",
}

import bpy
import os
import sys
import math
from mathutils import Vector

# ---------------------------------------------------------------- 常量

FACE_ROOT = "HeadAll_SCL"
SIDES = (("L", 1), ("R", -1))
EYE_JOINT = {"L": "L_EyeJ_LOD02", "R": "R_EyeJ_LOD02"}
EYE_MASTER = {"L": "L_Eye_Master", "R": "R_Eye_Master"}
BODY_EYE = {"L": "L_Eye", "R": "R_Eye"}
#: 判断「一个网格是不是眼球」时认这些骨。不同作者绑的不一样：
#: 大多数绑 L_EyeJ_LOD02（教程指明的眼球骨），也有直接绑 L_Eye_Master 的中枢骨的。
SRC_EYE_BONES = (tuple(EYE_JOINT.values()) + tuple(EYE_MASTER.values())
                 + tuple(BODY_EYE.values()))

REF_FBX = "MHWilds_Female.fbx"
STOCK_SKEL = "ch03_000_9000.fbxskel.7"

EPS = 1e-6


# ---------------------------------------------------------------- 找文件

def _search_roots():
    roots = []
    for kind, sub in (("SCRIPTS", "addons"), ("EXTENSIONS", "user_default")):
        try:
            p = bpy.utils.user_resource(kind, path=sub)
        except Exception:
            continue
        if p and os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def addon_dir():
    return os.path.dirname(os.path.abspath(__file__))


def local_refs_dir():
    """插件自带的参照物目录，查找时优先级最高。

    仓库里不含游戏原始文件（版权原因），由用户自己点按钮放进来。
    """
    return os.path.join(addon_dir(), "refs")


def find_reference_files(max_depth=8):
    """找游戏原版参照物，返回 (面部骨架 fbx, 身体骨架 fbxskel, 加载器目录)。

    第三项是 Modder_Batch_Tool 的 MHWilds 游戏目录，读 .fbxskel.7 需要它。
    查找顺序：插件自带 refs/ -> Blender 的 addons / extensions 目录。
    """
    local = local_refs_dir()
    l_ref = os.path.join(local, REF_FBX)
    l_skel = os.path.join(local, STOCK_SKEL)
    have_ref = l_ref if os.path.isfile(l_ref) else None
    have_skel = l_skel if os.path.isfile(l_skel) else None

    ref = skel = loader_dir = None
    for root in _search_roots():
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth > max_depth:
                dirnames[:] = []
                continue
            if loader_dir is None and "fbxskel_loader.py" in filenames:
                loader_dir = os.path.dirname(dirpath)
            if ref is None and REF_FBX in filenames:
                ref = os.path.join(dirpath, REF_FBX)
            if skel is None and STOCK_SKEL in filenames:
                skel = os.path.join(dirpath, STOCK_SKEL)
    # 优先用加载器同目录下的那份（配套、且是 MBT 一直在用的）
    if loader_dir:
        p = os.path.join(loader_dir, "model", STOCK_SKEL)
        if os.path.isfile(p):
            skel = p
        p = os.path.join(loader_dir, "model", REF_FBX)
        if os.path.isfile(p):
            ref = p
    # 插件自带的 refs/ 优先级最高
    if have_ref:
        ref = have_ref
    if have_skel:
        skel = have_skel
    return ref, skel, loader_dir


# ---------------------------------------------------------------- 读参照物

def read_face_reference(fbx_path):
    """导入游戏原版骨架，取回面部骨的「相对 Head 偏移」与父子关系，然后把导入物全部清掉。"""
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.fbx(filepath=fbx_path)
    except Exception as exc:
        raise RuntimeError("导入参照骨架失败：%r" % (exc,))
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == 'ARMATURE'), None)
    try:
        if arm is None:
            raise RuntimeError("参照 FBX 里没有骨架：%s" % fbx_path)
        b = arm.data.bones
        if "Head" not in b or FACE_ROOT not in b:
            raise RuntimeError("参照骨架里找不到 Head / %s" % FACE_ROOT)
        head = b["Head"].head_local.copy()
        root = b[FACE_ROOT]
        names = [root.name] + [c.name for c in root.children_recursive]
        offsets = {n: (b[n].head_local - head).copy() for n in names}
        parents = {n: (b[n].parent.name if b[n].parent else None) for n in names}
        return {"head": head, "names": names, "offsets": offsets, "parents": parents}
    finally:
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)


def read_stock_body_eye(skel_path, loader_dir):
    """从原版身体骨架取 L_Eye / R_Eye 的位置。取不到时返回空字典（不致命）。"""
    if not loader_dir:
        return {}
    if loader_dir not in sys.path:
        sys.path.insert(0, loader_dir)
    try:
        from fbxskel.fbxskel_loader import load_fbxskel
    except Exception:
        return {}
    ob = None
    try:
        ob = load_fbxskel(skel_path, collection=None, fix_rotation=True)
        return {n: ob.data.bones[n].head_local.copy()
                for n in BODY_EYE.values() if n in ob.data.bones}
    except Exception:
        return {}
    finally:
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)


# ---------------------------------------------------------------- 通用

def find_armature(obj=None):
    if obj is not None and obj.type == 'ARMATURE':
        return obj
    act = bpy.context.view_layer.objects.active
    if act is not None and act.type == 'ARMATURE':
        return act
    cands = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]

    # ★ 场景里有多个骨架时，**优先「真的有网格绑在它下面」的那个**。
    #
    #   踩过：原来是按「名字里有 MHWilds / ch03 就加权重、其次骨头多的优先」排。
    #   而导入参照骨架（MHWilds_Female.fbx）会留下一个名字就叫
    #   `MHWilds_Female Armature` 的空骨架 —— 它名字命中、骨头也不少（527 根），
    #   于是**永远压过用户自己的模型**。表现是：面板显示的骨架不对，诊断拿
    #   参照骨架跟它自己比，永远报「0 根不一致」，看着就像「读的还是上次那份数据」。
    #
    #   参照骨架是光秃秃的（没有网格绑上去）；模型骨架下面挂着蒙皮网格。
    #   这个判据比名字可靠。
    used = set()
    for m in bpy.context.scene.objects:
        if m.type != 'MESH':
            continue
        for md in m.modifiers:
            if md.type == 'ARMATURE' and md.object is not None:
                used.add(md.object.name)
    cands.sort(key=lambda o: (o.name in used, len(o.data.bones)), reverse=True)
    return cands[0]


def target_eye_bone(arm, side):
    for n in (EYE_JOINT[side], BODY_EYE[side]):
        if n in arm.data.bones:
            return n
    return None


def bound_eye_bones(obj, names):
    """该网格实际绑了哪些眼骨 -> {骨名: 覆盖顶点数}。用来在诊断里说清楚它绑的是什么。"""
    idx = {g.index: g.name for g in obj.vertex_groups if g.name in names}
    out = {}
    if not idx:
        return out
    for v in obj.data.vertices:
        for ge in v.groups:
            if ge.group in idx and ge.weight > EPS:
                out[idx[ge.group]] = out.get(idx[ge.group], 0) + 1
    return out


def find_eye_meshes(arm):
    """找出所有真正绑在眼骨上的网格（眼白绑 Head+眼皮，自然被排除）。"""
    src = {n for n in SRC_EYE_BONES if n in arm.data.bones}
    if not src:
        return []
    out = []
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        idx = {g.index for g in o.vertex_groups if g.name in src}
        if not idx:
            continue
        for v in o.data.vertices:
            if any(ge.group in idx and ge.weight > EPS for ge in v.groups):
                out.append(o)
                break
    return out


def side_centroid(obj, sign):
    """物体在 x*sign>0 一侧的顶点重心与顶点数。"""
    pts = [p for p in (obj.matrix_world @ v.co for v in obj.data.vertices) if p.x * sign > 0]
    if not pts:
        return None, 0
    return sum(pts, Vector()) / len(pts), len(pts)


def reference_mesh(meshes, sign):
    """该侧顶点最多的眼球网格 —— 也就是虹膜。

    杠杆按虹膜量，不按「虹膜+高光」的平均量：高光比虹膜靠前零点几毫米，
    加权平均会把枢轴拉近，幅度凭空少掉几个百分点。
    """
    best, best_n = None, 0
    for o in meshes:
        _, n = side_centroid(o, sign)
        if n > best_n:
            best, best_n = o, n
    return best


def measure_eye(arm, meshes):
    """返回 {side: {"centroid":..., "joint":..., "d":..., "lever":...}}"""
    out = {}
    for side, sign in SIDES:
        joint_name = target_eye_bone(arm, side)
        if joint_name is None:
            continue
        ref = reference_mesh(meshes, sign)
        if ref is None:
            continue
        centroid, n = side_centroid(ref, sign)
        if centroid is None or n == 0:
            continue
        joint = arm.data.bones[joint_name].head_local.copy()
        d = centroid - joint
        out[side] = {
            "centroid": centroid,
            "joint": joint,
            "joint_name": joint_name,
            "d": d,
            "lever": math.hypot(d.x, d.y),
        }
    return out


def visible_mm(weight, dy, deg):
    return weight * math.radians(deg) * abs(dy) * 1000.0


# ---------------------------------------------------------------- 诊断

class MHWS_OT_EyeFixDiagnose(bpy.types.Operator):
    bl_idname = "mhws.eye_fix_diagnose"
    bl_label = "诊断"
    bl_description = "只读检查：面部骨错位、假骨、眼球枢轴方向与幅度，不做任何修改"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.mhws_eyefix
        arm = find_armature(context.active_object)
        if arm is None:
            self.report({'ERROR'}, "场景里找不到骨架")
            return {'CANCELLED'}

        lines = []
        lines.append("骨架：%s（%d 根）" % (arm.name, len(arm.data.bones)))

        # --- 假骨 ---
        fakes = [b.name for b in arm.data.bones
                 if b.name.endswith("_Fake") and b.parent is not None]
        lines.append("假骨（*_Fake）：%s" % (", ".join(fakes) if fakes else "无"))

        # --- 面部骨 ---
        ref_path = props.ref_fbx or find_reference_files()[0]
        ref = None
        if ref_path and os.path.isfile(ref_path):
            try:
                ref = read_face_reference(ref_path)
            except Exception as exc:
                lines.append("参照骨架读取失败：%s" % exc)
        else:
            lines.append("找不到 %s，跳过面部骨比对（可在面板里手动指定）" % REF_FBX)

        if ref:
            head = arm.data.bones["Head"].head_local.copy()
            bad = []
            for n in ref["names"]:
                b = arm.data.bones.get(n)
                if b is None:
                    bad.append((n, float('inf')))
                    continue
                off = (b.head_local - head) - ref["offsets"][n]
                if off.length > 5e-4:
                    bad.append((n, off.length))
            bad.sort(key=lambda t: -t[1])
            lines.append("面部骨 vs 游戏原版：%d / %d 根不一致"
                         % (len(bad), len(ref["names"])))
            for n, dist in bad[:8]:
                lines.append("    %-24s %s" % (n, "缺失" if dist == float('inf') else "偏 %.5f" % dist))
            if len(bad) > 8:
                lines.append("    ...（共 %d 根）" % len(bad))

        # --- 眼球 ---
        meshes = find_eye_meshes(arm)
        if meshes:
            lines.append("绑在眼骨上的网格 %d 个：" % len(meshes))
            src = set(SRC_EYE_BONES)
            for o in meshes:
                b = bound_eye_bones(o, src)
                lines.append("    %-34s %s" % (
                    o.name,
                    ", ".join("%s(%d顶点)" % (k, v) for k, v in sorted(b.items())) or "无"))
        else:
            lines.append("绑在眼骨上的网格：无")
            lines.append("    认过的骨：%s" % ", ".join(SRC_EYE_BONES))
            lines.append("    如果你确定这个 mod 有眼球，说明它绑在别的骨上，"
                         "或者虹膜根本没绑眼骨（整只眼睛钉在头上）")
        eyes = measure_eye(arm, meshes)
        if not eyes:
            lines.append("量不到眼球几何，无法判断枢轴")
        for side, _ in SIDES:
            e = eyes.get(side)
            if not e:
                lines.append("%s 侧：测不到" % side)
                continue
            dy = e["d"].y
            verdict = "✓ 虹膜在枢轴前方（方向应该是对的）" if dy < 0 else "✗ 虹膜在枢轴后方 —— 转向会反向"
            lines.append("%s 侧  眼骨=%s  水平杠杆=%.5f  可见占比=%.0f%%"
                         % (side, e["joint_name"], e["lever"],
                            abs(dy) / e["lever"] * 100 if e["lever"] > EPS else 0))
            lines.append("    d = [%.5f, %.5f, %.5f]   %s"
                         % (e["d"].x, e["d"].y, e["d"].z, verdict))
            if dy < 0:
                lines.append("    当前权重 %.4f 下的可见横移：10°→%.2fmm  20°→%.2fmm  30°→%.2fmm"
                             % (props.weight_eye,
                                visible_mm(props.weight_eye, dy, 10),
                                visible_mm(props.weight_eye, dy, 20),
                                visible_mm(props.weight_eye, dy, 30)))

        text = "\n".join(lines)
        props.last_report = text
        print("\n======== MHWS Eye Fix 诊断 ========")
        print(text)
        print("===================================\n")
        self.report({'INFO'}, "诊断完成，详情见系统控制台（Window > Toggle System Console）")
        return {'FINISHED'}


# ---------------------------------------------------------------- 修复

class MHWS_OT_EyeFixApply(bpy.types.Operator):
    bl_idname = "mhws.eye_fix_apply"
    bl_label = "修复"
    bl_description = "修正面部骨错位与假骨、翻转眼球枢轴方向、重绑眼球权重"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mhws_eyefix
        arm = find_armature(context.active_object)
        if arm is None:
            self.report({'ERROR'}, "场景里找不到骨架")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        log = []

        # --- 参照物 ---
        auto_ref, auto_skel, loader_dir = find_reference_files()
        ref_path = props.ref_fbx or auto_ref
        skel_path = props.stock_skel or auto_skel
        ref = None
        if props.fix_face_bones and ref_path and os.path.isfile(ref_path):
            try:
                ref = read_face_reference(ref_path)
            except Exception as exc:
                self.report({'WARNING'}, "参照骨架读取失败，跳过面部骨修正：%s" % exc)
        elif props.fix_face_bones:
            self.report({'WARNING'}, "找不到 %s，跳过面部骨修正" % REF_FBX)

        stock_eye = {}
        if props.fix_body_eye and skel_path and os.path.isfile(skel_path):
            stock_eye = read_stock_body_eye(skel_path, loader_dir)

        # --- 先量（必须在改骨之前）---
        meshes = find_eye_meshes(arm)
        if not meshes:
            self.report({'ERROR'}, "找不到绑在眼骨上的网格，无法定位眼球")
            return {'CANCELLED'}
        eyes = measure_eye(arm, meshes)
        if not eyes:
            self.report({'ERROR'}, "量不到眼球几何")
            return {'CANCELLED'}

        # 每个眼的目标枢轴位置（只依赖几何，不依赖骨骼当前位置）
        targets = {}
        for side, e in eyes.items():
            d = e["d"]
            lever = e["lever"] * props.lever_scale
            if props.reaim_lever:
                want = Vector((0.0, -lever, d.z))       # 瞄准虹膜正后方 -> 长度全用于可见位移
            else:
                want = Vector((d.x, -abs(d.y), d.z))    # 只翻符号，方向不动
            targets[side] = e["centroid"] - want
            log.append("%s 侧：d=[%.5f, %.5f, %.5f] 杠杆 %.5f -> 目标杆 %.5f  %s"
                       % (side, d.x, d.y, d.z, e["lever"], lever,
                          "（已瞄准正后方）" if props.reaim_lever else "（只翻符号）"))

        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones

        # --- 1. 删假骨 ---
        removed = []
        for f in [b for b in eb if b.name.endswith("_Fake") and b.parent is not None]:
            name, parent = f.name, f.parent
            for c in list(f.children):
                c.parent = parent
            eb.remove(f)
            removed.append(name)
        if removed:
            log.append("删除假骨 %d 根：%s" % (len(removed), ", ".join(removed)))

        # --- 2. 面部骨归位 ---
        if ref is not None:
            names, offsets, parents = ref["names"], ref["offsets"], ref["parents"]
            head_now = eb["Head"].head.copy()

            def depth(n):
                d, p = 0, parents.get(n)
                while p:
                    d += 1
                    p = parents.get(p)
                return d

            created = []
            for n in names:
                if n not in eb:
                    eb.new(n)
                    created.append(n)
            for n in sorted(names, key=depth):
                if n not in eb:
                    continue
                p = parents.get(n)
                if p and p in eb and eb[n].parent is not eb[p]:
                    eb[n].parent = eb[p]
                    eb[n].use_connect = False
            moved = 0
            # 必须按层级从浅到深处理：父骨归位时会带走整棵子树，
            # 若先处理子骨再被父骨带一次，子骨就会偏两次
            for n in sorted(names, key=depth):
                if n not in eb:
                    continue
                b = eb[n]
                want = head_now + offsets[n]
                delta = want - b.head
                if delta.length > 1e-7:
                    moved += 1
                    b.head = want
                    b.tail = b.tail + delta
                    for c in b.children_recursive:
                        c.head += delta
                        c.tail += delta
            log.append("面部骨归位：新建 %d 根、移动 %d / %d 根" % (len(created), moved, len(names)))

        # --- 3. 翻正眼球枢轴 ---
        for side, target in targets.items():
            joint = EYE_JOINT[side]
            master = EYE_MASTER[side]
            if joint not in eb:
                continue
            delta = target - eb[joint].head
            # 只动这两根，保持两者相对关系；眼皮链一律不碰
            for n in (master, joint):
                if n in eb:
                    eb[n].head += delta
                    eb[n].tail += delta
            log.append("%s：%s + %s 平移 [%.5f, %.5f, %.5f]"
                       % (side, master, joint, delta.x, delta.y, delta.z))

        # --- 4. L_Eye / R_Eye 取原版位置 ---
        if stock_eye:
            H3 = eb["Head"].matrix.to_3x3().normalized()
            for n, h in stock_eye.items():
                if n not in eb:
                    continue
                b = eb[n]
                L = b.length
                b.head = h.copy()
                b.tail = h + H3.col[1].normalized() * L
                b.align_roll(H3.col[2].normalized())
            log.append("L_Eye / R_Eye 已设为原版位置（朝向对齐 Head）")
        elif props.fix_body_eye:
            log.append("取不到原版身体骨架，跳过 L_Eye / R_Eye")

        bpy.ops.object.mode_set(mode='OBJECT')

        # --- 5. 重绑眼球权重 ---
        w_eye = props.weight_eye
        w_head = 1.0 - w_eye
        for o in meshes:
            bones = {s: target_eye_bone(arm, s) for s, _ in SIDES}
            for g in list(o.vertex_groups):
                o.vertex_groups.remove(g)
            groups = {}
            mw = o.matrix_world
            for v in o.data.vertices:
                x = (mw @ v.co).x
                side = "L" if x > 0 else "R"
                name = bones.get(side)
                if name is None:
                    continue
                for n, w in ((name, w_eye), ("Head", w_head)):
                    if w <= EPS:
                        continue
                    if n not in groups:
                        groups[n] = o.vertex_groups.new(name=n)
                    groups[n].add([v.index], w, 'REPLACE')
            o.data.update()
        log.append("重绑 %d 个网格：眼骨 %.4f + Head %.4f（按 X 分侧）"
                   % (len(meshes), w_eye, w_head))

        # --- 复核 ---
        bpy.context.view_layer.update()
        eyes2 = measure_eye(arm, meshes)
        for side, _ in SIDES:
            e = eyes2.get(side)
            if not e:
                continue
            dy = e["d"].y
            log.append("%s 侧复核：d.y=%+.5f  水平杠杆=%.5f  %s"
                       % (side, dy, e["lever"], "✓" if dy < 0 else "✗ 仍反向"))
            log.append("    可见横移：10°→%.2fmm  20°→%.2fmm  30°→%.2fmm"
                       % (visible_mm(w_eye, dy, 10), visible_mm(w_eye, dy, 20),
                          visible_mm(w_eye, dy, 30)))

        text = "\n".join(log)
        props.last_report = text
        print("\n======== MHWS Eye Fix 修复 ========")
        print(text)
        print("===================================\n")
        self.report({'INFO'}, "修复完成，详情见系统控制台")
        return {'FINISHED'}


class MHWS_OT_EyeFixStashRefs(bpy.types.Operator):
    bl_idname = "mhws.eye_fix_stash_refs"
    bl_label = "把参照物复制到插件目录"
    bl_description = ("把游戏原版参照物复制到插件目录，之后换机器免配置。\n"
                      "注意：这两个文件是卡普空的游戏资产，不要随插件公开分发")

    bl_options = {'REGISTER'}

    def execute(self, context):
        import shutil
        ref, skel, _ = find_reference_files()
        dst = local_refs_dir()
        try:
            os.makedirs(dst, exist_ok=True)
        except Exception as exc:
            self.report({'ERROR'}, "建不了目录 %s：%r" % (dst, exc))
            return {'CANCELLED'}
        got, skipped = [], []
        for src, name in ((ref, REF_FBX), (skel, STOCK_SKEL)):
            if not src or not os.path.isfile(src):
                continue
            if os.path.abspath(os.path.dirname(src)) == os.path.abspath(dst):
                skipped.append(name)
                continue
            try:
                shutil.copy2(src, os.path.join(dst, name))
                got.append(name)
            except Exception as exc:
                self.report({'WARNING'}, "复制 %s 失败：%r" % (name, exc))
        if not got:
            if skipped:
                self.report({'INFO'}, "参照物已经在插件目录里了，无需复制")
                return {'FINISHED'}
            self.report({'WARNING'},
                        "没找到可复制的参照物。请先装 Modder_Batch_Tool 或 "
                        "Modding-Toolkit，或在面板底部手动指定两个文件的路径")
            return {'CANCELLED'}
        self.report({'INFO'}, "已复制到 refs/：%s" % ", ".join(got))
        return {'FINISHED'}


class MHWS_OT_EyeFixClearReport(bpy.types.Operator):
    bl_idname = "mhws.eye_fix_clear_report"
    bl_label = "清空报告"
    bl_options = {'REGISTER'}

    def execute(self, context):
        context.scene.mhws_eyefix.last_report = ""
        return {'FINISHED'}


# ---------------------------------------------------------------- 属性

class MHWS_EyeFixProps(bpy.types.PropertyGroup):
    weight_eye: bpy.props.FloatProperty(
        name="眼球权重",
        description="眼球绑在眼骨上的权重，其余给 Head。越大转动越明显",
        default=0.5, min=0.0, max=1.0, precision=3, subtype='FACTOR')

    reaim_lever: bpy.props.BoolProperty(
        name="杠杆瞄准正后方",
        description="保持杠杆长度不变，只把它转到虹膜正后方，"
                    "水平分量全部变成看得见的左右位移。关掉则只翻转符号",
        default=True)

    lever_scale: bpy.props.FloatProperty(
        name="杠杆倍率",
        description="在原始杠杆长度上乘一个系数。1.0 = 与原模型一致；调大更明显但易穿模",
        default=1.0, min=0.1, max=5.0, precision=2)

    fix_face_bones: bpy.props.BoolProperty(
        name="修正面部骨与假骨",
        description="删除 *_Fake 假骨，把整棵面部骨架校正回游戏原版位置（修「眼角乱动」）",
        default=True)

    fix_body_eye: bpy.props.BoolProperty(
        name="L_Eye / R_Eye 取原版位置",
        description="让导出的 fbxskel 里这两根眼骨与原版一致",
        default=True)

    ref_fbx: bpy.props.StringProperty(
        name="参照骨架",
        description="MHWilds_Female.fbx 路径，留空自动搜索",
        default="", subtype='FILE_PATH')

    stock_skel: bpy.props.StringProperty(
        name="原版身体骨架",
        description="ch03_000_9000.fbxskel.7 路径，留空自动搜索",
        default="", subtype='FILE_PATH')

    last_report: bpy.props.StringProperty(default="", options={'HIDDEN'})


# ---------------------------------------------------------------- UI

class MHWS_PT_EyeFix(bpy.types.Panel):
    bl_label = "眼球修复 (Eye Fix)"
    bl_idname = "MHWS_PT_eye_fix"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MHWS Eyefix"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mhws_eyefix
        arm = find_armature(context.active_object)

        if arm is None:
            layout.label(text="场景里没有骨架", icon='ERROR')
            return
        n_arms = sum(1 for o in context.scene.objects if o.type == 'ARMATURE')
        box = layout.box()
        box.label(text="骨架：%s" % arm.name, icon='ARMATURE_DATA')
        box.label(text="骨骼数：%d" % len(arm.data.bones))
        # 显示当前文件名 —— 排查「换文件后数据没跟着变」时，这一行是分水岭：
        # 它显示的不是你刚打开的文件，就说明读的是别处的东西。
        box.label(text="文件：%s"
                      % (os.path.basename(bpy.data.filepath) or "(未保存)"))
        if n_arms > 1:
            # 说清楚「用的是哪一个、怎么换」—— 场景里有多个骨架时，
            # 选错的那个会让诊断看着像「读的还是上次的数据」。
            box.label(text="场景里有 %d 个骨架，正在用上面这个" % n_arms, icon='INFO')
            box.label(text="选中想用的那个骨架，这里就会切过去", icon='INFO')

        col = layout.column(align=True)
        col.label(text="参数")
        col.prop(props, "weight_eye", slider=True)
        col.prop(props, "reaim_lever")
        if props.reaim_lever:
            col.prop(props, "lever_scale")
        col.prop(props, "fix_face_bones")
        col.prop(props, "fix_body_eye")

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("mhws.eye_fix_diagnose", icon='VIEWZOOM')
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("mhws.eye_fix_apply", icon='CHECKMARK')

        box = layout.box()
        box.label(text="参照物", icon='FILE_FOLDER')
        local = local_refs_dir()
        have = [n for n in (REF_FBX, STOCK_SKEL) if os.path.isfile(os.path.join(local, n))]
        if len(have) == 2:
            box.label(text="插件目录已自带 ✓", icon='CHECKMARK')
        else:
            box.label(text="插件目录自带 %d / 2" % len(have), icon='INFO')
        box.operator("mhws.eye_fix_stash_refs", icon='DUPLICATE')
        col = box.column(align=True)
        col.label(text="手动指定（留空自动搜索）")
        col.prop(props, "ref_fbx", text="")
        col.prop(props, "stock_skel", text="")

        if props.last_report:
            box = layout.box()
            row = box.row()
            row.label(text="上次报告", icon='TEXT')
            row.operator("mhws.eye_fix_clear_report", text="", icon='X')
            for line in props.last_report.split("\n"):
                box.label(text=line[:110])


# ---------------------------------------------------------------- 注册

classes = (
    MHWS_EyeFixProps,
    MHWS_OT_EyeFixDiagnose,
    MHWS_OT_EyeFixApply,
    MHWS_OT_EyeFixStashRefs,
    MHWS_OT_EyeFixClearReport,
    MHWS_PT_EyeFix,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mhws_eyefix = bpy.props.PointerProperty(type=MHWS_EyeFixProps)


def unregister():
    del bpy.types.Scene.mhws_eyefix
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
