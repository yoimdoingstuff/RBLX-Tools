"""Roblox animations <-> Blender rig actions.

A KeyframeSequence (what Roblox's Animation Editor, Moon Animator 2 and
Eclipse Animator export) has Keyframes at times; each holds a tree of Poses
named after the part a joint moves, whose CFrame is the Motor6D Transform.

Our rig bones rest at the joint frame (Part0.CFrame * C0) and are named after
Part1, so a Pose maps straight onto the bone's pose:
    bone pose matrix (Blender) = AXIS @ Transform @ AXIS^-1  (positions x stud scale)"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import coords
from .rbx import CFrame
from .rbx.writer import Item, write_file

# Enum.PoseEasingStyle / Enum.PoseEasingDirection
POSE_STYLES = {0: "LINEAR", 1: "CONSTANT", 2: "ELASTIC", 3: "CUBIC", 4: "BOUNCE", 5: "CUBIC"}
POSE_DIRS = {0: "EASE_IN", 1: "EASE_OUT", 2: "EASE_IN_OUT"}
# Roblox's original Elastic/Bounce/Cubic pose easings have In and Out reversed
# (CubicV2 was added to fix it), so they're swapped when reading/writing.
_SWAPPED_STYLES = {2, 3, 4}
_FLIP = {"EASE_IN": "EASE_OUT", "EASE_OUT": "EASE_IN", "EASE_IN_OUT": "EASE_IN_OUT"}
# Blender's own Bezier curves aren't one of Roblox's easings: they're baked per frame
_STYLE_IDS = {"LINEAR": 0, "CONSTANT": 1, "ELASTIC": 2, "BOUNCE": 4, "CUBIC": 5}
_DIR_IDS = {"EASE_IN": 0, "EASE_OUT": 1, "EASE_IN_OUT": 2, "AUTO": 2}


def transform_to_basis(cf, scale):
    """Roblox Motor6D Transform (CFrame) -> Blender bone pose basis matrix."""
    m = coords.rot_to_bl(cf.rot).to_4x4()
    m.translation = coords.vec_to_bl(cf.pos, scale)
    return m


def basis_to_transform(m, scale):
    """Blender bone pose basis matrix -> (position, row-major 3x3) for a CFrame."""
    loc, rot, _s = m.decompose()
    r = coords.rot_to_rbx(rot.to_matrix())
    return coords.vec_to_rbx(loc, scale), [r[i][j] for i in range(3) for j in range(3)]


def find_sequences(doc):
    """KeyframeSequences and CurveAnimations (both can be applied with apply_sequence)."""
    return [i for i in doc.all_instances() if i.class_name in ("KeyframeSequence", "CurveAnimation")]


# ---------------------------------------------------------------------------
# CurveAnimation (Roblox's curve-based animations: a Folder per joint, named
# after the part like a Pose, holding a "Position" Vector3Curve and a
# "Rotation" EulerRotationCurve or RotationCurve; each axis a FloatCurve)

TICKS_PER_SECOND = 2400.0
# Enum.KeyInterpolationMode
_CONSTANT, _LINEAR, _CUBIC = 0, 1, 2
# Enum.RotationOrder
_ROTATION_ORDERS = {0: "XYZ", 1: "XZY", 2: "YZX", 3: "YXZ", 4: "ZXY", 5: "ZYX"}


class CurveError(ValueError):
    pass


def _blob(v):
    if isinstance(v, str):  # the binary reader keeps blobs that happen to be UTF-8 as text
        return v.encode("utf-8", "surrogateescape")
    return bytes(v or b"")


def _times(data, off, count):
    import struct
    if len(data) < off + 8:
        raise CurveError("curve data truncated")
    _ver, n = struct.unpack_from("<II", data, off)
    if n != count or len(data) < off + 8 + 4 * n:
        raise CurveError("curve key count mismatch")
    return [t / TICKS_PER_SECOND for t in struct.unpack_from("<%di" % n, data, off + 8)]


def decode_float_curve(blob):
    """FloatCurve.ValuesAndTimes -> [(time, value, interpolation, left, right, tangent mask)]."""
    import struct
    data = _blob(blob)
    if len(data) < 16:
        return []
    _ver, n = struct.unpack_from("<II", data, 0)
    off = 8
    vals = []
    for _ in range(n):
        if len(data) < off + 14:
            raise CurveError("FloatCurve truncated")
        interp, mask = data[off], data[off + 1]
        v, lt, rt = struct.unpack_from("<fff", data, off + 2)
        vals.append((interp, mask, v, lt, rt))
        off += 14
    times = _times(data, off, n)
    return [(t, v, i, lt, rt, m) for t, (i, m, v, lt, rt) in zip(times, vals)]


def decode_rotation_curve(blob):
    """RotationCurve.ValuesAndTimes -> [(time, Quaternion (Roblox axes), interpolation)]."""
    import struct
    data = _blob(blob)
    if len(data) < 16:
        return []
    _ver, n = struct.unpack_from("<II", data, 0)
    off = 8
    vals = []
    for _ in range(n):
        if len(data) < off + 25:
            raise CurveError("RotationCurve truncated")
        interp = data[off]
        x, y, z, w, _lt, _rt = struct.unpack_from("<6f", data, off + 1)
        vals.append((interp - 12 if interp >= 12 else interp, Quaternion((w, x, y, z))))
        off += 25
    times = _times(data, off, n)
    return [(t, q, i) for t, (i, q) in zip(times, vals)]


def decode_marker_curve(blob):
    import struct
    data = _blob(blob)
    if len(data) < 16:
        return []
    _ver, n = struct.unpack_from("<II", data, 0)
    off = 8
    names = []
    for _ in range(n):
        end = data.index(b"\x00", off)
        names.append(data[off:end].decode("utf-8", "replace"))
        off = end + 1
    return list(zip(_times(data, off, n), names))


def _derived_slopes(keys):
    """Slopes for keys whose tangents weren't authored (Catmull-Rom style)."""
    out = []
    for k, key in enumerate(keys):
        if 0 < k < len(keys) - 1:
            a, b = keys[k - 1], keys[k + 1]
            dt = b[0] - a[0]
            s = (b[1] - a[1]) / dt if dt > 1e-9 else 0.0
        else:
            s = 0.0
        out.append(s)
    return out


def eval_float_curve(keys, t):
    """Value of a decoded FloatCurve at time t (seconds)."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, v0, interp, _lt0, rt0, m0 = keys[lo]
    t1, v1, _i1, lt1, _rt1, m1 = keys[hi]
    h = t1 - t0
    if h <= 1e-9 or interp == _CONSTANT:
        return v0
    u = (t - t0) / h
    if interp == _LINEAR:
        return v0 + (v1 - v0) * u
    derived = _derived_slopes(keys) if not (m0 & 3) or not (m1 & 3) else None
    # right tangent of the left key, left tangent of the right key (value per second)
    s0 = rt0 if m0 & 2 else _lt_or(keys[lo], derived, lo, right=True)
    s1 = lt1 if m1 & 1 else _lt_or(keys[hi], derived, hi, right=False)
    u2, u3 = u * u, u * u * u
    return ((2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * h * s0 +
            (-2 * u3 + 3 * u2) * v1 + (u3 - u2) * h * s1)


def _lt_or(key, derived, idx, right):
    """A key's tangent when only the other side (or neither) was authored:
    mirrored from the authored one, else derived from the neighbours."""
    _t, _v, _i, lt, rt, m = key
    if right and m & 1:
        return lt
    if not right and m & 2:
        return rt
    return derived[idx] if derived else 0.0


def _euler_matrix(x, y, z, order):
    from mathutils import Matrix as M
    rots = {"X": M.Rotation(x, 3, "X"), "Y": M.Rotation(y, 3, "Y"), "Z": M.Rotation(z, 3, "Z")}
    m = rots[order[0]] @ rots[order[1]] @ rots[order[2]]
    return m


def _rotation_at(keys, t):
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for k in range(len(keys) - 1):
        t0, q0, interp = keys[k]
        t1, q1, _ = keys[k + 1]
        if t0 <= t <= t1:
            if interp == _CONSTANT or t1 - t0 <= 1e-9:
                return q0
            u = (t - t0) / (t1 - t0)
            if interp == _CUBIC:
                u = u * u * (3 - 2 * u)  # Roblox eases cubic rotation keys in and out
            return q0.slerp(q1, u)
    return keys[-1][1]


def _joint_curves(folder):
    """{"pos": [x, y, z keys], "euler": ([x, y, z keys], order) | None, "quat": keys | None}."""
    out = {}
    for c in folder.children:
        if c.class_name == "Vector3Curve" and c.name == "Position":
            axes = {a.name: decode_float_curve(a.get("ValuesAndTimes", default=b""))
                    for a in c.children if a.class_name == "FloatCurve"}
            out["pos"] = [axes.get(n, []) for n in ("X", "Y", "Z")]
        elif c.class_name == "EulerRotationCurve":
            axes = {a.name: decode_float_curve(a.get("ValuesAndTimes", default=b""))
                    for a in c.children if a.class_name == "FloatCurve"}
            order = _ROTATION_ORDERS.get(int(c.get("RotationOrder", default=0) or 0), "XYZ")
            out["euler"] = ([axes.get(n, []) for n in ("X", "Y", "Z")], order)
        elif c.class_name == "RotationCurve":
            out["quat"] = decode_rotation_curve(c.get("ValuesAndTimes", default=b""))
    return out


def _curve_joints(anim):
    """[(joint name, curves)] for every joint folder under a CurveAnimation."""
    found = []

    def walk(inst):
        for c in inst.children:
            if c.class_name == "Folder":
                curves = _joint_curves(c)
                if curves:
                    found.append((c.name, curves))
                walk(c)
    walk(anim)
    return found


def _key_times(curves):
    ts = set()
    for keys in curves.get("pos", []):
        ts.update(k[0] for k in keys)
    if curves.get("euler"):
        for keys in curves["euler"][0]:
            ts.update(k[0] for k in keys)
    ts.update(k[0] for k in curves.get("quat") or [])
    return ts


def curve_transform(curves, t):
    """Roblox Motor6D Transform (CFrame) of one joint at time t."""
    pos = [eval_float_curve(keys, t) if keys else 0.0 for keys in curves.get("pos", [[], [], []])]
    pos = [0.0 if v is None else v for v in pos]
    rot = Matrix.Identity(3)
    if curves.get("quat"):
        q = _rotation_at(curves["quat"], t)
        if q is not None:
            rot = q.to_matrix()
    elif curves.get("euler"):
        keys, order = curves["euler"]
        ang = [eval_float_curve(k, t) if k else 0.0 for k in keys]
        rot = _euler_matrix(*[0.0 if a is None else a for a in ang], order)
    return CFrame(tuple(pos), tuple(rot[i][j] for i in range(3) for j in range(3)))


def apply_curve_animation(context, anim, rig, start_frame=None, new_action=True):
    """Bake a CurveAnimation onto `rig` (one key per frame, so Roblox's curve
    tangents play back exactly). Returns (keyed frames, missing joints)."""
    scene = context.scene
    scale = coords.stud_scale(scene)
    fps = scene.render.fps / scene.render.fps_base
    start = scene.frame_current if start_frame is None else start_frame
    rig.animation_data_create()
    if new_action:
        rig.animation_data.action = bpy.data.actions.new(anim.name or "Animation")
    action = rig.animation_data.action
    if action is not None:
        action["rbx_loop"] = bool(anim.get("Loop", default=False))
        action["rbx_priority"] = int(anim.get("Priority", default=2) or 2)
    joints = _curve_joints(anim)
    missing = set()
    end_t = 0.0
    for _n, curves in joints:
        ts = _key_times(curves)
        if ts:
            end_t = max(end_t, max(ts))
    last = start + int(math.ceil(end_t * fps))
    frames = list(range(start, last + 1))
    for name, curves in joints:
        pb = rig.pose.bones.get(name)
        if pb is None:
            missing.add(name)
            continue
        pb.rotation_mode = "QUATERNION"
        prev = None
        for f in frames:
            cf = curve_transform(curves, (f - start) / fps)
            pb.matrix_basis = transform_to_basis(cf, scale)
            q = pb.rotation_quaternion.copy()
            if prev is not None:
                q.make_compatible(prev)
            pb.rotation_quaternion = q
            prev = q
            pb.keyframe_insert("location", frame=f, group=pb.name)
            pb.keyframe_insert("rotation_quaternion", frame=f, group=pb.name)
    from .animate import fcurves_of
    for fc in fcurves_of(rig):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    for c in anim.descendants():
        if c.class_name == "MarkerCurve":
            for t, label in decode_marker_curve(c.get("ValuesAndTimes", default=b"")):
                scene.timeline_markers.new(label or c.name, frame=start + round(t * fps))
    if frames and frames[-1] > scene.frame_end:
        scene.frame_end = frames[-1]
    return frames, sorted(missing)


def _poses(pose_parent):
    for p in pose_parent.children:
        if p.class_name == "Pose":
            yield p
            yield from _poses(p)


def rig_for(context):
    """The armature to animate: the active rig, or the rig of the active part's character."""
    obj = context.active_object
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    o = obj
    while o is not None:
        if o.type == "ARMATURE":
            return o
        for c in o.children:
            if c.type == "ARMATURE":
                return c
        o = o.parent
    return None


def _fcurves(id_data):
    from .animate import fcurves_of
    return fcurves_of(id_data)


def apply_sequence(context, seq, rig, start_frame=None, new_action=True):
    """Key a KeyframeSequence (or CurveAnimation) onto `rig`. Returns (keyed
    frames, missing joints)."""
    if seq.class_name == "CurveAnimation":
        return apply_curve_animation(context, seq, rig, start_frame, new_action)
    scene = context.scene
    scale = coords.stud_scale(scene)
    fps = scene.render.fps / scene.render.fps_base
    start = scene.frame_current if start_frame is None else start_frame
    rig.animation_data_create()
    if new_action:
        action = bpy.data.actions.new(seq.name or "Animation")
        rig.animation_data.action = action
    action = rig.animation_data.action
    if action is not None:
        action["rbx_loop"] = bool(seq.get("Loop", default=False))
        action["rbx_priority"] = int(seq.get("Priority", default=2) or 2)

    keyframes = sorted((k for k in seq.children if k.class_name == "Keyframe"),
                       key=lambda k: float(k.get("Time", default=0.0)))
    missing = set()
    frames = []
    for kf in keyframes:
        frame = start + round(float(kf.get("Time", default=0.0)) * fps)
        frames.append(frame)
        for pose in _poses(kf):
            pb = rig.pose.bones.get(pose.name)
            if pb is None:
                missing.add(pose.name)
                continue
            if float(pose.get("Weight", default=1.0) or 0.0) <= 0.0:
                continue  # hierarchy placeholder
            cf = pose.get("CFrame")
            pb.rotation_mode = "QUATERNION"
            prev = pb.rotation_quaternion.copy()
            pb.matrix_basis = transform_to_basis(cf if isinstance(cf, CFrame) else CFrame(), scale)
            q = pb.rotation_quaternion.copy()
            q.make_compatible(prev)
            pb.rotation_quaternion = q
            group = pb.name
            pb.keyframe_insert("location", frame=frame, group=group)
            pb.keyframe_insert("rotation_quaternion", frame=frame, group=group)
            style_id = int(pose.get("EasingStyle", default=0) or 0)
            dir_id = int(pose.get("EasingDirection", default=0) or 0)
            style = POSE_STYLES.get(style_id, "LINEAR")
            direction = POSE_DIRS.get(dir_id, "EASE_IN")
            if style_id in _SWAPPED_STYLES:
                direction = _FLIP[direction]
            from .animate import set_ease
            base = 'pose.bones["%s"].' % bpy.utils.escape_identifier(pb.name)
            set_ease(rig, [base + "location", base + "rotation_quaternion"], frame, style, direction)
    for m in (k for k in seq.descendants() if k.class_name == "KeyframeMarker"):
        kf = m.parent
        if kf is not None and kf.class_name == "Keyframe":
            f = start + round(float(kf.get("Time", default=0.0)) * fps)
            scene.timeline_markers.new(m.get("Value", default="") or m.name, frame=f)
    if frames and max(frames) > scene.frame_end:
        scene.frame_end = max(frames)
    return frames, sorted(missing)


# ---------------------------------------------------------------------------
# Export

def _bone_keys(rig):
    """{bone name: {frame: (interpolation, easing)}} for keyed rotation/location."""
    out = {}
    for fc in _fcurves(rig):
        p = fc.data_path
        if not p.startswith('pose.bones["'):
            continue
        name = p[len('pose.bones["'):p.index('"]')]
        name = name.replace('\\"', '"').replace("\\\\", "\\")
        d = out.setdefault(name, {})
        for k in fc.keyframe_points:
            f = int(round(k.co.x))
            if f not in d or p.endswith("rotation_quaternion") or p.endswith("rotation_euler"):
                d[f] = (k.interpolation, k.easing)
    return out


def sequence_items(context, rig, name=None, loop=None, priority=None, bake_unsupported=True):
    """KeyframeSequence Item for the rig's current action."""
    scene = context.scene
    scale = coords.stud_scale(scene)
    fps = scene.render.fps / scene.render.fps_base
    keys = _bone_keys(rig)
    if not keys:
        return None
    frames = sorted({f for d in keys.values() for f in d})
    start = frames[0]
    # Roblox poses only ease Linear/Constant/Cubic/Elastic/Bounce: sample other easings per frame
    if bake_unsupported:
        extra = set()
        for d in keys.values():
            fs = sorted(d)
            for a, b in zip(fs, fs[1:]):
                interp = d[a][0]
                if interp not in _STYLE_IDS:
                    extra.update(range(a + 1, b))
        frames = sorted(set(frames) | extra)
    action = rig.animation_data.action if rig.animation_data else None
    seq = Item("KeyframeSequence", name or (action.name if action else rig.name))
    seq.prop("bool", "Loop", loop if loop is not None else bool(action.get("rbx_loop", False)) if action else False)
    seq.prop("token", "Priority", priority if priority is not None else
             int(action.get("rbx_priority", 2)) if action else 2)
    bones = rig.pose.bones
    animated = set(keys)
    # every bone on the way from the root to an animated bone needs a Pose
    needed = set()
    for n in animated:
        b = bones.get(n)
        while b is not None:
            needed.add(b.name)
            b = b.parent
    cur = scene.frame_current
    try:
        for f in frames:
            scene.frame_set(f)
            kf = seq.add(Item("Keyframe", "Keyframe"))
            kf.prop("float", "Time", (f - start) / fps)

            def add_pose(parent_item, pb):
                if pb.name not in needed:
                    return
                pose = parent_item.add(Item("Pose", pb.name))
                pos, rot = basis_to_transform(pb.matrix_basis, scale)
                pose.prop("CoordinateFrame", "CFrame", (pos, rot))
                key = keys.get(pb.name, {}).get(f)
                weight = 1.0 if pb.name in animated else 0.0
                pose.prop("float", "Weight", weight)
                interp, easing = key if key else ("LINEAR", "AUTO")
                style = _STYLE_IDS.get(interp, 0)
                direction = easing if easing != "AUTO" else "EASE_IN_OUT"
                if style in _SWAPPED_STYLES:
                    direction = _FLIP.get(direction, direction)
                pose.prop("token", "EasingStyle", style)
                pose.prop("token", "EasingDirection", _DIR_IDS.get(direction, 2))
                for c in pb.children:
                    add_pose(pose, c)

            for root in (b for b in bones if b.parent is None):
                add_pose(kf, root)
    finally:
        scene.frame_set(cur)
    return seq


def export_sequence(context, rig, path, **kw):
    seq = sequence_items(context, rig, **kw)
    if seq is None:
        return False
    write_file(path, [seq])
    return True
