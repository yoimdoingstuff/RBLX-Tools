"""Studio-style Build Mode.

A toggle (3D View header > Build, or the Roblox panel) that adds four tools to
the 3D View toolbar, like Roblox Studio's Select / Move / Scale / Rotate:

* Click a part to select it (the whole Model, like Studio; Alt picks the part
  itself). Click-drag to slide it over other surfaces, snapped to the grid.
  While dragging, R rotates and T tilts by 90 degrees.
* Move: arrow handles move along an axis in Move-increment steps.
* Scale: ball handles resize one face of a part (Ctrl: both sides).
* Rotate: rings rotate in Rotate-increment steps.

Turning Build Mode off removes the tools again, so Blender works as usual."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from . import coords
from .props import no_propagation

TOOL_SELECT = "rblx.tool_select"
TOOL_MOVE = "rblx.tool_move"
TOOL_SCALE = "rblx.tool_scale"
TOOL_ROTATE = "rblx.tool_rotate"
TOOL_IDS = (TOOL_SELECT, TOOL_MOVE, TOOL_SCALE, TOOL_ROTATE)

# Containers that clicking doesn't select as a whole (Studio skips Folders)
TRANSPARENT_CONTAINERS = {"Folder", "Workspace", "ReplicatedStorage", "ServerStorage",
                          "StarterPack", "Configuration"}
GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}

# Handle colours by Roblox axis: X red, Y (up) green, Z blue.
# Blender axis index -> colour (Blender X = Roblox X, Y = Roblox Z, Z = Roblox Y)
AXIS_COLORS = {0: (0.95, 0.25, 0.2), 1: (0.2, 0.45, 1.0), 2: (0.3, 0.85, 0.25)}
BL_TO_RBX_SIZE = {0: 0, 1: 2, 2: 1}  # Blender local axis -> Roblox Size component

_state = {"on": False, "registered": []}
# Latest handle gizmos per mode (lets tests find them on screen)
LAST_HANDLES = {}


def is_on():
    return _state["on"]


# ---------------------------------------------------------------------------
# Helpers

def scene_settings(context):
    return context.scene.rblx


def move_step(context):
    """Grid step in Blender units, or 0 when move snapping is off."""
    s = scene_settings(context)
    return s.move_increment * coords.stud_scale(context.scene) if s.snap_move else 0.0


def snap(value, step):
    return round(value / step) * step if step > 0 else value


def pick_target(obj, part_only=False):
    """What clicking `obj` selects: the top-most Model it's in (like Studio),
    or the part itself."""
    if part_only:
        return obj
    target = obj
    o = obj.parent
    while o is not None:
        if o.rblx.kind == "MODEL" and o.rblx.class_name not in TRANSPARENT_CONTAINERS:
            target = o
        o = o.parent
    return target


def select_target(target, state=True):
    for o in (target, *target.children_recursive):
        if o.visible_get():
            o.select_set(state)


def moving_roots(objects):
    """Selected objects whose parents aren't also selected."""
    sel = set(objects)
    roots = []
    for o in objects:
        p = o.parent
        while p is not None and p not in sel:
            p = p.parent
        if p is None:
            roots.append(o)
    return roots


def world_points(roots):
    pts = []
    for root in roots:
        for o in (root, *root.children_recursive):
            if o.type in GEOMETRY_TYPES and o.visible_get():
                mw = o.matrix_world
                pts.extend(mw @ Vector(c) for c in o.bound_box)
    if not pts:
        pts = [r.matrix_world.translation.copy() for r in roots]
    return pts


def bounds(pts):
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def mouse_ray(context, coord):
    region, rv3d = context.region, context.region_data
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction.normalized()


def ray_cast(context, origin, direction, exclude=(), skip_locked=False):
    """First hit that isn't in `exclude` (and isn't Locked, if asked)."""
    depsgraph = context.evaluated_depsgraph_get()
    o = origin.copy()
    for _ in range(64):
        hit, loc, nrm, _i, obj, _m = context.scene.ray_cast(depsgraph, o, direction)
        if not hit or obj is None:
            return None
        orig = obj.original
        if orig in exclude or (skip_locked and orig.rblx.locked):
            o = loc + direction * 1e-4
            continue
        return loc, nrm.normalized(), orig
    return None


def line_param(origin, direction, point, axis):
    """Parameter t of the point on the line point + axis*t closest to the ray."""
    w0 = point - origin
    b = axis.dot(direction)
    den = 1.0 - b * b
    if den < 1e-5:
        return None
    d = axis.dot(w0)
    e = direction.dot(w0)
    return (b * e - d) / den


def orthonormal(m3):
    return m3.to_quaternion().to_matrix()


def handle_frame(context, local=None):
    """(centre, 3x3 axes, half extents along those axes) for the selection."""
    s = scene_settings(context)
    roots = moving_roots(context.selected_objects)
    if not roots:
        return None
    active = context.active_object
    if active is not None and active not in context.selected_objects:
        active = roots[0]
    active = active or roots[0]
    if local is None:
        local = s.handle_space == "LOCAL"
    axes = orthonormal(active.matrix_world.to_3x3()) if local else Matrix.Identity(3)
    pts = world_points(roots)
    inv = axes.transposed()
    lp = [inv @ p for p in pts]
    mn, mx = bounds(lp)
    center = axes @ ((mn + mx) / 2.0)
    if len(roots) == 1 and roots[0].rblx.kind == "PART":
        center = roots[0].matrix_world.translation.copy()
        lc = inv @ center
        half = Vector(max(abs(mx[i] - lc[i]), abs(lc[i] - mn[i])) for i in range(3))
    else:
        half = (mx - mn) / 2.0
    return center, axes, half


def _view3d(context):
    """(area, window region, RegionView3D) of the 3D View to use, even when
    called from a header button or the Properties Editor."""
    areas = [context.area] if context.area is not None else []
    if context.screen is not None:
        areas += list(context.screen.areas)
    for area in areas:
        if area is not None and area.type == "VIEW_3D":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                return area, region, area.spaces.active.region_3d
    return None


def place_in_view(context, objects):
    """Put new objects where Studio inserts parts: on the surface in the middle
    of the view (or in front of the camera), with the corner on the grid."""
    found = _view3d(context)
    if found is None or not objects:
        return False
    _area, region, rv3d = found
    roots = moving_roots(objects)
    context.view_layer.update()
    pts = world_points(roots)
    mn, mx = bounds(pts)
    c0 = (mn + mx) / 2.0
    half = (mx - mn) / 2.0
    start = {o: o.matrix_world.copy() for o in roots}
    park = Matrix.Translation((0.0, 0.0, -1.0e6))
    for o, m0 in start.items():
        o.matrix_world = park @ m0
    coord = (region.width / 2.0, region.height / 2.0)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    hit = ray_cast(context, origin, direction, exclude=set(roots))
    if hit is not None and (hit[0] - origin).length < 2000.0 * coords.stud_scale(context.scene):
        loc, n, _obj = hit
        k = max(range(3), key=lambda i: abs(n[i]))
        target = loc.copy()
        target[k] = loc[k] + (1.0 if n[k] > 0 else -1.0) * half[k]
        free = [j for j in range(3) if j != k]
    else:
        target = rv3d.view_location.copy()
        free = [0, 1, 2]
    step = move_step(context)
    for j in free:
        target[j] = snap(target[j] - half[j], step) + half[j]
    move = Matrix.Translation(target - c0)
    for o, m0 in start.items():
        o.matrix_world = move @ m0
    return True


def _status(context, text):
    try:
        context.workspace.status_text_set(text)
    except AttributeError:
        pass
    if context.area is not None:
        context.area.header_text_set(text)


# ---------------------------------------------------------------------------
# Click / drag (all four tools)

class RBLX_OT_build_click(bpy.types.Operator):
    """Click to select a part (or its Model); drag to move it over other surfaces, snapped
    to the grid. While dragging: R rotates, T tilts"""
    bl_idname = "rblx.build_click"
    bl_label = "Roblox Select / Drag"
    bl_options = {"REGISTER", "UNDO"}

    extend: BoolProperty(name="Extend", default=False, options={"SKIP_SAVE"},
                         description="Add to / remove from the selection (Shift or Ctrl)")
    part_only: BoolProperty(name="Part Only", default=False, options={"SKIP_SAVE"},
                            description="Select the part itself, not its Model (Alt)")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and context.mode == "OBJECT"

    def invoke(self, context, event):
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin, direction = mouse_ray(context, coord)
        hit = ray_cast(context, origin, direction, skip_locked=True)
        if hit is None:
            if not self.extend:
                for o in context.selected_objects:
                    o.select_set(False)
            try:
                bpy.ops.view3d.select_box("INVOKE_DEFAULT", wait_for_input=False,
                                          mode="ADD" if self.extend else "SET")
            except (RuntimeError, TypeError):
                pass
            return {"FINISHED"}

        loc, _n, obj = hit
        target = pick_target(obj, self.part_only)
        self.target_name = target.name
        if self.extend:
            if target.select_get():
                select_target(target, False)
                return {"FINISHED"}
            select_target(target, True)
        elif not target.select_get():
            for o in context.selected_objects:
                o.select_set(False)
            select_target(target, True)
        context.view_layer.objects.active = target

        self.press = coord
        self.last = coord
        self.grab = loc.copy()
        self.dragging = False
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # -- drag -----------------------------------------------------------
    def start_drag(self, context):
        self.roots = moving_roots(context.selected_objects)
        if not self.roots:
            return False
        self.exclude = set()
        for r in self.roots:
            self.exclude.add(r)
            self.exclude.update(r.children_recursive)
        self.start = {o: o.matrix_world.copy() for o in self.roots}
        pts = world_points(self.roots)
        mn, mx = bounds(pts)
        self.c0 = (mn + mx) / 2.0
        self.rel = [p - self.c0 for p in pts]
        self.rot = Matrix.Identity(3)
        self.grab_off = self.grab - self.c0
        self.plane_z = self.grab.z
        self.dragging = True
        _status(context, "Drag: R rotate, T tilt, Esc / right-click cancel")
        return True

    def update_drag(self, context):
        origin, direction = mouse_ray(context, self.last)
        rel = [self.rot @ p for p in self.rel]
        mn, mx = bounds(rel)
        half = (mx - mn) / 2.0
        mid = (mx + mn) / 2.0
        off = self.rot @ self.grab_off
        step = move_step(context)

        # Park the dragged objects out of the way while casting: stepping past
        # their faces would also skip surfaces they sit flush on.
        park = Matrix.Translation((0.0, 0.0, -1.0e6))
        for o, m0 in self.start.items():
            o.matrix_world = park @ m0
        hit = ray_cast(context, origin, direction, exclude=self.exclude)
        if hit is not None:
            loc, n, _obj = hit
            k = max(range(3), key=lambda i: abs(n[i]))
            s = 1.0 if n[k] > 0 else -1.0
            pivot = loc - off
            pivot[k] = loc[k] + s * half[k] - mid[k]
            free = [j for j in range(3) if j != k]
        else:
            t = (self.plane_z - origin.z) / direction.z if abs(direction.z) > 1e-6 else -1.0
            if t < 0:  # looking away from the drag plane: stay where we were
                m = getattr(self, "current", None) or Matrix.Identity(4)
                for o, m0 in self.start.items():
                    o.matrix_world = m @ m0
                return
            pivot = origin + direction * t - off
            pivot.z = self.c0.z
            free = [0, 1]
        for j in free:  # snap the box's corner to the grid, like Studio
            pivot[j] = snap(pivot[j] + mn[j], step) - mn[j]

        m = Matrix.Translation(pivot) @ self.rot.to_4x4() @ Matrix.Translation(-self.c0)
        self.current = m
        for o, m0 in self.start.items():
            o.matrix_world = m @ m0

    def rotate(self, context, axis):
        self.rot = Matrix.Rotation(math.radians(90.0), 3, axis) @ self.rot
        self.update_drag(context)

    def restore(self):
        for o, m0 in getattr(self, "start", {}).items():
            o.matrix_world = m0

    def finish(self, context):
        _status(context, None)

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN",
                          "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}
        if event.type == "MOUSEMOVE":
            self.last = (event.mouse_region_x, event.mouse_region_y)
            if not self.dragging:
                thr = context.preferences.inputs.drag_threshold_mouse
                if (abs(self.last[0] - self.press[0]) > thr or
                        abs(self.last[1] - self.press[1]) > thr):
                    if not self.start_drag(context):
                        return {"FINISHED"}
            if self.dragging:
                self.update_drag(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if not self.dragging and not self.extend:
                # a plain click on an already-selected part selects just that
                target = bpy.data.objects.get(self.target_name)
                if target is not None:
                    for o in context.selected_objects:
                        o.select_set(False)
                    select_target(target, True)
                    context.view_layer.objects.active = target
            self.finish(context)
            return {"FINISHED"}
        if self.dragging and event.value == "PRESS":
            if event.type == "R":
                self.rotate(context, Vector((0.0, 0.0, 1.0)))
                return {"RUNNING_MODAL"}
            if event.type == "T":
                right = context.region_data.view_rotation @ Vector((1.0, 0.0, 0.0))
                axis = Vector((1.0, 0.0, 0.0)) if abs(right.x) >= abs(right.y) else Vector((0.0, 1.0, 0.0))
                self.rotate(context, axis)
                return {"RUNNING_MODAL"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.restore()
            self.finish(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


# ---------------------------------------------------------------------------
# Handles (Move / Scale / Rotate)

class RBLX_OT_handle_drag(bpy.types.Operator):
    """Drag a Studio-style handle"""
    bl_idname = "rblx.handle_drag"
    bl_label = "Roblox Handle"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    mode: EnumProperty(items=[("MOVE", "Move", ""), ("SCALE", "Scale", ""),
                              ("ROTATE", "Rotate", "")], default="MOVE")
    axis: IntProperty(min=0, max=2, default=0)
    sign: IntProperty(default=1)

    def invoke(self, context, event):
        if context.region_data is None:
            return {"CANCELLED"}
        frame = handle_frame(context, local=True if self.mode == "SCALE" else None)
        if frame is None:
            return {"CANCELLED"}
        self.center, axes, half = frame
        self.dir = axes.col[self.axis].normalized() * (1.0 if self.sign >= 0 else -1.0)
        self.half = half[self.axis]
        self.roots = moving_roots(context.selected_objects)
        self.start = {o: o.matrix_world.copy() for o in self.roots}
        self.value = 0.0
        coord = (event.mouse_region_x, event.mouse_region_y)

        if self.mode == "SCALE":
            self.objects = [o for o in context.selected_objects
                            if o.type == "MESH" and (o.rblx.kind == "PART" or o.rblx.kind == "NONE")]
            if not self.objects:
                self.report({"INFO"}, "Scale handles resize parts and meshes")
                return {"CANCELLED"}
            self.start = {o: o.matrix_world.copy() for o in self.objects}
            self.sizes = {o: (tuple(o.rblx.size) if o.rblx.kind == "PART" else tuple(o.dimensions))
                          for o in self.objects}
            self.anchor = self.center + self.dir * self.half
        else:
            self.anchor = self.center
        if self.mode == "ROTATE":
            c2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data,
                                                        self.center)
            if c2d is None:
                return {"CANCELLED"}
            self.c2d = c2d
            # Follow the cursor on the ring's plane; when the ring is seen
            # edge-on, use the angle around its centre on screen instead.
            view = context.region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
            self.planar = abs(view.dot(self.dir)) > 0.2
            self.b1 = self.dir.orthogonal().normalized()
            self.b2 = self.dir.cross(self.b1)
            self.prev = self.cursor_angle(context, coord)
            if self.prev is None:
                return {"CANCELLED"}
            self.total = 0.0
        else:
            t = line_param(*mouse_ray(context, coord), self.anchor, self.dir)
            if t is None:
                return {"CANCELLED"}
            self.t0 = t
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def apply(self, context, event):
        s = scene_settings(context)
        scale = coords.stud_scale(context.scene)
        coord = (event.mouse_region_x, event.mouse_region_y)
        if self.mode == "ROTATE":
            ang = self.cursor_angle(context, coord)
            if ang is None:
                return
            d = ang - self.prev
            d = (d + math.pi) % (2 * math.pi) - math.pi
            self.prev = ang
            self.total += d
            if self.planar:
                angle = self.total
            else:
                view = context.region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
                angle = self.total if self.dir.dot(view) < 0 else -self.total
            step = math.radians(s.rotate_increment) if s.snap_rotate else 0.0
            angle = snap(angle, step)
            self.value = math.degrees(angle)
            m = (Matrix.Translation(self.center) @ Matrix.Rotation(angle, 4, self.dir) @
                 Matrix.Translation(-self.center))
            for o, m0 in self.start.items():
                o.matrix_world = m @ m0
            _status(context, "Rotate %.1f°" % self.value)
            return
        t = line_param(*mouse_ray(context, coord), self.anchor, self.dir)
        if t is None:
            return
        delta = t - self.t0
        if self.mode == "MOVE":
            delta = snap(delta, move_step(context))
            self.value = delta / scale
            m = Matrix.Translation(self.dir * delta)
            for o, m0 in self.start.items():
                o.matrix_world = m @ m0
            _status(context, "Move %.3g studs" % self.value)
            return
        # SCALE: resize along the face, keeping the opposite face in place
        studs = delta / scale
        if s.snap_move:
            studs = snap(studs, s.move_increment)
        both = event.ctrl
        self.value = studs
        self.resize(context, studs * (2.0 if both else 1.0), both)
        _status(context, "Resize %+.3g studs%s" % (self.value, " (both sides)" if both else ""))

    def cursor_angle(self, context, coord):
        if not self.planar:
            return math.atan2(coord[1] - self.c2d.y, coord[0] - self.c2d.x)
        origin, direction = mouse_ray(context, coord)
        den = direction.dot(self.dir)
        if abs(den) < 1e-6:
            return None
        p = origin + direction * ((self.center - origin).dot(self.dir) / den)
        v = p - self.center
        return math.atan2(v.dot(self.b2), v.dot(self.b1))

    def resize(self, context, studs, both):
        scale = coords.stud_scale(context.scene)
        with no_propagation():
            for o in self.objects:
                m0 = self.start[o]
                rot = orthonormal(m0.to_3x3())
                j = max(range(3), key=lambda i: abs(rot.col[i].dot(self.dir)))
                sgn = 1.0 if rot.col[j].dot(self.dir) >= 0 else -1.0
                size0 = self.sizes[o]
                if o.rblx.kind == "PART":
                    c = BL_TO_RBX_SIZE[j]
                    new = list(size0)
                    new[c] = max(0.05, size0[c] + studs)
                    change = (new[c] - size0[c]) * scale
                    o.rblx.size = new
                else:
                    new = list(size0)
                    new[j] = max(0.05 * scale, size0[j] + studs * scale)
                    change = new[j] - size0[j]
                    o.dimensions = new
                mw = o.matrix_world.copy()
                mw.translation = m0.translation + (Vector((0, 0, 0)) if both else
                                                   rot.col[j] * sgn * change / 2.0)
                o.matrix_world = mw

    def restore(self):
        if self.mode == "SCALE":
            with no_propagation():
                for o in self.objects:
                    if o.rblx.kind == "PART":
                        o.rblx.size = self.sizes[o]
                    else:
                        o.dimensions = self.sizes[o]
        for o, m0 in self.start.items():
            o.matrix_world = m0

    def modal(self, context, event):
        if event.type == "MOUSEMOVE" or (self.mode == "SCALE" and event.type in
                                         {"LEFT_CTRL", "RIGHT_CTRL"}):
            self.apply(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            _status(context, None)
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.restore()
            _status(context, None)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class _HandleGroup:
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}
    tool_id = ""
    mode = "MOVE"

    @classmethod
    def poll(cls, context):
        if not _state["on"] or context.mode != "OBJECT" or not context.selected_objects:
            return False
        try:
            tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        except (AttributeError, TypeError):
            return False
        return tool is not None and tool.idname == cls.tool_id

    def _new(self, kind, axis, sign):
        gz = self.gizmos.new(kind)
        props = gz.target_set_operator("rblx.handle_drag")
        props.mode = self.mode
        props.axis = axis
        props.sign = sign
        gz.color = AXIS_COLORS[axis]
        gz.alpha = 0.85
        gz.color_highlight = tuple(min(1.0, c + 0.3) for c in AXIS_COLORS[axis])
        gz.alpha_highlight = 1.0
        return gz


def _track(direction, location):
    m = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
    m.translation = location
    return m


class RBLX_GGT_move(_HandleGroup, bpy.types.GizmoGroup):
    bl_idname = "RBLX_GGT_move"
    bl_label = "Roblox Move Handles"
    tool_id = TOOL_MOVE
    mode = "MOVE"

    def setup(self, context):
        self.handles = []
        for axis in range(3):
            for sign in (1, -1):
                gz = self._new("GIZMO_GT_arrow_3d", axis, sign)
                gz.line_width = 3.0
                gz.length = 0.6
                self.handles.append((gz, axis, sign))

    def draw_prepare(self, context):
        LAST_HANDLES[self.mode] = self.handles
        frame = handle_frame(context)
        if frame is None:
            return
        center, axes, half = frame
        margin = 0.25 * coords.stud_scale(context.scene)
        for gz, axis, sign in self.handles:
            d = axes.col[axis] * sign
            gz.matrix_basis = _track(d, center + d * (half[axis] + margin))


class RBLX_GGT_scale(_HandleGroup, bpy.types.GizmoGroup):
    bl_idname = "RBLX_GGT_scale"
    bl_label = "Roblox Scale Handles"
    tool_id = TOOL_SCALE
    mode = "SCALE"

    def setup(self, context):
        self.handles = []
        for axis in range(3):
            for sign in (1, -1):
                gz = self._new("GIZMO_GT_move_3d", axis, sign)
                gz.draw_style = "RING_2D"
                gz.draw_options = {"FILL", "ALIGN_VIEW"}
                gz.scale_basis = 0.065
                self.handles.append((gz, axis, sign))

    def draw_prepare(self, context):
        LAST_HANDLES[self.mode] = self.handles
        frame = handle_frame(context, local=True)
        if frame is None:
            return
        center, axes, half = frame
        margin = 0.35 * coords.stud_scale(context.scene)
        for gz, axis, sign in self.handles:
            d = axes.col[axis] * sign
            gz.matrix_basis = _track(d, center + d * (half[axis] + margin))


class RBLX_GGT_rotate(_HandleGroup, bpy.types.GizmoGroup):
    bl_idname = "RBLX_GGT_rotate"
    bl_label = "Roblox Rotate Handles"
    tool_id = TOOL_ROTATE
    mode = "ROTATE"

    def setup(self, context):
        self.handles = []
        for axis in range(3):
            gz = self._new("GIZMO_GT_dial_3d", axis, 1)
            gz.draw_options = {"CLIP"}
            gz.line_width = 3.0
            gz.use_draw_scale = False  # rings surround the part, like Studio
            self.handles.append((gz, axis, 1))

    def draw_prepare(self, context):
        LAST_HANDLES[self.mode] = self.handles
        frame = handle_frame(context)
        if frame is None:
            return
        center, axes, half = frame
        radius = max(half.length, 0.5 * coords.stud_scale(context.scene)) * 1.1
        for gz, axis, _sign in self.handles:
            gz.matrix_basis = _track(axes.col[axis], center) @ Matrix.Scale(radius, 4)


# ---------------------------------------------------------------------------
# Tools

def draw_snap_settings(layout, context, compact=False):
    s = scene_settings(context)
    row = layout.row(align=True)
    row.prop(s, "snap_move", text="", icon="SNAP_INCREMENT")
    sub = row.row(align=True)
    sub.active = s.snap_move
    sub.prop(s, "move_increment", text="Move")
    row = layout.row(align=True)
    row.prop(s, "snap_rotate", text="", icon="SNAP_INCREMENT")
    sub = row.row(align=True)
    sub.active = s.snap_rotate
    sub.prop(s, "rotate_increment", text="Rotate")
    if compact:
        layout.prop(s, "handle_space", text="")
    else:
        layout.row().prop(s, "handle_space", expand=True)


def _keymap(tool_id):
    km = [
        ("rblx.build_click", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
        ("rblx.build_click", {"type": "LEFTMOUSE", "value": "PRESS", "shift": True},
         {"properties": [("extend", True)]}),
        ("rblx.build_click", {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True},
         {"properties": [("extend", True)]}),
        ("rblx.build_click", {"type": "LEFTMOUSE", "value": "PRESS", "alt": True},
         {"properties": [("part_only", True)]}),
        ("rblx.build_click", {"type": "LEFTMOUSE", "value": "PRESS", "alt": True, "shift": True},
         {"properties": [("part_only", True), ("extend", True)]}),
        ("rblx.toggle_handle_space", {"type": "L", "value": "PRESS", "ctrl": True}, None),
    ]
    for key, ident in zip(("ONE", "TWO", "THREE", "FOUR"), TOOL_IDS):  # Studio: Ctrl+1..4
        km.append(("wm.tool_set_by_id", {"type": key, "value": "PRESS", "ctrl": True},
                   {"properties": [("name", ident)]}))
    return tuple(km + STUDIO_KEYS)


# Roblox Studio camera and shortcuts (operators in studio.py)
STUDIO_KEYS = [("rblx.studio_camera", {"type": k, "value": "PRESS", "shift": shift}, None)
               for k in ("W", "A", "S", "D", "Q", "E") for shift in (False, True)] + [
    ("rblx.studio_camera", {"type": "RIGHTMOUSE", "value": "PRESS"},
     {"properties": [("look", True)]}),
    ("view3d.move", {"type": "MIDDLEMOUSE", "value": "PRESS"}, None),
    ("view3d.rotate", {"type": "MIDDLEMOUSE", "value": "PRESS", "shift": True}, None),
    ("rblx.studio_zoom", {"type": "WHEELUPMOUSE", "value": "PRESS"},
     {"properties": [("direction", 1)]}),
    ("rblx.studio_zoom", {"type": "WHEELDOWNMOUSE", "value": "PRESS"},
     {"properties": [("direction", -1)]}),
    ("view3d.view_selected", {"type": "F", "value": "PRESS"}, None),
    ("object.duplicate", {"type": "D", "value": "PRESS", "ctrl": True}, None),
    ("rblx.group_model", {"type": "G", "value": "PRESS", "ctrl": True}, None),
    ("rblx.ungroup_model", {"type": "U", "value": "PRESS", "ctrl": True}, None),
    ("rblx.rotate_selection", {"type": "R", "value": "PRESS", "ctrl": True}, None),
    ("rblx.rotate_selection", {"type": "T", "value": "PRESS", "ctrl": True},
     {"properties": [("tilt", True)]}),
    ("object.delete", {"type": "DEL", "value": "PRESS"}, {"properties": [("confirm", False)]}),
    ("object.delete", {"type": "BACK_SPACE", "value": "PRESS"},
     {"properties": [("confirm", False)]}),
    ("ed.redo", {"type": "Y", "value": "PRESS", "ctrl": True}, None),
]


class _RobloxTool:
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"

    @staticmethod
    def draw_settings(context, layout, tool):
        if context.region is not None and context.region.type == "TOOL_HEADER" and is_on():
            return  # the Studio toolbar at the top already shows these
        s = scene_settings(context)
        for toggle, value, label in (("snap_move", "move_increment", "Move"),
                                     ("snap_rotate", "rotate_increment", "Rotate")):
            row = layout.row(align=True)
            row.prop(s, toggle, text="", icon="SNAP_INCREMENT")
            sub = row.row(align=True)
            sub.active = getattr(s, toggle)
            sub.prop(s, value, text=label)
        layout.prop(s, "handle_space", text="")


class RBLX_TL_select(_RobloxTool, bpy.types.WorkSpaceTool):
    bl_idname = TOOL_SELECT
    bl_label = "Roblox Select"
    bl_description = ("Click parts to select them, drag to move them over other surfaces "
                      "with grid snapping (Ctrl+1)")
    bl_icon = "ops.generic.select"
    bl_widget = None
    bl_keymap = _keymap(TOOL_SELECT)


class RBLX_TL_move(_RobloxTool, bpy.types.WorkSpaceTool):
    bl_idname = TOOL_MOVE
    bl_label = "Roblox Move"
    bl_description = "Studio-style Move handles (Ctrl+2)"
    bl_icon = "ops.transform.translate"
    bl_widget = None
    bl_keymap = _keymap(TOOL_MOVE)


class RBLX_TL_scale(_RobloxTool, bpy.types.WorkSpaceTool):
    bl_idname = TOOL_SCALE
    bl_label = "Roblox Scale"
    bl_description = "Studio-style Scale handles: resize one side of a part, Ctrl for both (Ctrl+3)"
    bl_icon = "ops.transform.resize"
    bl_widget = None
    bl_keymap = _keymap(TOOL_SCALE)


class RBLX_TL_rotate(_RobloxTool, bpy.types.WorkSpaceTool):
    bl_idname = TOOL_ROTATE
    bl_label = "Roblox Rotate"
    bl_description = "Studio-style Rotate handles (Ctrl+4)"
    bl_icon = "ops.transform.rotate"
    bl_widget = None
    bl_keymap = _keymap(TOOL_ROTATE)


TOOLS = (RBLX_TL_select, RBLX_TL_move, RBLX_TL_scale, RBLX_TL_rotate)


def _view3d_override(context):
    win = context.window or (context.window_manager.windows[0]
                             if context.window_manager.windows else None)
    if win is None:
        return None
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                return {"window": win, "area": area, "region": region}
    return None


def _set_tool(context, ident):
    ov = _view3d_override(context)
    if ov is None:
        return False
    try:
        with context.temp_override(**ov):
            bpy.ops.wm.tool_set_by_id(name=ident, space_type="VIEW_3D")
        return True
    except (RuntimeError, TypeError):
        return False


def _register_tools():
    if _state["registered"]:
        return
    prev = "builtin.transform"
    for i, tool in enumerate(TOOLS):
        try:
            bpy.utils.register_tool(tool, after={prev}, separator=(i == 0), group=False)
        except Exception:
            bpy.utils.register_tool(tool, separator=(i == 0), group=False)
        _state["registered"].append(tool)
        prev = tool.bl_idname


def _unregister_tools():
    for tool in reversed(_state["registered"]):
        try:
            bpy.utils.unregister_tool(tool)
        except Exception:
            pass
    _state["registered"].clear()


def set_build_mode(context, on):
    if on == _state["on"]:
        return
    if on:
        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                pass
        _register_tools()
        _state["on"] = True
        _set_tool(context, TOOL_SELECT)
        for win in context.window_manager.windows:  # the Studio toolbar lives in the tool header
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.show_region_tool_header = True
    else:
        _state["on"] = False
        try:
            tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        except (AttributeError, TypeError):
            tool = None
        if tool is not None and tool.idname in TOOL_IDS:
            _set_tool(context, "builtin.select_box")
        _unregister_tools()
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class RBLX_OT_toggle_build_mode(bpy.types.Operator):
    """Studio-style Build Mode: adds Roblox Select / Move / Scale / Rotate tools to the toolbar,
    with click-and-drag building and grid snapping. Click again to go back to Blender's tools"""
    bl_idname = "rblx.toggle_build_mode"
    bl_label = "Build Mode"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        set_build_mode(context, not _state["on"])
        self.report({"INFO"}, "Build Mode " + ("on" if _state["on"] else "off"))
        return {"FINISHED"}


class RBLX_OT_toggle_handle_space(bpy.types.Operator):
    """Switch the Move/Rotate handles between world and local axes (Ctrl+L, like Studio)"""
    bl_idname = "rblx.toggle_handle_space"
    bl_label = "Toggle Local/World Space"

    def execute(self, context):
        s = scene_settings(context)
        s.handle_space = "LOCAL" if s.handle_space == "WORLD" else "WORLD"
        return {"FINISHED"}


class RBLX_OT_stud_grid(bpy.types.Operator):
    """Make the viewport grid show studs (one square per Move increment)"""
    bl_idname = "rblx.stud_grid"
    bl_label = "Show Stud Grid"

    def execute(self, context):
        s = scene_settings(context)
        size = s.move_increment * coords.stud_scale(context.scene)
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                ov = area.spaces.active.overlay
                ov.grid_scale = size
                ov.grid_subdivisions = 1
                area.tag_redraw()
        return {"FINISHED"}


def draw_header_button(self, context):
    if context.mode not in ("OBJECT", "POSE", "EDIT_MESH"):
        return
    self.layout.operator(RBLX_OT_toggle_build_mode.bl_idname, text="Build",
                         icon="MOD_BUILD", depress=_state["on"])


CLASSES = (
    RBLX_OT_build_click,
    RBLX_OT_handle_drag,
    RBLX_GGT_move,
    RBLX_GGT_scale,
    RBLX_GGT_rotate,
    RBLX_OT_toggle_build_mode,
    RBLX_OT_toggle_handle_space,
    RBLX_OT_stud_grid,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_HT_header.append(draw_header_button)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_header_button)
    _state["on"] = False
    _unregister_tools()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
