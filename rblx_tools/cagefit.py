"""Layered clothing cage fitting.

Roblox fits a layered clothing item (a MeshPart with a WrapLayer) onto a body
whose MeshParts carry WrapTargets:

  * WrapLayer.ReferenceMeshId is the outer cage of the body the clothing was
    made on, placed by WrapLayer.ReferenceOrigin.
  * Each body part's WrapTarget.CageMeshId is that part's piece of the body's
    outer cage, placed by WrapTarget.CageOrigin.
  * Cages are made from the same template, so their vertices correspond by UV.

The clothing is moved by how far each reference cage vertex is from its body
cage twin, blended over the nearest cage vertices around every clothing
vertex. Roblox's own solver is not published; this is the same idea (cage
deformation by UV-matched cages) without its smoothing and collision passes."""

import numpy as np
from mathutils.kdtree import KDTree

from . import coords
from .rbx import CFrame

UV_EPS = 2e-3
NEIGHBOURS = 8


def _cframe(v):
    return v if isinstance(v, CFrame) else CFrame()


def _vec3(v, default=(1.0, 1.0, 1.0)):
    if isinstance(v, (tuple, list)) and len(v) == 3:
        return tuple(float(x) for x in v)
    return default


def _mesh_scale(part):
    """Render (and cage) mesh scale of a MeshPart: Size / InitialSize."""
    size = _vec3(part.get("size", "Size"))
    init = _vec3(part.get("InitialSize"), None)
    if not init or min(init) <= 1e-6:
        return (1.0, 1.0, 1.0)
    return tuple(s / i for s, i in zip(size, init))


def cage_world(md, part, origin, scale, part_matrix=None):
    """Cage vertices -> Blender world coordinates ((N, 3) array) and their UVs ((N, 2)).
    `part_matrix`: the part's Blender world matrix (default: from its CFrame)."""
    pos = np.asarray(md.positions, dtype=np.float64).reshape(-1, 3)
    uv = np.asarray(md.uvs, dtype=np.float64).reshape(-1, 2) if md.uvs else np.zeros((len(pos), 2))
    pos = pos * np.array(_mesh_scale(part))
    base = part_matrix.normalized() if part_matrix is not None else \
        coords.cframe_to_matrix(_cframe(part.get("CFrame")), scale)
    m = base @ coords.cframe_to_matrix(_cframe(origin), scale)
    # cage space (studs, Roblox axes) -> Blender (scaled, Blender axes) -> world
    bl = np.stack([-pos[:, 0], pos[:, 2], pos[:, 1]], axis=1) * scale
    M = np.array(m)
    return bl @ M[:3, :3].T + M[:3, 3], uv


def displacements(ref_pos, ref_uv, target_pos, target_uv):
    """Per reference-cage vertex: body cage twin - reference vertex (NaN when unmatched)."""
    kd = KDTree(len(target_uv))
    for i, (u, v) in enumerate(target_uv):
        kd.insert((u, v, 0.0), i)
    kd.balance()
    out = np.full(ref_pos.shape, np.nan)
    for i, (u, v) in enumerate(ref_uv):
        _co, j, d = kd.find((u, v, 0.0))
        if j is not None and d <= UV_EPS:
            out[i] = target_pos[j] - ref_pos[i]
    return out


def deform(points, ref_pos, disp, k=NEIGHBOURS):
    """Move `points` (N, 3) by the inverse-distance blend of the k nearest
    matched reference cage vertices' displacements."""
    ok = ~np.isnan(disp[:, 0])
    rp, dp = ref_pos[ok], disp[ok]
    if not len(rp):
        return points.copy(), 0
    kd = KDTree(len(rp))
    for i, c in enumerate(rp):
        kd.insert(c.tolist(), i)
    kd.balance()
    out = points.copy()
    k = min(k, len(rp))
    for n, p in enumerate(points):
        hits = kd.find_n(p.tolist(), k)
        w = np.array([1.0 / (d * d + 1e-6) for _c, _i, d in hits])
        idx = [i for _c, i, _d in hits]
        out[n] = p + (dp[idx] * w[:, None]).sum(axis=0) / w.sum()
    return out, int(ok.sum())


def fit_layer(obj, wrap, handle, targets, load_mesh, scale):
    """Fit one layered clothing object onto the body.
    `targets`: [(body part instance, WrapTarget instance, part's Blender world matrix)].
    `load_mesh(content, who)` -> MeshData or None. Returns matched cage vertex count
    (0: not fitted, e.g. a cage couldn't be downloaded)."""
    ref = load_mesh(wrap.get("ReferenceMeshId", "ReferenceMeshContent"), obj.name)
    if ref is None or not ref.positions:
        return 0
    ref_pos, ref_uv = cage_world(ref, handle, wrap.get("ReferenceOrigin"), scale,
                                 obj.matrix_world)
    tpos, tuv = [], []
    for part, target, part_matrix in targets:
        md = load_mesh(target.get("CageMeshId", "CageMeshContent"), part.name)
        if md is None or not md.positions:
            continue
        p, u = cage_world(md, part, target.get("CageOrigin"), scale, part_matrix)
        tpos.append(p)
        tuv.append(u)
    if not tpos:
        return 0
    disp = displacements(ref_pos, ref_uv, np.concatenate(tpos), np.concatenate(tuv))
    me = obj.data
    if me.users > 1:
        obj.data = me = me.copy()
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    mw = np.array(obj.matrix_world)
    world = co.reshape(n, 3) @ mw[:3, :3].T + mw[:3, 3]
    moved, matched = deform(world, ref_pos, disp)
    if not matched:
        return 0
    inv = np.array(obj.matrix_world.inverted_safe())
    local = moved @ inv[:3, :3].T + inv[:3, 3]
    me.vertices.foreach_set("co", local.astype(np.float32).ravel())
    me.update()
    obj["rblx_cage_fitted"] = matched
    return matched
