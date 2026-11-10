"""Builds Roblox-style part geometry (Block, Ball, Cylinder, Wedge, ...)
and decal/texture planes. Geometry is generated in Roblox local space and
converted to Blender axes, so a part's local axes match Roblox's."""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import coords

SEGMENTS = 32


def _bl(p):
    return Vector((p[0], -p[2], p[1]))


def _quad_uvs(bm, face):
    uv = bm.loops.layers.uv.verify()
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for loop, c in zip(face.loops, corners):
        loop[uv].uv = c


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
        f = _poly(bm, v, idx)
        if f:
            _quad_uvs(bm, f)


def _build_wedge(bm, hx, hy, hz):
    # Full bottom, full-height back (+Z), slope facing front-up (-Z).
    v = [bm.verts.new(_bl(p)) for p in (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
        (-hx, hy, hz), (hx, hy, hz))]
    for idx in ((0, 1, 2, 3), (3, 2, 5, 4), (0, 4, 5, 1)):
        f = _poly(bm, v, idx)
        if f:
            _quad_uvs(bm, f)
    _poly(bm, v, (0, 3, 4))
    _poly(bm, v, (1, 5, 2))


def _build_corner_wedge(bm, hx, hy, hz):
    v = [bm.verts.new(_bl(p)) for p in (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
        (hx, hy, -hz))]
    f = _poly(bm, v, (0, 1, 2, 3))
    if f:
        _quad_uvs(bm, f)
    for idx in ((0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)):
        _poly(bm, v, idx)


def _build_ball(bm, size):
    r = min(size) / 2.0
    res = bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=SEGMENTS // 2,
                                    radius=r, calc_uvs=True)
    for f in bm.faces:
        f.smooth = True
    return res


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
    me.update()


def build_mesh_from_rbx(me, mesh_data, scale=1.0, mesh_scale=(1, 1, 1), offset=(0, 0, 0)):
    """Fill `me` from a parsed rbx.mesh.MeshData (studs, Roblox axes)."""
    sx, sy, sz = (mesh_scale[i] * scale for i in range(3))
    ox, oy, oz = (offset[i] * scale for i in range(3))
    verts = [(p[0] * sx + ox, -(p[2] * sz + oz), p[1] * sy + oy) for p in mesh_data.positions]
    faces = [f for f in mesh_data.faces if max(f) < len(verts) and len(set(f)) == 3]
    me.clear_geometry()
    me.from_pydata(verts, [], faces)
    if mesh_data.uvs:
        uv_layer = me.uv_layers.new(name="UVMap")
        uvs = mesh_data.uvs
        for poly in me.polygons:
            for li in poly.loop_indices:
                uv_layer.data[li].uv = uvs[me.loops[li].vertex_index]
    if mesh_data.normals:
        try:
            me.normals_split_custom_set_from_vertices(
                [(n[0], -n[2], n[1]) for n in mesh_data.normals])
        except (RuntimeError, ValueError):
            pass
    for poly in me.polygons:
        poly.use_smooth = True
    me.validate(clean_customdata=False)
    me.update()


# ---------------------------------------------------------------------------
# Decal / Texture planes

DECAL_OFFSET = 0.005  # studs, keeps decals from z-fighting with the part


def _face_axes(face):
    n = Vector(coords.FACE_NORMALS[face])
    if face == "TOP":
        up = Vector((0.0, 0.0, -1.0))
    elif face == "BOTTOM":
        up = Vector((0.0, 0.0, 1.0))
    else:
        up = Vector((0.0, 1.0, 0.0))
    u = up.cross(n)
    return n, u, up


def build_decal_plane(me, face, box_size, scale=1.0, tiling=None):
    """Plane covering `face` of a box of `box_size` (studs, Roblox axes).
    `tiling` = (studs_per_tile_u, studs_per_tile_v, offset_u, offset_v) for
    Roblox Texture objects; None stretches the image once (Decal)."""
    n, u, up = _face_axes(face)
    half = Vector(box_size) / 2.0
    # extents along each axis
    depth = abs(n.dot(half))
    hu = abs(u.x) * half.x + abs(u.y) * half.y + abs(u.z) * half.z
    hv = abs(up.x) * half.x + abs(up.y) * half.y + abs(up.z) * half.z
    center = n * (depth + DECAL_OFFSET)

    corners = (
        center - u * hu - up * hv,
        center + u * hu - up * hv,
        center + u * hu + up * hv,
        center - u * hu + up * hv,
    )
    if tiling:
        su, sv, ou, ov = tiling
        su = su if su > 1e-4 else 1.0
        sv = sv if sv > 1e-4 else 1.0
        w, h = hu * 2.0, hv * 2.0
        uvs = ((ou / su, ov / sv), ((w + ou) / su, ov / sv),
               ((w + ou) / su, (h + ov) / sv), (ou / su, (h + ov) / sv))
    else:
        uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

    bm = bmesh.new()
    verts = [bm.verts.new(_bl(c * scale)) for c in corners]
    f = bm.faces.new(verts)
    uv = bm.loops.layers.uv.verify()
    for loop, c in zip(f.loops, uvs):
        loop[uv].uv = c
    bm.to_mesh(me)
    bm.free()
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
        from . import materials
        materials.ensure_slot(obj)
    for child in obj.children:
        if child.rblx.kind in ("DECAL", "TEXTURE"):
            rebuild_decal(child)


def part_box_size(part_obj):
    """Size (studs) of the box that decals on this part should cover, in the
    part's *unscaled* local space."""
    r = part_obj.rblx
    if r.shape in ("MESH", "UNION"):
        return tuple(r.initial_size)
    return tuple(r.size)


def rebuild_decal(obj):
    parent = obj.parent
    if parent is None or obj.type != "MESH":
        return
    r = obj.rblx
    tiling = None
    if r.kind == "TEXTURE":
        tiling = (r.studs_per_tile_u, r.studs_per_tile_v, r.offset_studs_u, r.offset_studs_v)
    me = ensure_single_user_mesh(obj)
    build_decal_plane(me, r.face, part_box_size(parent), coords.stud_scale(), tiling)
    from . import materials
    materials.ensure_slot(obj)


def new_mesh_object(name, collection, mesh=None):
    me = mesh or bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    return obj
