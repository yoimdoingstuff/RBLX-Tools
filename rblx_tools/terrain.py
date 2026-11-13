"""Builds Roblox smooth terrain in Blender.

The voxels' occupancy is treated as a density field and the surface where it
crosses 0.5 is extracted with "surface nets" (numpy), which gives the smooth,
rounded look of Roblox terrain. One mesh holds all solid materials (a material
slot and colour per face, from the place's MaterialColors); water is a
separate transparent mesh."""

import bpy
import numpy as np

from . import coords, materials
from .rbx import terrain as rterrain
from .rbx.color import to_linear

MAX_CELLS = 60_000_000

# The 12 edges of a cell as pairs of corner offsets
_CORNERS = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
_EDGES = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]


def dense_grids(cs, chunks):
    """(origin voxel (x,y,z), material uint8 grid, solid occupancy, water occupancy)
    as numpy arrays indexed [x, y, z] (Roblox axes), padded by one empty voxel."""
    chunks = [c for c in chunks if c[1]] or chunks  # skip all-air chunks
    coords_ = np.array([c[0] for c in chunks], dtype=np.int64)
    lo = coords_.min(axis=0) * cs - 1
    hi = (coords_.max(axis=0) + 1) * cs + 1
    shape = tuple(int(v) for v in (hi - lo))
    if shape[0] * shape[1] * shape[2] > MAX_CELLS:
        raise rterrain.TerrainError("terrain too large to build (%d x %d x %d voxels)" % shape)
    mat = np.zeros(shape, dtype=np.uint8)
    occ = np.zeros(shape, dtype=np.float32)
    wat = np.zeros(shape, dtype=np.float32)
    n = cs * cs * cs
    for (cx, cy, cz), runs in chunks:
        m = np.zeros(n, dtype=np.uint8)
        o = np.zeros(n, dtype=np.float32)
        w = np.zeros(n, dtype=np.float32)
        for start, count, material, solid, water in runs:
            sl = slice(start, start + count)
            m[sl] = material
            o[sl] = solid if material not in (0, 1) else 0.0
            w[sl] = 1.0 if material == 1 else water
        # flat index = y*cs*cs + z*cs + x  ->  [y, z, x]  ->  [x, y, z]
        sh = (cs, cs, cs)
        x0, y0, z0 = cx * cs - lo[0], cy * cs - lo[1], cz * cs - lo[2]
        dst = (slice(x0, x0 + cs), slice(y0, y0 + cs), slice(z0, z0 + cs))
        mat[dst] = m.reshape(sh).transpose(2, 0, 1)
        occ[dst] = o.reshape(sh).transpose(2, 0, 1)
        wat[dst] = w.reshape(sh).transpose(2, 0, 1)
    return lo, mat, occ, wat


def surface_nets(density, level=0.5):
    """(vertices Nx3 in voxel-centre units, quads Mx4, quad edge info) for the
    iso-surface of `density`. Edge info: (axis, i, j, k, inside_first) per quad."""
    d = density
    nx, ny, nz = d.shape
    inside = d > level
    cells = (nx - 1, ny - 1, nz - 1)
    # Only cells the surface passes through are touched (maps can have tens of
    # millions of voxels): collect each crossing edge's point per cell.
    cell_ids, points = [], []
    for e0, e1 in _EDGES:
        A, B = _CORNERS[e0], _CORNERS[e1]
        va = d[A[0]:A[0] + cells[0], A[1]:A[1] + cells[1], A[2]:A[2] + cells[2]]
        vb = d[B[0]:B[0] + cells[0], B[1]:B[1] + cells[1], B[2]:B[2] + cells[2]]
        ia = inside[A[0]:A[0] + cells[0], A[1]:A[1] + cells[1], A[2]:A[2] + cells[2]]
        ib = inside[B[0]:B[0] + cells[0], B[1]:B[1] + cells[1], B[2]:B[2] + cells[2]]
        idx = np.nonzero(ia != ib)
        if not len(idx[0]):
            continue
        da, db = va[idx], vb[idx]
        denom = db - da
        t = np.where(np.abs(denom) > 1e-9, (level - da) / np.where(denom == 0, 1, denom), 0.5)
        p = np.stack(idx, axis=1).astype(np.float32)
        p += np.array(A, np.float32) + t[:, None].astype(np.float32) * (np.array(B, np.float32) -
                                                                          np.array(A, np.float32))
        cell_ids.append(np.ravel_multi_index(idx, cells))
        points.append(p)
    if not cell_ids:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.int64), np.zeros((0, 5), np.int64)
    flat = np.concatenate(cell_ids)
    pts = np.concatenate(points)
    uniq, inv = np.unique(flat, return_inverse=True)
    counts = np.bincount(inv).astype(np.float32)
    verts = np.stack([np.bincount(inv, weights=pts[:, a]) for a in range(3)], axis=1) / counts[:, None]
    verts = verts.astype(np.float32)

    class _Index:
        """cell (i, j, k) -> vertex index, or -1 (looked up in the sorted cell list)."""

        def __getitem__(self, ijk):
            i, j, k = ijk
            ok = (i >= 0) & (j >= 0) & (k >= 0) & (i < cells[0]) & (j < cells[1]) & (k < cells[2])
            f = np.ravel_multi_index((np.clip(i, 0, cells[0] - 1), np.clip(j, 0, cells[1] - 1),
                                      np.clip(k, 0, cells[2] - 1)), cells)
            pos = np.clip(np.searchsorted(uniq, f), 0, len(uniq) - 1)
            return np.where(ok & (uniq[pos] == f), pos, -1)

    index = _Index()

    quads, info = [], []
    # Each grid edge (voxel p -> p + axis) that crosses the surface becomes a quad
    # joining the 4 cells around it. (o1, o2) are chosen so o1 x o2 = +axis: the
    # quad faces +axis, which is outward when the solid voxel is at p.
    others = {0: (1, 2), 1: (2, 0), 2: (0, 1)}
    for axis in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[axis] = slice(0, -1)
        b[axis] = slice(1, None)
        ins_a, ins_b = inside[tuple(a)], inside[tuple(b)]
        P = np.stack(np.nonzero(ins_a != ins_b), axis=1)
        if not len(P):
            continue
        o1, o2 = others[axis]
        ok = ((P[:, o1] >= 1) & (P[:, o1] <= cells[o1] - 1) &
              (P[:, o2] >= 1) & (P[:, o2] <= cells[o2] - 1) & (P[:, axis] <= cells[axis] - 1))
        P = P[ok]
        solid_first = ins_a[P[:, 0], P[:, 1], P[:, 2]]
        e1 = np.zeros(3, np.int64)
        e2 = np.zeros(3, np.int64)
        e1[o1] = 1
        e2[o2] = 1
        ring = [P - e1 - e2, P - e2, P, P - e1]
        q = np.stack([index[c[:, 0], c[:, 1], c[:, 2]] for c in ring], axis=1)
        good = (q >= 0).all(axis=1)
        q, P, solid_first = q[good], P[good], solid_first[good]
        q[~solid_first] = q[~solid_first][:, ::-1]
        quads.append(q)
        info.append(np.concatenate([np.full((len(P), 1), axis), P,
                                    solid_first.astype(np.int64)[:, None]], axis=1))
    if not quads:
        return verts, np.zeros((0, 4), np.int64), np.zeros((0, 5), np.int64)
    return verts, np.concatenate(quads), np.concatenate(info)


def _to_blender(verts, lo, scale):
    """voxel-centre index space -> Blender coordinates."""
    studs = (verts + lo.astype(np.float32) + 0.5) * rterrain.VOXEL_STUDS * scale
    return np.stack([-studs[:, 0], studs[:, 2], studs[:, 1]], axis=1)


def _mesh(name, verts, quads):
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    me.loops.add(len(quads) * 4)
    me.loops.foreach_set("vertex_index", quads.astype(np.int32).ravel())
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, len(quads) * 4, 4, dtype=np.int32))
    me.update(calc_edges=True)
    me.validate()
    me.shade_smooth()
    return me


def build(context, collection, smooth_grid, material_colors=b"", water_color=None,
          water_transparency=0.3, scale=1.0, report=None, water_wave_size=0.15,
          water_wave_speed=10.0, water_reflectance=1.0, decoration=False, grass_length=0.7):
    """Returns the created terrain objects (empty list for empty terrain)."""
    cs, chunks = rterrain.decode(smooth_grid)
    if not chunks:
        return []
    lo, mat, occ, wat = dense_grids(cs, chunks)
    colors = rterrain.material_colors(material_colors)
    created = []

    verts, quads, info = surface_nets(occ)
    if len(quads):
        me = _mesh("Terrain", _to_blender(verts, lo, scale), quads)
        # material of each face: the solid voxel on its edge
        axis, i, j, k, first_inside = info.T
        step = np.zeros((len(axis), 3), dtype=np.int64)
        step[np.arange(len(axis)), axis] = 1
        p = np.stack([i, j, k], axis=1) + np.where(first_inside[:, None] == 1, 0, step)
        face_mat = mat[p[:, 0], p[:, 1], p[:, 2]]
        used = sorted(set(int(m) for m in np.unique(face_mat)) - {0, 1}) or [8]
        slot_of = {m: n for n, m in enumerate(used)}
        names = [rterrain.MATERIALS[m] if m < len(rterrain.MATERIALS) else "Rock" for m in used]
        for nm in names:
            me.materials.append(materials.terrain_material(nm if nm in materials.PRESETS else "Rock"))
        me.polygons.foreach_set("material_index",
                                np.array([slot_of.get(int(m), 0) for m in face_mat], dtype=np.int32))
        col = me.attributes.new("rbx_color", "FLOAT_COLOR", "FACE")
        lin = {m: (*to_linear(colors.get(n, (0.5, 0.5, 0.5))), 1.0) for m, n in zip(used, names)}
        col.data.foreach_set("color", np.array([lin.get(int(m), lin[used[0]]) for m in face_mat],
                                               dtype=np.float32).ravel())
        use = me.attributes.new("rbx_use_color", "FLOAT", "FACE")
        use.data.foreach_set("value", np.ones(len(quads), dtype=np.float32))
        obj = bpy.data.objects.new("Terrain", me)
        collection.objects.link(obj)
        obj.rblx.class_name = "Terrain"
        created.append(obj)
        if report is not None:
            report.count("terrain materials", len(used))
        if decoration and "Grass" in names:
            from . import decoration as deco
            deco.add_grass(obj, names.index("Grass"),
                           to_linear(colors.get("Grass", (0.42, 0.5, 0.25))), grass_length)

    wv, wq, _wi = surface_nets(wat)
    if len(wq):
        me = _mesh("Terrain Water", _to_blender(wv, lo, scale), wq)
        obj = bpy.data.objects.new("Terrain Water", me)
        collection.objects.link(obj)
        r = obj.rblx
        r.class_name = "Terrain"
        r.color = to_linear(water_color if water_color else (12 / 255, 84 / 255, 92 / 255))
        r.transparency = max(0.0, min(1.0, water_transparency))
        obj.color = (*r.color, 1.0 - r.transparency)
        obj["rblx_water"] = [float(water_wave_size), float(water_wave_speed),
                             float(water_reflectance)]
        if hasattr(obj, "visible_shadow"):
            obj.visible_shadow = False  # Roblox water doesn't shadow what's under it
        materials.assign(obj, materials.water_material(water_wave_size, water_wave_speed,
                                                       water_reflectance))
        created.append(obj)
    return created
