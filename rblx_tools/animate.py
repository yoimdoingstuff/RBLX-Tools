"""Animation Mode: animate Roblox rigs and parts the way Moon Animator 2 and
Eclipse Animator do, in Blender.

Turned on with the Animate button (3D View header in the Animation
workspace, or the Dope Sheet / Timeline header). It adds a "Roblox Animate"
tool:

* Click a body part to pick its joint (the bone it's attached to); Alt+click
  picks the part / model itself. Shift adds to the selection.
* Rotation rings turn the joint around its pivot; R switches to move arrows,
  Y switches world / local axes, C toggles rotation snapping.
* Every handle drag sets a keyframe at the current frame with the chosen
  easing (Linear, Sine, Back, Quad, Cubic, Quart, Quint, Expo, Circ, Bounce,
  Elastic, Constant; In / Out / InOut). Easing shapes the motion from that
  keyframe to the next, like Roblox's own keyframes.
* Moon / Eclipse keys: Space play, 1 start, 4 / 6 previous / next frame,
  J / K previous / next keyframe, = add keyframe, G reset the joint, Delete
  delete the keyframe, Ctrl+C / Ctrl+V copy / paste the pose, 7 edit the
  easing, F focus, Ctrl+Z / Ctrl+Y undo / redo. WASD / right mouse camera
  like Build Mode.

The timeline is Blender's Dope Sheet / Timeline."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy_extras import anim_utils, view3d_utils
from mathutils import Matrix, Quaternion, Vector

from . import build, coords

TOOL_ANIMATE = "rblx.tool_animate"
_state = {"on": False, "registered": False}
LAST_HANDLES = {}
_clipboard = {"bones": {}, "objects": {}}

EASE_STYLES = ("LINEAR", "CONSTANT", "SINE", "BACK", "QUAD", "CUBIC", "QUART", "QUINT", "EXPO",
               "CIRC", "BOUNCE", "ELASTIC", "BEZIER")
EASE_DIRS = {"IN": "EASE_IN", "OUT": "EASE_OUT", "IN_OUT": "EASE_IN_OUT"}


def is_on():
    return _state["on"]


def is_anim_workspace(context):
    ws = getattr(context, "workspace", None)
    return ws is not None and ws.name.lower().startswith("anim")


# ---------------------------------------------------------------------------
# Targets: things that can be posed and keyed (rig joints or objects)

class BoneTarget:
    def __init__(self, arm, pb):
        self.arm, self.pb = arm, pb
        self.id = arm
        self.name = pb.name

    def get(self):
        return self.arm.matrix_world @ self.pb.matrix

    def set(self, m):
        self.pb.matrix = self.arm.matrix_world.inverted() @ m

    def pivot(self):
        return self.get().translation

    def parts(self):
        return [o for o in self.arm.children
                if o.parent_type == "BONE" and o.parent_bone == self.pb.name]

    def paths(self):
        base = 'pose.bones["%s"].' % bpy.utils.escape_identifier(self.pb.name)
        rot = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
            self.pb.rotation_mode, "rotation_euler")
        return [base + "location", base + rot]

    def snapshot(self):
        pb = self.pb
        return (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(),
                pb.scale.copy())

    def restore(self, snap):
        pb = self.pb
        pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = snap

    def keep_continuous(self, snap):
        if self.pb.rotation_mode == "QUATERNION":
            q = self.pb.rotation_quaternion.copy()
            q.make_compatible(snap[1])
            self.pb.rotation_quaternion = q

    def reset(self):
        pb = self.pb
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


class ObjectTarget:
    def __init__(self, obj):
        self.obj = obj
        self.id = obj
        self.name = obj.name

    def get(self):
        return self.obj.matrix_world.copy()

    def set(self, m):
        self.obj.matrix_world = m

    def pivot(self):
        return self.obj.matrix_world.translation.copy()

    def parts(self):
        return [self.obj]

    def paths(self):
        rot = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
            self.obj.rotation_mode, "rotation_euler")
        return ["location", rot]

    def snapshot(self):
        return self.obj.matrix_basis.copy()

    def restore(self, snap):
        self.obj.matrix_basis = snap

    def keep_continuous(self, snap):
        if self.obj.rotation_mode not in ("QUATERNION", "AXIS_ANGLE"):
            e = self.obj.rotation_euler.copy()
            e.make_compatible(snap.to_euler(self.obj.rotation_mode))
            self.obj.rotation_euler = e

    def reset(self):
        return False


def bone_selected(pb):
    """Blender 5 keeps bone selection on the pose bone; 4.x on the bone."""
    return pb.select if hasattr(pb, "select") else pb.bone.select


def select_bone(pb, state=True):
    if hasattr(pb, "select"):
        pb.select = state
    else:
        pb.bone.select = state


def selected_targets(context):
    """Selected joints (bones of selected rigs) and selected objects, without
    things whose parent is also being posed."""
    targets, posed_arms = [], set()
    for o in context.selected_objects:
        if o.type == "ARMATURE":
            bones = [pb for pb in o.pose.bones if bone_selected(pb)]
            names = {pb.name for pb in bones}
            for pb in bones:
                p = pb.parent
                while p is not None and p.name not in names:
                    p = p.parent
                if p is None:
                    targets.append(BoneTarget(o, pb))
            if bones:
                posed_arms.add(o)
    rest = [o for o in context.selected_objects if o not in posed_arms]
    for o in build.moving_roots(rest):
        if o.parent in posed_arms and o.parent_type == "BONE":
            continue  # a body part highlighted for its joint
        targets.append(ObjectTarget(o))
    return targets


def target_frame(context, targets, local=None):
    """(centre, axes, radius) for the handles."""
    if not targets:
        return None
    s = context.scene.rblx
    if local is None:
        local = s.handle_space == "LOCAL"
    first = targets[0]
    axes = build.orthonormal(first.get().to_3x3()) if local else Matrix.Identity(3)
    center = sum((t.pivot() for t in targets), Vector()) / len(targets)
    pts = []
    for t in targets:
        pts += build.world_points(t.parts())
    scale = coords.stud_scale(context.scene)
    if pts:
        radius = max((p - center).length for p in pts)
        radius = min(max(radius * 0.75, 0.75 * scale), 6.0 * scale)
    else:
        radius = 1.0 * scale
    return center, axes, radius


# ---------------------------------------------------------------------------
# Keyframes and easing

def fcurves_of(id_data):
    ad = id_data.animation_data
    if ad is None or ad.action is None:
        return []
    try:
        cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    except (AttributeError, TypeError):
        cb = None
    if cb is not None:
        return list(cb.fcurves)
    return list(getattr(ad.action, "fcurves", []))


def set_ease(id_data, paths, frame, style, direction):
    """Give the keyframes at `frame` on these channels the easing."""
    n = 0
    paths = set(paths)
    for fc in fcurves_of(id_data):
        if fc.data_path not in paths:
            continue
        for k in fc.keyframe_points:
            if abs(k.co.x - frame) < 0.5:
                k.interpolation = style
                if direction in EASE_DIRS.values():
                    k.easing = direction
                n += 1
        fc.update()
    return n


def key_targets(context, targets, ease=True):
    scene = context.scene
    frame = scene.frame_current
    s = scene.rblx
    for t in targets:
        for path in t.paths():
            try:
                t.id.keyframe_insert(path, frame=frame,
                                     group=t.name if isinstance(t, BoneTarget) else None)
            except (RuntimeError, TypeError):
                t.id.keyframe_insert(path, frame=frame)
        if ease:
            set_ease(t.id, t.paths(), frame, s.anim_ease_style, EASE_DIRS[s.anim_ease_dir])


def ensure_frame_rate(scene):
    """Moon Animator and Eclipse work at 60 fps: use that for scenes that
    don't have any animation yet."""
    if scene.render.fps == 60:
        return False
    if any(o.animation_data and o.animation_data.action for o in scene.objects):
        return False
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    return True


# ---------------------------------------------------------------------------
# Click selection

class RBLX_OT_anim_click(bpy.types.Operator):
    """Click a body part to pick its joint (Alt: the part or model itself)"""
    bl_idname = "rblx.anim_click"
    bl_label = "Pick Joint"
    bl_options = {"REGISTER", "UNDO"}

    extend: BoolProperty(default=False, options={"SKIP_SAVE"})
    part_only: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and context.mode == "OBJECT"

    def invoke(self, context, event):
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin, direction = build.mouse_ray(context, coord)
        hit = build.ray_cast(context, origin, direction, skip_locked=False)
        if not self.extend:
            deselect_all(context)
        if hit is None:
            return {"FINISHED"}
        obj = hit[2]
        arm = obj.parent if (obj.parent is not None and obj.parent.type == "ARMATURE"
                             and obj.parent_type == "BONE") else None
        if arm is not None and not self.part_only and obj.parent_bone in arm.pose.bones:
            bone = arm.data.bones[obj.parent_bone]
            pb = arm.pose.bones[obj.parent_bone]
            if self.extend and bone_selected(pb):
                select_bone(pb, False)
                obj.select_set(False)
                return {"FINISHED"}
            select_bone(pb, True)
            arm.data.bones.active = bone
            arm.select_set(True)
            obj.select_set(True)
            context.view_layer.objects.active = arm
        else:
            target = build.pick_target(obj, self.part_only)
            if self.extend and target.select_get():
                build.select_target(target, False)
                return {"FINISHED"}
            build.select_target(target, True)
            context.view_layer.objects.active = target
        return {"FINISHED"}


def deselect_all(context):
    for o in context.selected_objects:
        o.select_set(False)
    for o in context.scene.objects:
        if o.type == "ARMATURE":
            for pb in o.pose.bones:
                if bone_selected(pb):
                    select_bone(pb, False)


# ---------------------------------------------------------------------------
# Handles (rotate rings / move arrows) that key on release

class RBLX_OT_anim_handle(bpy.types.Operator):
    """Drag to pose; a keyframe is set when you let go"""
    bl_idname = "rblx.anim_handle"
    bl_label = "Pose"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    mode: EnumProperty(items=[("MOVE", "Move", ""), ("ROTATE", "Rotate", "")], default="ROTATE")
    axis: IntProperty(min=0, max=2, default=0)
    sign: IntProperty(default=1)

    def invoke(self, context, event):
        if context.region_data is None:
            return {"CANCELLED"}
        self.targets = selected_targets(context)
        frame = target_frame(context, self.targets)
        if frame is None:
            return {"CANCELLED"}
        self.center, axes, _r = frame
        self.dir = axes.col[self.axis].normalized() * (1.0 if self.sign >= 0 else -1.0)
        self.start = [(t, t.get(), t.snapshot()) for t in self.targets]
        coord = (event.mouse_region_x, event.mouse_region_y)
        self.value = 0.0
        if self.mode == "ROTATE":
            view = context.region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
            self.planar = abs(view.dot(self.dir)) > 0.2
            self.b1 = self.dir.orthogonal().normalized()
            self.b2 = self.dir.cross(self.b1)
            self.c2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data,
                                                             self.center)
            if self.c2d is None:
                return {"CANCELLED"}
            self.prev = self.angle(context, coord)
            if self.prev is None:
                return {"CANCELLED"}
            self.total = 0.0
        else:
            t = build.line_param(*build.mouse_ray(context, coord), self.center, self.dir)
            if t is None:
                return {"CANCELLED"}
            self.t0 = t
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def angle(self, context, coord):
        if not self.planar:
            return math.atan2(coord[1] - self.c2d.y, coord[0] - self.c2d.x)
        origin, direction = build.mouse_ray(context, coord)
        den = direction.dot(self.dir)
        if abs(den) < 1e-6:
            return None
        p = origin + direction * ((self.center - origin).dot(self.dir) / den)
        v = p - self.center
        return math.atan2(v.dot(self.b2), v.dot(self.b1))

    def apply(self, context, event):
        s = context.scene.rblx
        coord = (event.mouse_region_x, event.mouse_region_y)
        if self.mode == "ROTATE":
            a = self.angle(context, coord)
            if a is None:
                return
            d = (a - self.prev + math.pi) % (2 * math.pi) - math.pi
            self.prev = a
            self.total += d
            if self.planar:
                ang = self.total
            else:
                view = context.region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
                ang = self.total if self.dir.dot(view) < 0 else -self.total
            ang = build.snap(ang, math.radians(s.rotate_increment) if s.snap_rotate else 0.0)
            self.value = math.degrees(ang)
            m = (Matrix.Translation(self.center) @ Matrix.Rotation(ang, 4, self.dir) @
                 Matrix.Translation(-self.center))
            label = "Rotate %.1f°" % self.value
        else:
            t = build.line_param(*build.mouse_ray(context, coord), self.center, self.dir)
            if t is None:
                return
            delta = build.snap(t - self.t0, build.move_step(context))
            self.value = delta / coords.stud_scale(context.scene)
            m = Matrix.Translation(self.dir * delta)
            label = "Move %.3g studs" % self.value
        for tgt, m0, snap0 in self.start:
            tgt.set(m @ m0)
            tgt.keep_continuous(snap0)
        if context.area is not None:
            context.area.header_text_set(label + "  (keyframe on release)")

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            self.apply(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if context.area is not None:
                context.area.header_text_set(None)
            if abs(self.value) > 1e-6:
                key_targets(context, self.targets)
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            for tgt, _m0, snap0 in self.start:
                tgt.restore(snap0)
            if context.area is not None:
                context.area.header_text_set(None)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class RBLX_GGT_anim(bpy.types.GizmoGroup):
    bl_idname = "RBLX_GGT_anim"
    bl_label = "Roblox Animation Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        if not _state["on"] or context.mode != "OBJECT" or not context.selected_objects:
            return False
        try:
            tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        except (AttributeError, TypeError):
            return False
        return tool is not None and tool.idname == TOOL_ANIMATE

    def _gizmo(self, kind, mode, axis, sign):
        gz = self.gizmos.new(kind)
        props = gz.target_set_operator("rblx.anim_handle")
        props.mode, props.axis, props.sign = mode, axis, sign
        gz.color = build.AXIS_COLORS[axis]
        gz.alpha = 0.85
        gz.color_highlight = tuple(min(1.0, c + 0.3) for c in build.AXIS_COLORS[axis])
        gz.alpha_highlight = 1.0
        return gz

    def setup(self, context):
        self.rings, self.arrows = [], []
        for axis in range(3):
            gz = self._gizmo("GIZMO_GT_dial_3d", "ROTATE", axis, 1)
            gz.draw_options = {"CLIP"}
            gz.line_width = 3.0
            gz.use_draw_scale = False
            self.rings.append((gz, axis))
            for sign in (1, -1):
                gz = self._gizmo("GIZMO_GT_arrow_3d", "MOVE", axis, sign)
                gz.line_width = 3.0
                gz.length = 0.6
                self.arrows.append((gz, axis, sign))

    def draw_prepare(self, context):
        LAST_HANDLES["ROTATE"], LAST_HANDLES["MOVE"] = self.rings, self.arrows
        targets = selected_targets(context)
        frame = target_frame(context, targets)
        rotate = context.scene.rblx.anim_handle_mode == "ROTATE"
        for gz, _a in self.rings:
            gz.hide = frame is None or not rotate
        for gz, _a, _s in self.arrows:
            gz.hide = frame is None or rotate
        if frame is None:
            return
        center, axes, radius = frame
        for gz, axis in self.rings:
            m = axes.col[axis].to_track_quat("Z", "Y").to_matrix().to_4x4()
            m.translation = center
            gz.matrix_basis = m @ Matrix.Scale(radius, 4)
        for gz, axis, sign in self.arrows:
            d = axes.col[axis] * sign
            m = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
            m.translation = center + d * radius * 0.5
            gz.matrix_basis = m


# ---------------------------------------------------------------------------
# Moon / Eclipse actions

class _TargetOp:
    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)


class RBLX_OT_anim_key(_TargetOp, bpy.types.Operator):
    """Add a keyframe for the selected joints / parts at the current frame (=)"""
    bl_idname = "rblx.anim_key"
    bl_label = "Add Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = selected_targets(context)
        key_targets(context, targets)
        self.report({"INFO"}, "Keyed %d item(s) at frame %d" % (len(targets), context.scene.frame_current))
        return {"FINISHED"}


class RBLX_OT_anim_reset(_TargetOp, bpy.types.Operator):
    """Put the selected joints back in their default pose and key it (G)"""
    bl_idname = "rblx.anim_reset"
    bl_label = "Reset Joint"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = [t for t in selected_targets(context) if isinstance(t, BoneTarget)]
        if not targets:
            self.report({"INFO"}, "Select a joint (click a body part) to reset it")
            return {"CANCELLED"}
        for t in targets:
            t.reset()
        key_targets(context, targets)
        return {"FINISHED"}


class RBLX_OT_anim_delete_key(_TargetOp, bpy.types.Operator):
    """Delete the selected joints' / parts' keyframes at the current frame (Delete)"""
    bl_idname = "rblx.anim_delete_key"
    bl_label = "Delete Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        frame = context.scene.frame_current
        n = 0
        for t in selected_targets(context):
            for path in t.paths():
                try:
                    if t.id.keyframe_delete(path, frame=frame):
                        n += 1
                except RuntimeError:
                    pass
        self.report({"INFO"}, "Deleted keyframes on %d channel(s)" % n if n else "No keyframe here")
        return {"FINISHED"}


class RBLX_OT_anim_copy(_TargetOp, bpy.types.Operator):
    """Copy the selected joints' / parts' pose (Ctrl+C)"""
    bl_idname = "rblx.anim_copy"
    bl_label = "Copy Pose"

    def execute(self, context):
        _clipboard["bones"].clear()
        _clipboard["objects"].clear()
        for t in selected_targets(context):
            if isinstance(t, BoneTarget):
                _clipboard["bones"][t.name] = t.snapshot()
            else:
                _clipboard["objects"][t.name] = t.snapshot()
        n = len(_clipboard["bones"]) + len(_clipboard["objects"])
        self.report({"INFO"}, "Copied %d pose(s)" % n)
        return {"FINISHED"}


class RBLX_OT_anim_paste(_TargetOp, bpy.types.Operator):
    """Paste the copied pose onto the selected joints / parts and key it (Ctrl+V)"""
    bl_idname = "rblx.anim_paste"
    bl_label = "Paste Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = selected_targets(context)
        bones, objs = _clipboard["bones"], _clipboard["objects"]
        done = []
        for t in targets:
            src = bones if isinstance(t, BoneTarget) else objs
            snap = src.get(t.name)
            if snap is None and len(src) == 1 and len(targets) == 1:
                snap = next(iter(src.values()))  # one joint onto another
            if snap is not None:
                t.restore(snap)
                done.append(t)
        if not done:
            self.report({"INFO"}, "Nothing copied for these joints")
            return {"CANCELLED"}
        key_targets(context, done)
        return {"FINISHED"}


class RBLX_OT_anim_ease(bpy.types.Operator):
    """Set the easing of the selected joints' / parts' keyframes at the current frame (7)"""
    bl_idname = "rblx.anim_ease"
    bl_label = "Edit Easing"
    bl_options = {"REGISTER", "UNDO"}

    style: EnumProperty(name="Ease", items=[
        ("LINEAR", "Linear", ""), ("CONSTANT", "Constant", ""), ("SINE", "Sine", ""),
        ("BACK", "Back", ""), ("QUAD", "Quad", ""), ("CUBIC", "Cubic", ""), ("QUART", "Quart", ""),
        ("QUINT", "Quint", ""), ("EXPO", "Expo", ""), ("CIRC", "Circ", ""),
        ("BOUNCE", "Bounce", ""), ("ELASTIC", "Elastic", ""), ("BEZIER", "Smooth (Blender)", "")],
        default="LINEAR")
    direction: EnumProperty(name="Direction", items=[("IN", "In", ""), ("OUT", "Out", ""),
                                                     ("IN_OUT", "InOut", "")], default="IN_OUT")
    also_default: BoolProperty(name="Use for new keyframes", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def invoke(self, context, event):
        s = context.scene.rblx
        self.style, self.direction = s.anim_ease_style, s.anim_ease_dir
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        s = context.scene.rblx
        if self.also_default:
            s.anim_ease_style, s.anim_ease_dir = self.style, self.direction
        frame = context.scene.frame_current
        n = 0
        for t in selected_targets(context):
            n += set_ease(t.id, t.paths(), frame, self.style, EASE_DIRS[self.direction])
        self.report({"INFO"}, "Eased %d keyframe channel(s) at frame %d" % (n, frame))
        return {"FINISHED"}


class RBLX_OT_anim_toggle_handles(bpy.types.Operator):
    """Switch between rotation rings and move arrows (R, like Moon Animator)"""
    bl_idname = "rblx.anim_toggle_handles"
    bl_label = "Rotate / Move Handles"

    def execute(self, context):
        s = context.scene.rblx
        s.anim_handle_mode = "MOVE" if s.anim_handle_mode == "ROTATE" else "ROTATE"
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Tool, mode toggle and UI

ANIM_KEYS = [
    ("rblx.anim_click", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    ("rblx.anim_click", {"type": "LEFTMOUSE", "value": "PRESS", "shift": True},
     {"properties": [("extend", True)]}),
    ("rblx.anim_click", {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True},
     {"properties": [("extend", True)]}),
    ("rblx.anim_click", {"type": "LEFTMOUSE", "value": "PRESS", "alt": True},
     {"properties": [("part_only", True)]}),
    ("screen.animation_play", {"type": "SPACE", "value": "PRESS"}, None),
    ("screen.frame_jump", {"type": "ONE", "value": "PRESS"}, {"properties": [("end", False)]}),
    ("screen.frame_offset", {"type": "FOUR", "value": "PRESS", "repeat": True},
     {"properties": [("delta", -1)]}),
    ("screen.frame_offset", {"type": "SIX", "value": "PRESS", "repeat": True},
     {"properties": [("delta", 1)]}),
    ("screen.keyframe_jump", {"type": "J", "value": "PRESS"}, {"properties": [("next", False)]}),
    ("screen.keyframe_jump", {"type": "K", "value": "PRESS"}, {"properties": [("next", True)]}),
    ("rblx.anim_toggle_handles", {"type": "R", "value": "PRESS"}, None),
    ("rblx.toggle_handle_space", {"type": "Y", "value": "PRESS"}, None),
    ("wm.context_toggle", {"type": "C", "value": "PRESS"},
     {"properties": [("data_path", "scene.rblx.snap_rotate")]}),
    ("rblx.anim_key", {"type": "EQUAL", "value": "PRESS"}, None),
    ("rblx.anim_key", {"type": "NUMPAD_PLUS", "value": "PRESS"}, None),
    ("rblx.anim_reset", {"type": "G", "value": "PRESS"}, None),
    ("rblx.anim_delete_key", {"type": "DEL", "value": "PRESS"}, None),
    ("rblx.anim_delete_key", {"type": "X", "value": "PRESS"}, None),
    ("rblx.anim_delete_key", {"type": "NUMPAD_MINUS", "value": "PRESS"}, None),
    ("rblx.anim_copy", {"type": "C", "value": "PRESS", "ctrl": True}, None),
    ("rblx.anim_paste", {"type": "V", "value": "PRESS", "ctrl": True}, None),
    ("rblx.anim_ease", {"type": "SEVEN", "value": "PRESS"}, None),
    ("ed.redo", {"type": "Y", "value": "PRESS", "ctrl": True}, None),
] + [k for k in build.STUDIO_KEYS
     if k[0] in ("rblx.studio_camera", "rblx.studio_zoom", "view3d.move", "view3d.rotate",
                 "view3d.view_selected")]


class RBLX_TL_animate(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = TOOL_ANIMATE
    bl_label = "Roblox Animate"
    bl_description = ("Click body parts to pose their joints; dragging the rings / arrows sets "
                      "keyframes (Moon Animator / Eclipse style)")
    bl_icon = "ops.transform.rotate"
    bl_widget = None
    bl_keymap = tuple(ANIM_KEYS)

    @staticmethod
    def draw_settings(context, layout, tool):
        if context.region is not None and context.region.type == "TOOL_HEADER":
            return  # the animation toolbar is drawn there
        draw_settings(layout, context)


def draw_settings(layout, context):
    s = context.scene.rblx
    layout.prop(s, "anim_handle_mode", expand=True)
    layout.prop(s, "handle_space", text="")
    row = layout.row(align=True)
    row.prop(s, "snap_rotate", text="", icon="SNAP_INCREMENT")
    sub = row.row(align=True)
    sub.active = s.snap_rotate
    sub.prop(s, "rotate_increment", text="Rotate")
    row = layout.row(align=True)
    row.prop(s, "anim_ease_style", text="")
    sub = row.row(align=True)
    sub.active = s.anim_ease_style not in ("LINEAR", "CONSTANT", "BEZIER")
    sub.prop(s, "anim_ease_dir", text="")


def _set_tool(context, ident):
    return build._set_tool(context, ident)


def set_anim_mode(context, on):
    if on == _state["on"]:
        return
    if on:
        if build.is_on():
            build.set_build_mode(context, False)
        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                pass
        if not _state["registered"]:
            try:
                bpy.utils.register_tool(RBLX_TL_animate, after={"builtin.transform"},
                                        separator=True, group=False)
            except Exception:
                bpy.utils.register_tool(RBLX_TL_animate, separator=True, group=False)
            _state["registered"] = True
        _state["on"] = True
        if context.scene is not None:
            ensure_frame_rate(context.scene)
        _set_tool(context, TOOL_ANIMATE)
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.show_region_tool_header = True
                elif area.type == "DOPESHEET_EDITOR":
                    # Like Moon's timeline: show every item's tracks, not only the selected
                    ds = area.spaces.active.dopesheet
                    if ds.show_only_selected:
                        ds.show_only_selected = False
                        _state.setdefault("dopesheets", []).append(ds)
    else:
        for ds in _state.pop("dopesheets", []):
            try:
                ds.show_only_selected = True
            except ReferenceError:
                pass
        _state["on"] = False
        try:
            tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        except (AttributeError, TypeError):
            tool = None
        if tool is not None and tool.idname == TOOL_ANIMATE:
            _set_tool(context, "builtin.select_box")
        if _state["registered"]:
            try:
                bpy.utils.unregister_tool(RBLX_TL_animate)
            except Exception:
                pass
            _state["registered"] = False
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class RBLX_OT_toggle_anim_mode(bpy.types.Operator):
    """Animation Mode: pose Roblox rigs and parts and set keyframes like Moon Animator 2 /
    Eclipse Animator. Click again to go back to Blender's tools"""
    bl_idname = "rblx.toggle_anim_mode"
    bl_label = "Animation Mode"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        set_anim_mode(context, not _state["on"])
        self.report({"INFO"}, "Animation Mode " + ("on" if _state["on"] else "off"))
        return {"FINISHED"}


def draw_toggle(layout, text="Animate"):
    layout.operator(RBLX_OT_toggle_anim_mode.bl_idname, text=text, icon="ARMATURE_DATA",
                    depress=_state["on"])


def draw_dopesheet_button(self, context):
    draw_toggle(self.layout)


def draw_anim_toolbar(self, context):
    """Moon-style bar at the top of the 3D View while Animation Mode is on."""
    if not _state["on"] or context.mode != "OBJECT":
        return
    layout = self.layout
    scene = context.scene
    s = scene.rblx
    row = layout.row(align=True)
    row.operator("screen.frame_jump", text="", icon="REW").end = False
    row.operator("screen.keyframe_jump", text="", icon="PREV_KEYFRAME").next = False
    playing = context.screen is not None and context.screen.is_animation_playing
    row.operator("screen.animation_play", text="", icon="PAUSE" if playing else "PLAY")
    row.operator("screen.keyframe_jump", text="", icon="NEXT_KEYFRAME").next = True
    row.operator("screen.frame_jump", text="", icon="FF").end = True
    # (frame, end and fps are in the timeline below)

    row = layout.row(align=True)
    row.operator("rblx.anim_key", text="Key", icon="KEY_HLT")
    row.operator("rblx.anim_delete_key", text="", icon="KEY_DEHLT")
    row.operator("rblx.anim_reset", text="", icon="LOOP_BACK")

    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.ui_units_x = 4.0
    sub.prop(s, "anim_ease_style", text="")
    sub = row.row(align=True)
    sub.ui_units_x = 3.0
    sub.active = s.anim_ease_style not in ("LINEAR", "CONSTANT", "BEZIER")
    sub.prop(s, "anim_ease_dir", text="")
    row.operator("rblx.anim_ease", text="", icon="IPO_EASE_IN_OUT")

    row = layout.row(align=True)
    row.prop(s, "anim_handle_mode", expand=True, icon_only=True)
    layout.prop(s, "handle_space", text="", icon_only=True)
    row = layout.row(align=True)
    row.prop(s, "snap_rotate", text="", icon="SNAP_INCREMENT")
    sub = row.row(align=True)
    sub.active = s.snap_rotate
    sub.ui_units_x = 3.0
    sub.prop(s, "rotate_increment", text="")

    targets = selected_targets(context)
    if targets:
        names = ", ".join(t.name for t in targets[:3]) + ("..." if len(targets) > 3 else "")
        layout.label(text=names, icon="BONE_DATA" if isinstance(targets[0], BoneTarget)
                     else "OBJECT_DATA")


CLASSES = (
    RBLX_OT_anim_click,
    RBLX_OT_anim_handle,
    RBLX_GGT_anim,
    RBLX_OT_anim_key,
    RBLX_OT_anim_reset,
    RBLX_OT_anim_delete_key,
    RBLX_OT_anim_copy,
    RBLX_OT_anim_paste,
    RBLX_OT_anim_ease,
    RBLX_OT_anim_toggle_handles,
    RBLX_OT_toggle_anim_mode,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_HT_tool_header.prepend(draw_anim_toolbar)
    bpy.types.DOPESHEET_HT_header.append(draw_dopesheet_button)


def unregister():
    bpy.types.DOPESHEET_HT_header.remove(draw_dopesheet_button)
    bpy.types.VIEW3D_HT_tool_header.remove(draw_anim_toolbar)
    _state["on"] = False
    if _state["registered"]:
        try:
            bpy.utils.unregister_tool(RBLX_TL_animate)
        except Exception:
            pass
        _state["registered"] = False
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
