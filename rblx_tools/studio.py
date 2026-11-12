"""Roblox Studio controls for Build Mode.

Camera (like Studio):
* W A S D move, Q / E down / up, Shift slows down. Scroll while moving
  changes the camera speed.
* Hold right mouse to look around (WASD keeps working); a right click that
  doesn't move opens Blender's context menu.
* Middle mouse pans, scroll zooms toward the cursor, F focuses the selection.

Shortcuts: Ctrl+D duplicate, Ctrl+G group as Model, Ctrl+U ungroup,
Ctrl+R rotate / Ctrl+T tilt 90 degrees, Delete / Backspace delete, Ctrl+Y redo
(plus Ctrl+1-4 tools and Ctrl+L local/world from build.py).

These keys live in the Roblox tools' keymap, so they only apply while Build
Mode is on and a Roblox tool is active.

The Studio-style toolbar is drawn at the top of the 3D View (the tool
settings bar) while Build Mode is on."""

import math
import time

import bpy
from bpy.props import BoolProperty, IntProperty
from mathutils import Matrix, Quaternion, Vector

from . import build, coords, prefs

MOVE_KEYS = {"W": (0, 0, -1), "S": (0, 0, 1), "A": (-1, 0, 0), "D": (1, 0, 0)}
VERTICAL_KEYS = {"E": 1.0, "Q": -1.0}
LOOK_SENSITIVITY = 0.0045  # radians per pixel
SPEED_STEP = 1.25
MIN_SPEED, MAX_SPEED = 0.5, 2000.0


def camera_enabled():
    p = prefs.get()
    return getattr(p, "studio_camera", True) if p is not None else True


def _speed_get():
    p = prefs.get()
    return getattr(p, "camera_speed", 20.0) if p is not None else _fallback["speed"]


def _speed_set(v):
    v = max(MIN_SPEED, min(MAX_SPEED, v))
    p = prefs.get()
    if p is not None and hasattr(p, "camera_speed"):
        p.camera_speed = v
    _fallback["speed"] = v


_fallback = {"speed": 20.0}


def _eye(rv3d):
    return rv3d.view_location + rv3d.view_rotation @ Vector((0.0, 0.0, rv3d.view_distance))


def _ensure_perspective(rv3d):
    if rv3d.view_perspective != "PERSP":
        rv3d.view_perspective = "PERSP"


def move_view(rv3d, delta):
    rv3d.view_location = rv3d.view_location + delta


def look(rv3d, dx, dy):
    """Turn the camera in place (yaw around world up, pitch around its own X)."""
    eye = _eye(rv3d)
    rot = rv3d.view_rotation.copy()
    yaw = Quaternion((0.0, 0.0, 1.0), -dx * LOOK_SENSITIVITY)
    new = yaw @ rot
    pitch = Quaternion(new @ Vector((1.0, 0.0, 0.0)), dy * LOOK_SENSITIVITY)
    pitched = pitch @ new
    fwd = pitched @ Vector((0.0, 0.0, -1.0))
    if abs(fwd.z) < 0.995:  # don't flip over the top
        new = pitched
    new.normalize()
    rv3d.view_rotation = new
    rv3d.view_location = eye - new @ Vector((0.0, 0.0, rv3d.view_distance))


class RBLX_OT_studio_camera(bpy.types.Operator):
    """Roblox Studio camera: WASD/QE to move (Shift slower, scroll changes speed),
    hold right mouse to look around"""
    bl_idname = "rblx.studio_camera"
    bl_label = "Studio Camera"
    bl_options = {"BLOCKING"}

    look: BoolProperty(name="Look", default=False, options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == "VIEW_3D"
                and context.region_data is not None)

    def invoke(self, context, event):
        if not camera_enabled():
            return {"PASS_THROUGH"}
        self.rv3d = context.region_data
        self.keys = set()
        self.looking = False
        self.moved_look = 0.0
        self.shift = event.shift
        if self.look:
            self.start_look(context, event)
        elif event.type in MOVE_KEYS or event.type in VERTICAL_KEYS:
            self.keys.add(event.type)
        else:
            return {"PASS_THROUGH"}
        self.last_time = time.perf_counter()
        self.timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.status(context)
        return {"RUNNING_MODAL"}

    # -- helpers ----------------------------------------------------------
    def status(self, context):
        text = "Camera speed %.1f studs/s  (scroll: faster/slower, Shift: slow)" % _speed_get()
        if context.area is not None:
            context.area.header_text_set(text)

    def start_look(self, context, event):
        self.looking = True
        self.moved_look = 0.0
        self.center = (event.mouse_x, event.mouse_y)
        self.center_region = (event.mouse_region_x, event.mouse_region_y)
        _ensure_perspective(self.rv3d)
        try:
            context.window.cursor_modal_set("NONE")
        except (AttributeError, TypeError):
            pass

    def stop_look(self, context):
        self.looking = False
        try:
            context.window.cursor_modal_restore()
            context.window.cursor_warp(*self.center)
        except (AttributeError, TypeError):
            pass

    def finish(self, context):
        if self.looking:
            self.stop_look(context)
        context.window_manager.event_timer_remove(self.timer)
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def step(self, context):
        now = time.perf_counter()
        dt = min(now - self.last_time, 0.1)
        self.last_time = now
        if not self.keys:
            return
        _ensure_perspective(self.rv3d)
        local = Vector((0.0, 0.0, 0.0))
        for k in self.keys:
            if k in MOVE_KEYS:
                local += Vector(MOVE_KEYS[k])
        world = self.rv3d.view_rotation @ local
        for k in self.keys:
            if k in VERTICAL_KEYS:
                world.z += VERTICAL_KEYS[k]
        if world.length < 1e-6:
            return
        speed = _speed_get() * coords.stud_scale(context.scene) * (0.25 if self.shift else 1.0)
        move_view(self.rv3d, world.normalized() * speed * dt)

    # -- events -----------------------------------------------------------
    def modal(self, context, event):
        t, v = event.type, event.value
        if t in {"LEFT_SHIFT", "RIGHT_SHIFT"}:
            self.shift = v == "PRESS"
            return {"RUNNING_MODAL"}
        if t == "TIMER":
            self.step(context)
            return {"PASS_THROUGH"}
        if (t in MOVE_KEYS or t in VERTICAL_KEYS) and not (event.ctrl or event.alt or event.oskey):
            if v == "PRESS":
                self.keys.add(t)
            elif v == "RELEASE":
                self.keys.discard(t)
            return self.check_done(context)
        if t in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            _speed_set(_speed_get() * (SPEED_STEP if t == "WHEELUPMOUSE" else 1.0 / SPEED_STEP))
            self.status(context)
            return {"RUNNING_MODAL"}
        if t == "RIGHTMOUSE":
            if v == "PRESS" and not self.looking:
                self.start_look(context, event)
            elif v == "RELEASE" and self.looking:
                moved = self.moved_look
                self.stop_look(context)
                if moved < 4 and not self.keys:
                    self.finish(context)
                    try:
                        bpy.ops.wm.call_menu(name="VIEW3D_MT_object_context_menu")
                    except RuntimeError:
                        pass
                    return {"FINISHED"}
                return self.check_done(context)
            return {"RUNNING_MODAL"}
        if t == "MOUSEMOVE" and self.looking:
            dx = event.mouse_x - self.center[0]
            dy = event.mouse_y - self.center[1]
            if dx or dy:
                self.moved_look += abs(dx) + abs(dy)
                look(self.rv3d, dx, dy)
                try:
                    context.window.cursor_warp(*self.center)
                except (AttributeError, TypeError):
                    pass
            return {"RUNNING_MODAL"}
        if t in {"ESC", "WINDOW_DEACTIVATE"}:
            self.finish(context)
            return {"FINISHED"}
        return {"PASS_THROUGH"}

    def check_done(self, context):
        if not self.keys and not self.looking:
            self.finish(context)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class RBLX_OT_studio_zoom(bpy.types.Operator):
    """Zoom toward the mouse, like Roblox Studio's scroll wheel"""
    bl_idname = "rblx.studio_zoom"
    bl_label = "Studio Zoom"

    direction: IntProperty(default=1, options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def invoke(self, context, event):
        if not camera_enabled():
            return {"PASS_THROUGH"}
        rv3d = context.region_data
        if rv3d.view_perspective == "ORTHO" or rv3d.view_perspective == "CAMERA":
            return {"PASS_THROUGH"}  # Blender's own zoom suits orthographic/camera views
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin, direction = build.mouse_ray(context, coord)
        eye = _eye(rv3d)
        hit = build.ray_cast(context, eye, direction)
        scale = coords.stud_scale(context.scene)
        dist = (hit[0] - eye).length if hit is not None else rv3d.view_distance
        step = max(dist * 0.15, 0.5 * scale)
        if self.direction > 0 and hit is not None:
            step = min(step, max(dist - 0.5 * scale, 0.0))
        move_view(rv3d, direction * step * (1 if self.direction > 0 else -1))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Studio shortcuts

def _roots(context):
    return build.moving_roots(context.selected_objects)


class RBLX_OT_rotate_selection(bpy.types.Operator):
    """Rotate the selection 90 degrees (Ctrl+R) or tilt it (Ctrl+T), like Roblox Studio"""
    bl_idname = "rblx.rotate_selection"
    bl_label = "Rotate 90°"
    bl_options = {"REGISTER", "UNDO"}

    tilt: BoolProperty(name="Tilt", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        frame = build.handle_frame(context, local=False)
        if frame is None:
            return {"CANCELLED"}
        center = frame[0]
        if self.tilt:
            rv3d = context.region_data
            right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))) if rv3d else Vector((1, 0, 0))
            axis = Vector((1.0, 0.0, 0.0)) if abs(right.x) >= abs(right.y) else Vector((0.0, 1.0, 0.0))
        else:
            axis = Vector((0.0, 0.0, 1.0))
        m = (Matrix.Translation(center) @ Matrix.Rotation(math.radians(90.0), 4, axis) @
             Matrix.Translation(-center))
        for o in _roots(context):
            o.matrix_world = m @ o.matrix_world
        return {"FINISHED"}


class RBLX_OT_group_model(bpy.types.Operator):
    """Group the selection into a new Model (Ctrl+G, like Roblox Studio)"""
    bl_idname = "rblx.group_model"
    bl_label = "Group as Model"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        roots = _roots(context)
        mn, mx = build.bounds(build.world_points(roots))
        model = bpy.data.objects.new("Model", None)
        model.empty_display_type = "CUBE"
        model.empty_display_size = 0.5 * coords.stud_scale(context.scene)
        model.rblx.kind, model.rblx.class_name = "MODEL", "Model"
        coll = roots[0].users_collection[0] if roots[0].users_collection else context.collection
        coll.objects.link(model)
        model.location = (mn + mx) / 2.0
        common_parent = roots[0].parent if all(r.parent == roots[0].parent for r in roots) else None
        if common_parent is not None and roots[0].parent_type == "OBJECT":
            mw = model.matrix_world.copy()
            model.parent = common_parent
            model.matrix_world = mw
        context.view_layer.update()
        for r in roots:
            mw = r.matrix_world.copy()
            r.parent = model
            r.parent_type = "OBJECT"
            r.matrix_world = mw
        for o in context.selected_objects:
            o.select_set(False)
        build.select_target(model, True)
        context.view_layer.objects.active = model
        return {"FINISHED"}


class RBLX_OT_ungroup_model(bpy.types.Operator):
    """Ungroup the selected Models, keeping their contents (Ctrl+U, like Roblox Studio)"""
    bl_idname = "rblx.ungroup_model"
    bl_label = "Ungroup"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(
            o.type == "EMPTY" and o.rblx.kind == "MODEL" for o in context.selected_objects)

    def execute(self, context):
        models = [o for o in context.selected_objects if o.type == "EMPTY" and o.rblx.kind == "MODEL"]
        freed = []
        for model in models:
            for child in list(model.children):
                mw = child.matrix_world.copy()
                child.parent = model.parent
                child.matrix_world = mw
                freed.append(child)
            bpy.data.objects.remove(model)
        for o in context.selected_objects:
            o.select_set(False)
        for c in freed:
            build.select_target(c, True)
        if freed:
            context.view_layer.objects.active = freed[0]
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Studio-style toolbar (top of the 3D View while Build Mode is on)

RIBBON_PARTS = (
    ("BLOCK", "Block", "MESH_CUBE"),
    ("BALL", "Sphere", "MESH_UVSPHERE"),
    ("WEDGE", "Wedge", "MESH_CONE"),
    ("CORNER_WEDGE", "Corner", "MESH_CONE"),
    ("CYLINDER", "Cylinder", "MESH_CYLINDER"),
)

RIBBON_TOOLS = (
    (build.TOOL_SELECT, "Select", "RESTRICT_SELECT_OFF"),
    (build.TOOL_MOVE, "Move", "EMPTY_ARROWS"),
    (build.TOOL_SCALE, "Scale", "FULLSCREEN_ENTER"),
    (build.TOOL_ROTATE, "Rotate", "FILE_REFRESH"),
)


def draw_ribbon(self, context):
    if not build.is_on() or context.mode != "OBJECT":
        return
    layout = self.layout
    try:
        active_tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        active_id = active_tool.idname if active_tool else ""
    except (AttributeError, TypeError):
        active_id = ""

    # Insert parts with one click (they land in the middle of the view)
    row = layout.row(align=True)
    for shape, label, icon in RIBBON_PARTS:
        row.operator("rblx.add_part", text=label, icon=icon).shape = shape
    layout.separator()

    row = layout.row(align=True)
    for ident, label, icon in RIBBON_TOOLS:
        op = row.operator("wm.tool_set_by_id", text="", icon=icon, depress=active_id == ident)
        op.name = ident
        op.space_type = "VIEW_3D"

    s = context.scene.rblx
    for toggle, value, label in (("snap_move", "move_increment", "Move"),
                                 ("snap_rotate", "rotate_increment", "Rotate")):
        row = layout.row(align=True)
        row.prop(s, toggle, text="", icon="SNAP_INCREMENT")
        sub = row.row(align=True)
        sub.active = getattr(s, toggle)
        sub.ui_units_x = 5.5
        sub.prop(s, value, text=label)
    layout.prop(s, "handle_space", text="", icon_only=True)

    layout.separator()
    obj = context.active_object
    if obj is not None and obj.rblx.kind == "PART" and obj.select_get():
        r = obj.rblx
        sub = layout.row(align=True)
        sub.ui_units_x = 5.5
        sub.prop(r, "material", text="", icon="MATERIAL")
        sub = layout.row(align=True)
        sub.ui_units_x = 2.5
        sub.prop(r, "color", text="")
        row = layout.row(align=True)
        row.prop(r, "anchored", text="", icon="PINNED" if r.anchored else "UNPINNED", toggle=True)
        row.prop(r, "locked", text="", icon="LOCKED" if r.locked else "UNLOCKED", toggle=True)
    row = layout.row(align=True)
    row.operator("rblx.group_model", text="", icon="OUTLINER_OB_EMPTY")
    row.operator("rblx.ungroup_model", text="", icon="X")
    layout.separator()


CLASSES = (
    RBLX_OT_studio_camera,
    RBLX_OT_studio_zoom,
    RBLX_OT_rotate_selection,
    RBLX_OT_group_model,
    RBLX_OT_ungroup_model,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_HT_tool_header.prepend(draw_ribbon)


def unregister():
    bpy.types.VIEW3D_HT_tool_header.remove(draw_ribbon)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
