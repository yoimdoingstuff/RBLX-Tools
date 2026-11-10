"""Roblox properties stored on Blender objects (obj.rblx) and scenes
(scene.rblx). Most are real stored properties so they can be keyframed;
Position/Orientation are computed from the object's transform."""

import contextlib

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       PointerProperty, StringProperty)

from . import coords
from .rbx.enums import MATERIALS

_suspended = 0


@contextlib.contextmanager
def suspend_updates():
    """Skip geometry/material rebuilds while setting many properties."""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


def updates_suspended():
    return _suspended > 0


KIND_ITEMS = [
    ("NONE", "None", "Not a Roblox object"),
    ("PART", "Part", "BasePart (Part, MeshPart, WedgePart, ...)"),
    ("DECAL", "Decal", "Image stretched over one face"),
    ("TEXTURE", "Texture", "Image tiled over one face"),
    ("MODEL", "Model", "Model / Folder container"),
    ("LIGHT", "Light", "PointLight / SpotLight / SurfaceLight"),
    ("ATTACHMENT", "Attachment", "Attachment"),
]

SHAPE_ITEMS = [
    ("BLOCK", "Block", "", "MESH_CUBE", 0),
    ("BALL", "Ball", "", "MESH_UVSPHERE", 1),
    ("CYLINDER", "Cylinder", "Runs along the part's X axis, like Roblox", "MESH_CYLINDER", 2),
    ("WEDGE", "Wedge", "", "MESH_CONE", 3),
    ("CORNER_WEDGE", "Corner Wedge", "", "MESH_CONE", 4),
    ("TRUSS", "Truss", "Shown as a block", "MESH_GRID", 5),
    ("MESH", "Mesh", "Custom mesh (MeshPart / SpecialMesh); Size scales it", "MESH_MONKEY", 6),
    ("UNION", "Union", "Union / CSG part (shown as a placeholder)", "MOD_BOOLEAN", 7),
]

MATERIAL_ITEMS = [(name, name, "") for name in (
    "Plastic", "SmoothPlastic", "Neon", "Wood", "WoodPlanks", "Marble", "Basalt", "Slate",
    "CrackedLava", "Concrete", "Limestone", "Granite", "Pavement", "Brick", "Pebble",
    "Cobblestone", "Rock", "Sandstone", "CorrodedMetal", "DiamondPlate", "Foil", "Metal",
    "Grass", "LeafyGrass", "Sand", "Fabric", "Snow", "Mud", "Ground", "Asphalt", "Salt",
    "Ice", "Glacier", "Glass", "ForceField", "Air", "Water")]
assert {m[0] for m in MATERIAL_ITEMS} == set(MATERIALS.values())

FACE_ITEMS = [
    ("RIGHT", "Right", "+X"),
    ("TOP", "Top", "+Y"),
    ("BACK", "Back", "+Z"),
    ("LEFT", "Left", "-X"),
    ("BOTTOM", "Bottom", "-Y"),
    ("FRONT", "Front", "-Z (the part's LookVector)"),
]

MATERIAL_MODE_ITEMS = [
    ("BASIC", "Roblox Material", "Shared material for the Roblox material type"),
    ("TEXTURED", "Texture", "TextureID image over the part color"),
    ("SURFACE", "Custom", "SurfaceAppearance or your own material (left untouched)"),
]


# ---------------------------------------------------------------------------
# Update callbacks

def _on_geometry(self, context):
    if updates_suspended():
        return
    from . import geometry
    obj = self.id_data
    if self.kind == "PART":
        geometry.rebuild_part(obj)
    elif self.kind in ("DECAL", "TEXTURE"):
        geometry.rebuild_decal(obj)


def _on_appearance(self, context):
    obj = self.id_data
    obj.color = (self.color[0], self.color[1], self.color[2], 1.0 - self.transparency)
    if updates_suspended():
        return
    # Shader reads these through Attribute nodes; tag so the viewport redraws.
    obj.update_tag()


def _on_material(self, context):
    if updates_suspended():
        return
    from . import materials
    obj = self.id_data
    if self.kind == "PART" and self.material_mode == "BASIC":
        materials.assign(obj, materials.part_material(self.material))


def _on_shadow(self, context):
    self.id_data.visible_shadow = self.cast_shadow


def _on_texture_id(self, context):
    if updates_suspended():
        return
    from . import materials
    materials.refresh_texture(self.id_data)


def _get_position(self):
    obj = self.id_data
    pos, _ = coords.matrix_to_rbx(obj.matrix_world, coords.stud_scale())
    return pos


def _set_position(self, value):
    obj = self.id_data
    mw = obj.matrix_world.copy()
    mw.translation = coords.vec_to_bl(value, coords.stud_scale())
    obj.matrix_world = mw


def _get_orientation(self):
    obj = self.id_data
    _, rot = coords.matrix_to_rbx(obj.matrix_world, coords.stud_scale())
    return coords.orientation_from_rbx_rot(rot)


def _set_orientation(self, value):
    from mathutils import Matrix
    obj = self.id_data
    loc, _rot, sca = obj.matrix_world.decompose()
    rot = coords.rot_to_bl(coords.rbx_rot_from_orientation(value))
    obj.matrix_world = Matrix.LocRotScale(loc, rot.to_quaternion(), sca)


# ---------------------------------------------------------------------------

class RBLX_ObjectProps(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Kind", items=KIND_ITEMS, default="NONE")
    class_name: StringProperty(name="ClassName", default="")

    # Data
    shape: EnumProperty(name="Shape", items=SHAPE_ITEMS, default="BLOCK", update=_on_geometry)
    size: FloatVectorProperty(name="Size", size=3, subtype="XYZ", unit="NONE",
                              default=(4.0, 1.0, 2.0), min=0.001, soft_max=2048.0,
                              precision=3, update=_on_geometry,
                              description="Size in studs (Roblox axes: X, Y up, Z)")
    initial_size: FloatVectorProperty(name="Initial Size", size=3, default=(1.0, 1.0, 1.0),
                                      options={"HIDDEN"},
                                      description="Size of the mesh geometry at scale 1")
    position: FloatVectorProperty(name="Position", size=3, subtype="XYZ", precision=3,
                                  get=_get_position, set=_set_position,
                                  options={"SKIP_SAVE"},
                                  description="Position in studs, Roblox axes (Y is up)")
    orientation: FloatVectorProperty(name="Orientation", size=3, subtype="XYZ", precision=2,
                                     get=_get_orientation, set=_set_orientation,
                                     options={"SKIP_SAVE"},
                                     description="Roblox Orientation in degrees (applied Y, X, Z)")

    # Appearance
    color: FloatVectorProperty(name="Color", size=3, subtype="COLOR", min=0.0, max=1.0,
                               default=(0.639, 0.635, 0.647), update=_on_appearance)
    transparency: FloatProperty(name="Transparency", min=0.0, max=1.0, default=0.0,
                                update=_on_appearance)
    reflectance: FloatProperty(name="Reflectance", min=0.0, max=1.0, default=0.0,
                               update=_on_appearance)
    material: EnumProperty(name="Material", items=MATERIAL_ITEMS, default="Plastic",
                           update=_on_material)
    material_mode: EnumProperty(name="Surface", items=MATERIAL_MODE_ITEMS, default="BASIC")
    cast_shadow: BoolProperty(name="CastShadow", default=True, update=_on_shadow)

    # Behavior (stored for reference/round-tripping; no effect in Blender)
    anchored: BoolProperty(name="Anchored", default=True)
    can_collide: BoolProperty(name="CanCollide", default=True)
    can_touch: BoolProperty(name="CanTouch", default=True)
    can_query: BoolProperty(name="CanQuery", default=True)
    locked: BoolProperty(name="Locked", default=False)
    massless: BoolProperty(name="Massless", default=False)

    # Assets
    mesh_id: StringProperty(name="MeshId", default="")
    mesh_fit: BoolProperty(name="Fit Mesh To InitialSize", default=True, options={"HIDDEN"},
                           description="MeshPart: mesh is fitted to InitialSize. "
                                       "SpecialMesh: mesh uses Scale/Offset as-is")
    mesh_scale: FloatVectorProperty(name="Mesh Scale", size=3, default=(1.0, 1.0, 1.0),
                                    options={"HIDDEN"})
    mesh_offset: FloatVectorProperty(name="Mesh Offset", size=3, default=(0.0, 0.0, 0.0),
                                     options={"HIDDEN"})
    texture_id: StringProperty(name="TextureID", default="", update=_on_texture_id,
                               description="rbxassetid://... or a local image path")
    asset_missing: BoolProperty(name="Asset Missing", default=False, options={"HIDDEN"})

    # Decal / Texture
    face: EnumProperty(name="Face", items=FACE_ITEMS, default="FRONT", update=_on_geometry)
    studs_per_tile_u: FloatProperty(name="StudsPerTileU", default=2.0, min=0.01,
                                    update=_on_geometry)
    studs_per_tile_v: FloatProperty(name="StudsPerTileV", default=2.0, min=0.01,
                                    update=_on_geometry)
    offset_studs_u: FloatProperty(name="OffsetStudsU", default=0.0, update=_on_geometry)
    offset_studs_v: FloatProperty(name="OffsetStudsV", default=0.0, update=_on_geometry)

    # Light
    light_range: FloatProperty(name="Range", default=8.0, min=0.0, max=60.0)
    light_brightness: FloatProperty(name="Brightness", default=1.0, min=0.0)


class RBLX_SceneProps(bpy.types.PropertyGroup):
    stud_scale: FloatProperty(
        name="Stud Scale", default=1.0, min=0.0001, soft_max=10.0,
        description="Blender units per Roblox stud (1.0 keeps numbers identical to Studio; "
                    "0.28 is Roblox's real-world meters-per-stud)")


CLASSES = (RBLX_ObjectProps, RBLX_SceneProps)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.rblx = PointerProperty(type=RBLX_ObjectProps)
    bpy.types.Scene.rblx = PointerProperty(type=RBLX_SceneProps)


def unregister():
    del bpy.types.Scene.rblx
    del bpy.types.Object.rblx
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
