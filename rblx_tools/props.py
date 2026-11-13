"""Roblox properties stored on Blender objects (obj.rblx) and scenes
(scene.rblx). Most are real stored properties so they can be keyframed;
Position/Orientation/BrickColor are computed.

Like Roblox Studio, editing a property while several parts are selected
applies it to all of them (scene.rblx.edit_all_selected)."""

import contextlib

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)

from . import coords
from .rbx.enums import MATERIALS

_suspended = 0
_propagating = False


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
    ("MODEL", "Model", "Model / Folder container"),
    ("RIG", "Rig", "Character rig (armature built from Motor6D joints)"),
    ("LIGHT", "Light", "PointLight / SpotLight / SurfaceLight"),
    ("ATTACHMENT", "Attachment", "Attachment"),
    ("EFFECT", "Effect", "ParticleEmitter / Fire / Smoke / Sparkles / Beam"),
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
    ("HEAD", "Head", "Classic character head", "MESH_CAPSULE", 8),
]
PRIMITIVE_SHAPES = {"BLOCK", "BALL", "CYLINDER", "WEDGE", "CORNER_WEDGE", "TRUSS", "HEAD"}

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
    ("LAYERED", "Textured", "Roblox material plus this part's texture layers"),
    ("SURFACE", "Custom", "SurfaceAppearance or your own material (left untouched)"),
]

LAYER_MAPPING_ITEMS = [
    ("UV", "Wrap (UV)", "Wraps the whole part using its UV map, like MeshPart.TextureID", "UV", 0),
    ("FACE", "Decal", "Stretched once over one face, like a Roblox Decal", "IMAGE_PLANE", 1),
    ("TILED", "Texture", "Tiled over one face, like a Roblox Texture", "TEXTURE", 2),
    ("TEMPLATE", "Clothing", "Roblox shirt/pants template (585x559)", "MOD_CLOTH", 3),
]

TEMPLATE_REGION_ITEMS = [
    ("TORSO", "Torso", "Torso area of the template"),
    ("LEFT_LIMB", "Left Arm / Leg", "Left arm area (shirts) or left leg (pants)"),
    ("RIGHT_LIMB", "Right Arm / Leg", "Right arm area (shirts) or right leg (pants)"),
]

# Named BrickColors for the Studio-style BrickColor picker
BRICK_COLOR_NAMES = [
    ("White", (242, 243, 243)), ("Institutional white", (248, 248, 248)),
    ("Light stone grey", (229, 228, 223)), ("Medium stone grey", (163, 162, 165)),
    ("Dark stone grey", (99, 95, 98)), ("Black", (27, 42, 53)), ("Really black", (17, 17, 17)),
    ("Bright red", (196, 40, 28)), ("Really red", (255, 0, 0)), ("Bright orange", (218, 133, 65)),
    ("Bright yellow", (245, 205, 48)), ("New Yeller", (255, 255, 0)),
    ("Bright green", (75, 151, 75)), ("Dark green", (40, 127, 71)), ("Lime green", (0, 255, 0)),
    ("Bright blue", (13, 105, 172)), ("Really blue", (0, 0, 255)), ("Navy blue", (0, 32, 96)),
    ("Toothpaste", (0, 255, 255)), ("Cyan", (4, 175, 236)), ("Bright violet", (107, 50, 124)),
    ("Magenta", (170, 0, 170)), ("Hot pink", (255, 0, 191)), ("Pink", (255, 102, 204)),
    ("Brown", (124, 92, 70)), ("Reddish brown", (105, 64, 40)), ("Nougat", (204, 142, 105)),
    ("Light orange", (234, 184, 146)), ("Brick yellow", (215, 197, 154)),
    ("Sand blue", (116, 134, 157)), ("Sand green", (120, 144, 130)), ("Earth green", (39, 70, 45)),
]
BRICK_COLOR_ITEMS = [(str(i), n, "") for i, (n, _c) in enumerate(BRICK_COLOR_NAMES)]


# ---------------------------------------------------------------------------
# Studio-style multi-selection editing

def _propagate(self, context, attr):
    global _propagating
    if _propagating or updates_suspended() or context is None:
        return
    scene = getattr(context, "scene", None)
    if scene is None or not scene.rblx.edit_all_selected:
        return
    obj = self.id_data
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None or view_layer.objects.active != obj:
        return
    try:
        selected = context.selected_objects
    except AttributeError:
        return
    value = getattr(self, attr)
    if hasattr(value, "__len__") and not isinstance(value, str):
        value = tuple(value)
    _propagating = True
    try:
        for other in selected:
            if other is obj or other.rblx.kind != self.kind:
                continue
            if attr == "shape" and other.rblx.shape not in PRIMITIVE_SHAPES:
                continue
            setattr(other.rblx, attr, value)
    finally:
        _propagating = False


def _upd(attr, *funcs):
    def update(self, context):
        for f in funcs:
            f(self, context)
        _propagate(self, context, attr)
    return update


def _on_geometry(self, context):
    if updates_suspended():
        return
    from . import geometry
    if self.kind == "PART":
        geometry.rebuild_part(self.id_data)


def casts_shadow(r):
    """Roblox draws nothing for a fully transparent part, not even its shadow
    (e.g. a character's HumanoidRootPart, which would shade its Torso)."""
    return r.cast_shadow and r.transparency < 0.999


def _on_appearance(self, context):
    obj = self.id_data
    obj.color = (self.color[0], self.color[1], self.color[2], 1.0 - self.transparency)
    if self.kind == "PART":
        obj.visible_shadow = casts_shadow(self)
    if not updates_suspended():
        obj.update_tag()


def _on_material(self, context):
    if updates_suspended():
        return
    from . import materials
    if self.kind == "PART":
        materials.refresh(self.id_data)


def _on_shadow(self, context):
    self.id_data.visible_shadow = casts_shadow(self)


def _noop(self, context):
    pass


def _on_highlight(self, context):
    if updates_suspended():
        return
    from . import effects
    effects.apply_highlight(self.id_data)


def _on_material_style(self, context):
    from . import materials
    materials.apply_material_style(self.id_data)


@contextlib.contextmanager
def no_propagation():
    """Set properties on several objects without Studio-style multi-editing
    copying the active object's value onto the others."""
    global _propagating
    old = _propagating
    _propagating = True
    try:
        yield
    finally:
        _propagating = old


def _get_position(self):
    obj = self.id_data
    pos, _ = coords.matrix_to_rbx(obj.matrix_world, coords.stud_scale())
    return pos


def _apply_position(obj, value):
    mw = obj.matrix_world.copy()
    mw.translation = coords.vec_to_bl(value, coords.stud_scale())
    obj.matrix_world = mw


def _set_position(self, value):
    obj = self.id_data
    _apply_position(obj, value)
    for other in _studio_targets(obj):
        _apply_position(other, value)


def _get_orientation(self):
    obj = self.id_data
    _, rot = coords.matrix_to_rbx(obj.matrix_world, coords.stud_scale())
    return coords.orientation_from_rbx_rot(rot)


def _apply_orientation(obj, value):
    from mathutils import Matrix
    loc, _rot, sca = obj.matrix_world.decompose()
    rot = coords.rot_to_bl(coords.rbx_rot_from_orientation(value))
    obj.matrix_world = Matrix.LocRotScale(loc, rot.to_quaternion(), sca)


def _set_orientation(self, value):
    obj = self.id_data
    _apply_orientation(obj, value)
    for other in _studio_targets(obj):
        _apply_orientation(other, value)


def _studio_targets(obj):
    """Other selected objects of the same kind, when multi-editing applies."""
    if _propagating:
        return []
    ctx = bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None or not scene.rblx.edit_all_selected:
        return []
    view_layer = getattr(ctx, "view_layer", None)
    if view_layer is None or view_layer.objects.active != obj:
        return []
    return [o for o in getattr(ctx, "selected_objects", []) if o is not obj and
            o.rblx.kind == obj.rblx.kind]


def _get_brick_color(self):
    from .rbx.color import to_srgb
    c = [v * 255.0 for v in to_srgb(self.color)]
    best, best_d = 0, None
    for i, (_n, rgb) in enumerate(BRICK_COLOR_NAMES):
        d = sum((a - b) ** 2 for a, b in zip(c, rgb))
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _set_brick_color(self, value):
    from .rbx.color import to_linear
    rgb = BRICK_COLOR_NAMES[value][1]
    self.color = to_linear(tuple(v / 255.0 for v in rgb))


# ---------------------------------------------------------------------------
# Texture layers

def _on_layer_struct(self, context):
    if updates_suspended():
        return
    obj = self.id_data
    if isinstance(obj, bpy.types.Object):
        from . import materials
        materials.refresh(obj)


def _on_layer_value(self, context):
    obj = self.id_data
    if isinstance(obj, bpy.types.Object) and not updates_suspended():
        obj.update_tag()


class RBLX_TextureLayer(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Texture")
    kind: StringProperty(name="Class", default="Image",
                         description="Roblox object this layer came from (Decal, Shirt, ...)")
    enabled: BoolProperty(name="Enabled", default=True, update=_on_layer_struct)
    image: PointerProperty(name="Image", type=bpy.types.Image, update=_on_layer_struct)
    source: StringProperty(name="Source", default="",
                           description="Asset id or file the image came from (used to reload it)")
    mapping: EnumProperty(name="Mapping", items=LAYER_MAPPING_ITEMS, default="FACE",
                          update=_on_layer_struct)
    face: EnumProperty(name="Face", items=FACE_ITEMS, default="FRONT", update=_on_layer_struct)
    template_region: EnumProperty(name="Template Area", items=TEMPLATE_REGION_ITEMS,
                                  default="TORSO", update=_on_layer_struct)
    color: FloatVectorProperty(name="Color3", size=3, subtype="COLOR", min=0.0, max=1.0,
                               default=(1.0, 1.0, 1.0), update=_on_layer_value,
                               description="Tint multiplied with the image (Roblox Color3). "
                                           "White keeps the image's own colors")
    transparency: FloatProperty(name="Transparency", min=0.0, max=1.0, default=0.0,
                                update=_on_layer_value)
    studs_per_tile_u: FloatProperty(name="StudsPerTileU", default=2.0, min=0.01,
                                    update=_on_layer_value)
    studs_per_tile_v: FloatProperty(name="StudsPerTileV", default=2.0, min=0.01,
                                    update=_on_layer_value)
    offset_studs_u: FloatProperty(name="OffsetStudsU", default=0.0, update=_on_layer_value)
    offset_studs_v: FloatProperty(name="OffsetStudsV", default=0.0, update=_on_layer_value)
    missing: BoolProperty(name="Missing", default=False, options={"HIDDEN"})


# ---------------------------------------------------------------------------

class RBLX_ObjectProps(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Kind", items=KIND_ITEMS, default="NONE")
    class_name: StringProperty(name="ClassName", default="")

    # Data / Part
    shape: EnumProperty(name="Shape", items=SHAPE_ITEMS, default="BLOCK",
                        update=_upd("shape", _on_geometry))
    size: FloatVectorProperty(name="Size", size=3, subtype="XYZ", unit="NONE",
                              default=(4.0, 1.0, 2.0), min=0.001, soft_max=2048.0,
                              precision=3, update=_upd("size", _on_geometry),
                              description="Size in studs (Roblox axes: X, Y up, Z)")
    bevel: FloatProperty(name="Bevel", min=0.0, soft_max=0.5, default=0.0, precision=3,
                         update=_upd("bevel", _on_geometry),
                         description="Round off the part's edges, in studs (block-like shapes). "
                                     "Roblox's R6 body parts use 0.065")
    initial_size: FloatVectorProperty(name="Initial Size", size=3, default=(1.0, 1.0, 1.0),
                                      options={"HIDDEN"},
                                      description="Size of the mesh geometry at scale 1")
    position: FloatVectorProperty(name="Position", size=3, subtype="XYZ", precision=3,
                                  get=_get_position, set=_set_position, options=set(),
                                  description="Position in studs, Roblox axes (Y is up)")
    orientation: FloatVectorProperty(name="Orientation", size=3, subtype="XYZ", precision=2,
                                     get=_get_orientation, set=_set_orientation, options=set(),
                                     description="Roblox Orientation in degrees (applied Y, X, Z)")

    # Appearance
    brick_color: EnumProperty(name="BrickColor", items=BRICK_COLOR_ITEMS,
                              get=_get_brick_color, set=_set_brick_color,
                              description="Pick a named Roblox BrickColor (sets Color)")
    # Colours are stored linear (Blender's colour space); Roblox's sRGB values
    # are converted on import. The colour picker shows the same hex as Studio.
    color: FloatVectorProperty(name="Color", size=3, subtype="COLOR", min=0.0, max=1.0,
                               default=(0.366, 0.361, 0.376),  # Medium stone grey
                               update=_upd("color", _on_appearance))
    transparency: FloatProperty(name="Transparency", min=0.0, max=1.0, default=0.0,
                                update=_upd("transparency", _on_appearance))
    reflectance: FloatProperty(name="Reflectance", min=0.0, max=1.0, default=0.0,
                               update=_upd("reflectance", _on_appearance))
    material: EnumProperty(name="Material", items=MATERIAL_ITEMS, default="Plastic",
                           update=_upd("material", _on_material))
    material_mode: EnumProperty(name="Surface", items=MATERIAL_MODE_ITEMS, default="BASIC")
    material_variant: StringProperty(
        name="MaterialVariant", default="", update=_upd("material_variant", _on_material),
        description="Name of a MaterialService MaterialVariant to use instead of the plain "
                    "material (it must have the same base material, like in Roblox)")
    cast_shadow: BoolProperty(name="CastShadow", default=True,
                              update=_upd("cast_shadow", _on_shadow))

    # Behavior (stored for reference; no effect in Blender)
    anchored: BoolProperty(name="Anchored", default=True, update=_upd("anchored", _noop))
    can_collide: BoolProperty(name="CanCollide", default=True, update=_upd("can_collide", _noop))
    can_touch: BoolProperty(name="CanTouch", default=True, update=_upd("can_touch", _noop))
    can_query: BoolProperty(name="CanQuery", default=True, update=_upd("can_query", _noop))
    locked: BoolProperty(name="Locked", default=False, update=_upd("locked", _noop))
    massless: BoolProperty(name="Massless", default=False, update=_upd("massless", _noop))

    # Assets
    mesh_id: StringProperty(name="MeshId", default="")
    texture_id: StringProperty(name="TextureID", default="")
    mesh_fit: BoolProperty(name="Fit Mesh To InitialSize", default=True, options={"HIDDEN"})
    mesh_scale: FloatVectorProperty(name="Mesh Scale", size=3, default=(1.0, 1.0, 1.0),
                                    options={"HIDDEN"})
    mesh_offset: FloatVectorProperty(name="Mesh Offset", size=3, default=(0.0, 0.0, 0.0),
                                     options={"HIDDEN"})
    asset_missing: BoolProperty(name="Asset Missing", default=False, options={"HIDDEN"})

    # Texture layers (Decals, Textures, clothing, TextureID, your own images)
    layers: CollectionProperty(type=RBLX_TextureLayer)
    active_layer: IntProperty(name="Active Layer", default=0, min=0)

    # Highlight (Roblox Highlight instance: fill tint + outline)
    highlight_enabled: BoolProperty(name="Highlight", default=False,
                                    update=_upd("highlight_enabled", _on_highlight))
    highlight_fill: FloatVectorProperty(name="FillColor", size=3, subtype="COLOR", min=0.0,
                                        max=1.0, default=(1.0, 0.0, 0.0),
                                        update=_upd("highlight_fill", _on_highlight))
    highlight_fill_transparency: FloatProperty(
        name="FillTransparency", min=0.0, max=1.0, default=0.5,
        update=_upd("highlight_fill_transparency", _on_highlight))
    highlight_outline: FloatVectorProperty(name="OutlineColor", size=3, subtype="COLOR", min=0.0,
                                           max=1.0, default=(1.0, 1.0, 1.0),
                                           update=_upd("highlight_outline", _on_highlight))
    highlight_outline_transparency: FloatProperty(
        name="OutlineTransparency", min=0.0, max=1.0, default=0.0,
        update=_upd("highlight_outline_transparency", _on_highlight))
    # Read by the materials (kept in sync by apply_highlight)
    highlight_fill_alpha: FloatProperty(default=0.0, options={"HIDDEN"})
    highlight_outline_alpha: FloatProperty(default=1.0, options={"HIDDEN"})

    # Light
    light_range: FloatProperty(name="Range", default=8.0, min=0.0, max=60.0)
    light_brightness: FloatProperty(name="Brightness", default=1.0, min=0.0)


class RBLX_SceneProps(bpy.types.PropertyGroup):
    stud_scale: FloatProperty(
        name="Stud Scale", default=1.0, min=0.0001, soft_max=10.0,
        description="Blender units per Roblox stud (1.0 keeps numbers identical to Studio; "
                    "0.28 is Roblox's real-world meters-per-stud)")
    edit_all_selected: BoolProperty(
        name="Edit All Selected", default=True,
        description="Like Roblox Studio: changing a property of the active part changes it on "
                    "every selected part")
    use_2022_materials: BoolProperty(
        name="2022 Materials", default=True, update=_on_material_style,
        description="MaterialService.Use2022Materials: on, parts use Roblox's 2022 material "
                    "look; off, the older (pre-2022) materials")

    # Build mode (Studio-style dragging and handles)
    snap_move: BoolProperty(name="Snap Move", default=True,
                            description="Move and resize in steps of the Move increment")
    move_increment: FloatProperty(name="Move", default=1.0, min=0.001, soft_max=64.0,
                                  precision=3, description="Move/resize step, in studs")
    snap_rotate: BoolProperty(name="Snap Rotate", default=True,
                              description="Rotate in steps of the Rotate increment")
    rotate_increment: FloatProperty(name="Rotate", default=15.0, min=0.01, max=180.0,
                                    precision=2, description="Rotation step, in degrees")
    # Animation Mode (Moon Animator / Eclipse style)
    anim_handle_mode: EnumProperty(
        name="Handles", default="ROTATE",
        items=[("ROTATE", "Rotate", "Rotation rings around the joint", "DRIVER_ROTATIONAL_DIFFERENCE", 0),
               ("MOVE", "Move", "Position arrows", "EMPTY_ARROWS", 1)],
        description="Which handles Animation Mode shows (R switches, like Moon Animator)")
    anim_ease_style: EnumProperty(
        name="Ease", default="LINEAR",
        items=[("LINEAR", "Linear", ""), ("CONSTANT", "Constant", "Holds until the next keyframe"),
               ("SINE", "Sine", ""), ("BACK", "Back", ""), ("QUAD", "Quad", ""),
               ("CUBIC", "Cubic", ""), ("QUART", "Quart", ""), ("QUINT", "Quint", ""),
               ("EXPO", "Expo", ""), ("CIRC", "Circ", ""), ("BOUNCE", "Bounce", ""),
               ("ELASTIC", "Elastic", ""), ("BEZIER", "Smooth (Blender)", "Blender's Bezier curve")],
        description="Easing style for new keyframes: shapes the motion from this keyframe to the next")
    anim_ease_dir: EnumProperty(
        name="Direction", default="IN_OUT",
        items=[("IN", "In", ""), ("OUT", "Out", ""), ("IN_OUT", "InOut", "")],
        description="Easing direction for new keyframes")

    handle_space: EnumProperty(
        name="Space", default="WORLD",
        items=[("WORLD", "World", "Move/Rotate handles follow the world axes", "WORLD", 0),
               ("LOCAL", "Local", "Move/Rotate handles follow the part's own axes",
                "OBJECT_DATA", 1)],
        description="Axes the Move and Rotate handles use (Ctrl+L in Studio)")


CLASSES = (RBLX_TextureLayer, RBLX_ObjectProps, RBLX_SceneProps)


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
