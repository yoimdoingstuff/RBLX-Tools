"""Roblox <-> Blender coordinate conversion.

Roblox is right-handed and Y-up (LookVector is -Z). Blender is right-handed
and Z-up. We use the rotation that makes Roblox's front (-Z) face Blender's
front (-Y), so Blender's Front view (numpad 1) looks a character in the face:
    Blender (x, y, z) = Roblox (-x, z, y)
Distances are multiplied by the scene's stud scale (Blender units per stud).
"""

import math

from mathutils import Euler, Matrix, Vector

# Roblox -> Blender axis change (a proper rotation, det = +1)
AXIS = Matrix(((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))
AXIS_INV = AXIS.transposed()
AXIS4 = AXIS.to_4x4()
AXIS4_INV = AXIS_INV.to_4x4()


def stud_scale(scene=None):
    if scene is None:
        import bpy
        scene = bpy.context.scene
    try:
        return scene.rblx.stud_scale
    except AttributeError:
        return 1.0


def vec_to_bl(v, scale=1.0):
    """Roblox position/vector (studs) -> Blender Vector."""
    return Vector((-v[0] * scale, v[2] * scale, v[1] * scale))


def vec_to_rbx(v, scale=1.0):
    """Blender Vector -> Roblox (x, y, z) in studs."""
    s = 1.0 / scale if scale else 1.0
    return (-v[0] * s, v[2] * s, v[1] * s)


def size_to_bl(size):
    """Roblox size (x, y, z) -> per-axis magnitudes in Blender local axes."""
    return Vector((abs(size[0]), abs(size[2]), abs(size[1])))


def size_to_rbx(v):
    return (abs(v[0]), abs(v[2]), abs(v[1]))


def rot_to_bl(rot9):
    """Roblox 3x3 rotation (row-major 9-tuple or Matrix) -> Blender 3x3 Matrix."""
    if isinstance(rot9, Matrix):
        m = rot9.to_3x3()
    else:
        m = Matrix((rot9[0:3], rot9[3:6], rot9[6:9]))
    return AXIS @ m @ AXIS_INV


def rot_to_rbx(mat3):
    return AXIS_INV @ mat3 @ AXIS


def cframe_to_matrix(cf, scale=1.0):
    """Roblox CFrame -> Blender 4x4 world matrix (no scale)."""
    m = rot_to_bl(cf.rot).to_4x4()
    m.translation = vec_to_bl(cf.pos, scale)
    return m


def matrix_to_rbx(mat4, scale=1.0):
    """Blender world matrix -> (position studs, 3x3 Roblox rotation Matrix)."""
    loc, rot, _sca = mat4.decompose()
    return vec_to_rbx(loc, scale), rot_to_rbx(rot.to_matrix())


def orientation_from_rbx_rot(rbx_rot3):
    """Roblox Orientation (degrees). Roblox applies Y, then X, then Z
    (R = Ry * Rx * Rz), which is mathutils' 'ZXY' order."""
    e = rbx_rot3.to_euler("ZXY")
    return (math.degrees(e.x), math.degrees(e.y), math.degrees(e.z))


def rbx_rot_from_orientation(deg):
    return Euler((math.radians(deg[0]), math.radians(deg[1]), math.radians(deg[2])), "ZXY").to_matrix()


# NormalId -> unit vector in Roblox space
FACE_NORMALS = {
    "RIGHT": (1.0, 0.0, 0.0),
    "TOP": (0.0, 1.0, 0.0),
    "BACK": (0.0, 0.0, 1.0),
    "LEFT": (-1.0, 0.0, 0.0),
    "BOTTOM": (0.0, -1.0, 0.0),
    "FRONT": (0.0, 0.0, -1.0),
}
