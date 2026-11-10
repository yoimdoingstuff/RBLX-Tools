"""Builds Roblox-style part geometry (Block, Ball, Cylinder, Wedge, Head, ...).
Geometry is generated in Roblox local space and converted to Blender axes,
so a part's local axes match Roblox's."""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import coords

SEGMENTS = 32
BOX_SHAPES = {"BLOCK", "TRUSS", "WEDGE", "CORNER_WEDGE", "MESH", "UNION"}

# Roblox clothing template (585 x 559 px): face -> (x, y, w, h) in pixels.
# Faces are the part's own sides (LEFT = -X = the character's left).
TEMPLATE_SIZE = (585.0, 559.0)
TEMPLATE_RECTS = {
    "TORSO": {"TOP": (231, 8, 128, 64), "FRONT": (231, 74, 128, 128),
              "BOTTOM": (231, 204, 128, 64), "BACK": (427, 74, 128, 128),
              "LEFT": (361, 74, 64, 128), "RIGHT": (165, 74, 64, 128)},
    "RIGHT_LIMB": {"LEFT": (19, 355, 64, 128), "BACK": (85, 355, 64, 128),
                   "RIGHT": (151, 355, 64, 128), "FRONT": (217, 355, 64, 128),
                   "TOP": (217, 289, 64, 64), "BOTTOM": (217, 485, 64, 64)},
    "LEFT_LIMB": {"FRONT": (308, 355, 64, 128), "LEFT": (374, 355, 64, 128),
                  "BACK": (440, 355, 64, 128), "RIGHT": (506, 355, 64, 128),
                  "TOP": (308, 289, 64, 64), "BOTTOM": (308, 485, 64, 64)},
}


def _bl(p):
    """Roblox local -> Blender local (see coords.AXIS)."""
    return Vector((-p[0], p[2], p[1]))


def _rbx(v):
    """Blender local -> Roblox local."""
    return Vector((-v[0], v[2], v[1]))


def face_axes(face):
    """(normal, u, up) in Roblox space for an image on `face`, as seen from
    outside. Top/bottom are oriented so they join the front face edge the way
    Roblox's clothing template does."""
    n = Vector(coords.FACE_NORMALS[face])
    if face == "TOP":
        up = Vector((0.0, 0.0, 1.0))
    elif face == "BOTTOM":
        up = Vector((0.0, 0.0, -1.0))
    else:
        up = Vector((0.0, 1.0, 0.0))
    u = up.cross(n)
    return n, u, up


def nearest_face(normal_rbx):
    best, best_d = "FRONT", -2.0
    for face, n in coords.FACE_NORMALS.items():
        d = normal_rbx.dot(Vector(n))
        if d > best_d:
            best, best_d = face, d
    return best


def _poly(bm, verts, idx):
    try:
        return bm.faces.new([verts[i] for i in idx])
    except ValueError:
        return None


def _build_box(bm, hx, hy, hz):
    v = [bm.verts.new(_bl(p)) for p in (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
        (-hx, hy, -hz), (hx, hy, -hz), (hx, hy, hz), (-hx, hy, hz))]
    for idx in ((0, 1, 2, 3), (7, 6, 5, 4), (3, 2, 6, 7), (1, 0, 4, 5), (0, 3, 7, 4), (2, 1, 5, 6)):
        _poly(bm, v, idx)


def _build_wedge(bm, hx, hy, hz):
    # Full bottom, full-height back (+Z), slope facing front-up (-Z).
    v = [bm.verts.new(_bl(p)) for p in (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
        (-hx, hy, hz), (hx, hy, hz))]
    for idx in ((0, 1, 2, 3), (3, 2, 5, 4), (0, 4, 5, 1), (0, 3, 4), (1, 5, 2)):
        _poly(bm, v, idx)


def _build_corner_wedge(bm, hx, hy, hz):
    v = [bm.verts.new(_bl(p)) for p in (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
        (hx, hy, -hz))]
    for idx in ((0, 1, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)):
        _poly(bm, v, idx)


def _build_ball(bm, size):
    r = min(size) / 2.0
    bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=SEGMENTS // 2,
                              radius=r, calc_uvs=True)
    for f in bm.faces:
        f.smooth = True


def _build_cylinder(bm, size):
    # Roblox cylinders run along their local X axis.
    length = size[0]
    r = min(size[1], size[2]) / 2.0
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=SEGMENTS,
                                radius1=r, radius2=r, depth=length, calc_uvs=True)
    bmesh.ops.rotate(bm, verts=res["verts"], cent=(0, 0, 0),
                     matrix=Matrix.Rotation(math.pi / 2.0, 3, "Y"))
    for f in bm.faces:
        f.smooth = abs(f.normal.x) < 0.5


def _build_head(bm, size):
    """Classic Roblox head: an upright cylinder with rounded rims.
    Diameter = min(X, Z), height = Y (Roblox Y = Blender Z)."""
    d = min(size[0], size[2])
    h = size[1]
    r = d / 2.0
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=SEGMENTS,
                                radius1=r, radius2=r, depth=h, calc_uvs=True)
    caps = [f for f in bm.faces if abs(f.normal.z) > 0.9]
    rim = list({e for f in caps for e in f.edges})
    bevel = min(r, h / 2.0) * 0.45
    if rim and bevel > 1e-5:
        bmesh.ops.bevel(bm, geom=rim, offset=bevel, offset_type="OFFSET", segments=5,
                        profile=0.5, affect="EDGES", clamp_overlap=True)
    for f in bm.faces:
        f.smooth = True
    return res


def build_primitive(me, shape, size):
    """Rebuild mesh `me` as a Roblox primitive. `size` is in Blender units
    along Roblox local axes (x, y, z)."""
    bm = bmesh.new()
    hx, hy, hz = (max(s, 1e-4) / 2.0 for s in size)
    if shape == "BALL":
        _build_ball(bm, size)
    elif shape == "CYLINDER":
        _build_cylinder(bm, size)
    elif shape == "HEAD":
        _build_head(bm, size)
    elif shape == "WEDGE":
        _build_wedge(bm, hx, hy, hz)
    elif shape == "CORNER_WEDGE":
        _build_corner_wedge(bm, hx, hy, hz)
    else:  # BLOCK, TRUSS, and fallbacks
        _build_box(bm, hx, hy, hz)
    bm.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if shape in BOX_SHAPES or shape not in ("BALL", "CYLINDER", "HEAD"):
        project_face_uvs(me, "UVMap", (hx, hy, hz))
    me.update()


def project_face_uvs(me, layer_name, half, region=None):
    """UVs for box-like meshes: each face gets the image as seen from
    outside (0..1), or its area of the clothing template when `region` is
    given ("TORSO", "LEFT_LIMB", "RIGHT_LIMB")."""
    uv_layer = me.uv_layers.get(layer_name) or me.uv_layers.new(name=layer_name)
    hx, hy, hz = (max(h, 1e-6) for h in half)
    half_v = Vector((hx, hy, hz))
    rects = TEMPLATE_RECTS.get(region) if region else None
    W, H = TEMPLATE_SIZE
    for poly in me.polygons:
        face = nearest_face(_rbx(poly.normal))
        n, u, up = face_axes(face)
        hu = abs(u.x) * half_v.x + abs(u.y) * half_v.y + abs(u.z) * half_v.z
        hv = abs(up.x) * half_v.x + abs(up.y) * half_v.y + abs(up.z) * half_v.z
        for li in poly.loop_indices:
            p = _rbx(me.vertices[me.loops[li].vertex_index].co)
            s = p.dot(u) / (2.0 * hu) + 0.5
            t = p.dot(up) / (2.0 * hv) + 0.5
            if rects:
                rx, ry, rw, rh = rects[face]
                x = rx + s * rw
                y = ry + (1.0 - t) * rh
                uv_layer.data[li].uv = (x / W, 1.0 - y / H)
            else:
                uv_layer.data[li].uv = (s, t)
    return uv_layer


def build_mesh_from_rbx(me, mesh_data, scale=1.0, mesh_scale=(1, 1, 1), offset=(0, 0, 0)):
    """Fill `me` from a parsed rbx.mesh.MeshData (studs, Roblox axes)."""
    sx, sy, sz = (mesh_scale[i] * scale for i in range(3))
    ox, oy, oz = (offset[i] * scale for i in range(3))
    verts = [(-(p[0] * sx + ox), p[2] * sz + oz, p[1] * sy + oy) for p in mesh_data.positions]
    faces = [f for f in mesh_data.faces if max(f) < len(verts) and len(set(f)) == 3]
    me.clear_geometry()
    me.from_pydata(verts, [], faces)
    if mesh_data.uvs and len(mesh_data.uvs) >= len(verts):
        uv_layer = me.uv_layers.new(name="UVMap")
        uvs = mesh_data.uvs
        vidx = [0] * len(me.loops)
        me.loops.foreach_get("vertex_index", vidx)
        flat = [c for vi in vidx for c in uvs[vi]]
        uv_layer.data.foreach_set("uv", flat)
    for poly in me.polygons:
        poly.use_smooth = True
    if mesh_data.normals and len(mesh_data.normals) >= len(verts):
        try:
            me.normals_split_custom_set_from_vertices(
                [(-n[0], n[2], n[1]) for n in mesh_data.normals[:len(verts)]])
        except (RuntimeError, ValueError, TypeError):
            pass
    me.validate(clean_customdata=False)
    me.update()


# ---------------------------------------------------------------------------
# Object-level helpers

def ensure_single_user_mesh(obj):
    if obj.data is None or obj.type != "MESH":
        return None
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    return obj.data


def _set_scale_keep_world(obj, scale_vec):
    loc, rot, _ = obj.matrix_basis.decompose()
    obj.matrix_basis = Matrix.LocRotScale(loc, rot, scale_vec)


def part_box_size(part_obj):
    """Size (studs) of the box that decals/projections on this part cover, in
    the part's *unscaled* local space."""
    r = part_obj.rblx
    if r.shape in ("MESH", "UNION"):
        return tuple(r.initial_size)
    return tuple(r.size)


def ensure_template_uvs(obj):
    """Add clothing-template UV maps needed by the part's layers (box parts)."""
    r = obj.rblx
    if obj.type != "MESH" or r.shape not in ("BLOCK", "TRUSS"):
        return
    regions = {l.template_region for l in r.layers if l.mapping == "TEMPLATE"}
    if not regions:
        return
    scale = coords.stud_scale()
    half = tuple(s * scale / 2.0 for s in part_box_size(obj))
    me = obj.data
    for region in regions:
        name = "RBX_Template_" + region
        if me.uv_layers.get(name) is None:
            project_face_uvs(me, name, half, region)
    if me.uv_layers.get("UVMap") is not None:
        me.uv_layers.active = me.uv_layers["UVMap"]
        me.uv_layers["UVMap"].active_render = True


def rebuild_part(obj):
    """Apply obj.rblx.size/shape to the object's geometry."""
    r = obj.rblx
    scale = coords.stud_scale()
    size = tuple(r.size)
    if r.shape in ("MESH", "UNION"):
        init = tuple(r.initial_size)
        ratio = tuple((s / i) if i > 1e-6 else 1.0 for s, i in zip(size, init))
        _set_scale_keep_world(obj, coords.size_to_bl(ratio))
    else:
        me = ensure_single_user_mesh(obj)
        if me is None:
            return
        build_primitive(me, r.shape, tuple(s * scale for s in size))
        _set_scale_keep_world(obj, Vector((1.0, 1.0, 1.0)))
        ensure_template_uvs(obj)
        from . import materials
        materials.ensure_slot(obj)


def new_mesh_object(name, collection, mesh=None):
    me = mesh or bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    return obj
