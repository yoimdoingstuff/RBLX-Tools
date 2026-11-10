import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Vector

from . import assets, coords, geometry, importer, lighting, materials
from .props import FACE_ITEMS, SHAPE_ITEMS, suspend_updates
from .rbx import RobloxFormatError, load_file

ROBLOX_FILES = "*.rbxm;*.rbxmx;*.rbxl;*.rbxlx"

DEFAULT_SIZES = {
    "BLOCK": (4.0, 1.0, 2.0),
    "BALL": (2.0, 2.0, 2.0),
    "CYLINDER": (2.0, 2.0, 2.0),
    "WEDGE": (4.0, 1.0, 2.0),
    "CORNER_WEDGE": (2.0, 2.0, 2.0),
    "TRUSS": (2.0, 2.0, 2.0),
}
MEDIUM_STONE_GREY = (163 / 255.0, 162 / 255.0, 165 / 255.0)


def _parts(objects):
    return [o for o in objects if o.rblx.kind == "PART"]


# ---------------------------------------------------------------------------
# Import

class IMPORT_SCENE_OT_rblx(bpy.types.Operator, ImportHelper):
    """Import a Roblox model or place file"""
    bl_idname = "import_scene.rblx"
    bl_label = "Import Roblox File"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filename_ext = ".rbxm"
    filter_glob: StringProperty(default=ROBLOX_FILES, options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    stud_scale: FloatProperty(name="Stud Scale", default=1.0, min=0.0001, soft_max=10.0,
                              description="Blender units per stud")
    import_lighting: BoolProperty(name="Lighting", default=True,
                                  description="Apply the file's Lighting settings (place files)")
    import_lights: BoolProperty(name="Lights", default=True,
                                description="PointLight / SpotLight / SurfaceLight")
    import_attachments: BoolProperty(name="Attachments", default=False)
    import_storage: BoolProperty(name="Storage Services", default=False,
                                 description="Also import models in ReplicatedStorage, "
                                             "ServerStorage and StarterPack (place files)")
    hide_invisible: BoolProperty(name="Wireframe Invisible Parts", default=True,
                                 description="Show Transparency = 1 parts as wireframe")
    asset_folder: StringProperty(name="Extra Asset Folder", subtype="DIR_PATH", default="",
                                 description="Searched in addition to the folder in preferences")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "stud_scale")
        col.separator()
        col.prop(self, "import_lighting")
        col.prop(self, "import_lights")
        col.prop(self, "import_attachments")
        col.prop(self, "import_storage")
        col.prop(self, "hide_invisible")
        col.separator()
        col.prop(self, "asset_folder")

    def invoke(self, context, event):
        self.stud_scale = context.scene.rblx.stud_scale
        if self.filepath and os.path.isfile(self.filepath):
            return self.execute(context)  # drag & drop
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        paths = []
        if self.files and self.directory:
            paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        if not paths:
            paths = [self.filepath]
        opts = importer.ImportOptions(
            stud_scale=self.stud_scale, import_lighting=self.import_lighting,
            import_lights=self.import_lights, import_attachments=self.import_attachments,
            import_storage=self.import_storage, asset_folder=self.asset_folder,
            hide_invisible=self.hide_invisible)
        for path in paths:
            try:
                report = importer.import_file(context, path, opts)
            except (RobloxFormatError, OSError) as ex:
                self.report({"ERROR"}, "%s: %s" % (os.path.basename(path), ex))
                return {"CANCELLED"}
            level = {"WARNING"} if report.missing else {"INFO"}
            self.report(level, "%s: %s (details in Text Editor > RBX Import Report)"
                        % (os.path.basename(path), report.summary()))
        return {"FINISHED"}


class RBLX_FH_import(bpy.types.FileHandler):
    bl_idname = "RBLX_FH_import"
    bl_label = "Roblox File"
    bl_import_operator = "import_scene.rblx"
    bl_file_extensions = ".rbxm;.rbxmx;.rbxl;.rbxlx"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type in ("VIEW_3D", "OUTLINER")


# ---------------------------------------------------------------------------
# Parts

def create_part(context, shape="BLOCK", size=None, name=None):
    scene = context.scene
    scale = coords.stud_scale(scene)
    size = size or DEFAULT_SIZES.get(shape, (4.0, 1.0, 2.0))
    name = name or ("Part" if shape in ("BLOCK", "BALL", "CYLINDER") else
                    {"WEDGE": "Wedge", "CORNER_WEDGE": "CornerWedge", "TRUSS": "Truss"}[shape])
    obj = geometry.new_mesh_object(name, context.collection)
    with suspend_updates():
        r = obj.rblx
        r.kind = "PART"
        r.class_name = {"WEDGE": "WedgePart", "CORNER_WEDGE": "CornerWedgePart",
                        "TRUSS": "TrussPart"}.get(shape, "Part")
        r.shape = shape
        r.size = size
        r.initial_size = size
        r.color = MEDIUM_STONE_GREY
        r.material = "Plastic"
    obj.color = (*MEDIUM_STONE_GREY, 1.0)
    obj.location = scene.cursor.location
    geometry.rebuild_part(obj)
    materials.assign(obj, materials.part_material("Plastic"))
    return obj


class RBLX_OT_add_part(bpy.types.Operator):
    """Add a Roblox part"""
    bl_idname = "rblx.add_part"
    bl_label = "Add Roblox Part"
    bl_options = {"REGISTER", "UNDO"}

    shape: EnumProperty(name="Shape", items=[s for s in SHAPE_ITEMS if s[0] not in ("MESH", "UNION")],
                        default="BLOCK")

    def execute(self, context):
        for o in context.selected_objects:
            o.select_set(False)
        obj = create_part(context, self.shape)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class RBLX_OT_convert_to_part(bpy.types.Operator):
    """Turn the selected mesh objects into Roblox parts (keeps their geometry)"""
    bl_idname = "rblx.convert_to_part"
    bl_label = "Make Roblox Part"
    bl_options = {"REGISTER", "UNDO"}

    keep_material: BoolProperty(name="Keep Material", default=True,
                                description="Keep the object's current material instead of "
                                            "switching to a Roblox material")

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.selected_objects)

    def execute(self, context):
        scale = coords.stud_scale(context.scene)
        n = 0
        for obj in context.selected_objects:
            if obj.type != "MESH" or obj.rblx.kind != "NONE":
                continue
            bb = [Vector(c) for c in obj.bound_box]
            local_dims = Vector((max(v.x for v in bb) - min(v.x for v in bb),
                                 max(v.y for v in bb) - min(v.y for v in bb),
                                 max(v.z for v in bb) - min(v.z for v in bb)))
            initial = tuple(max(d / scale, 0.001) for d in coords.size_to_rbx(local_dims))
            ratio = coords.size_to_rbx(obj.scale)
            with suspend_updates():
                r = obj.rblx
                r.kind = "PART"
                r.class_name = "MeshPart"
                r.shape = "MESH"
                r.initial_size = initial
                r.size = tuple(i * s for i, s in zip(initial, ratio))
                r.color = MEDIUM_STONE_GREY if self.keep_material else tuple(obj.color[:3])
                r.material_mode = "SURFACE" if self.keep_material else "BASIC"
            if not self.keep_material:
                materials.assign(obj, materials.part_material(obj.rblx.material))
            n += 1
        self.report({"INFO"}, "Converted %d object(s)" % n)
        return {"FINISHED"}


class RBLX_OT_sync_size(bpy.types.Operator):
    """Fold the object's Blender scale into the Roblox Size property"""
    bl_idname = "rblx.sync_size"
    bl_label = "Apply Scale to Size"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_parts(context.selected_objects))

    def execute(self, context):
        for obj in _parts(context.selected_objects):
            r = obj.rblx
            s = coords.size_to_rbx(obj.scale)
            if r.shape in ("MESH", "UNION"):
                r.size = tuple(i * k for i, k in zip(r.initial_size, s))
            else:
                r.size = tuple(v * k for v, k in zip(r.size, s))  # rebuild resets scale
        return {"FINISHED"}


COPY_GROUPS = [
    ("APPEARANCE", "Appearance", "Color, Material, Transparency, Reflectance, CastShadow"),
    ("SIZE", "Size", "Size and Shape"),
    ("BEHAVIOR", "Behavior", "Anchored, CanCollide, ..."),
]


class RBLX_OT_copy_to_selected(bpy.types.Operator):
    """Copy the active part's Roblox properties to the other selected parts"""
    bl_idname = "rblx.copy_to_selected"
    bl_label = "Copy to Selected"
    bl_options = {"REGISTER", "UNDO"}

    groups: EnumProperty(name="Copy", items=COPY_GROUPS, options={"ENUM_FLAG"},
                         default={"APPEARANCE"})

    @classmethod
    def poll(cls, context):
        a = context.active_object
        return a is not None and a.rblx.kind == "PART" and len(context.selected_objects) > 1

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        src = context.active_object.rblx
        for obj in _parts(context.selected_objects):
            if obj == context.active_object:
                continue
            r = obj.rblx
            if "APPEARANCE" in self.groups:
                r.color = src.color
                r.transparency = src.transparency
                r.reflectance = src.reflectance
                r.cast_shadow = src.cast_shadow
                if r.material_mode == "BASIC":
                    r.material = src.material
            if "SIZE" in self.groups and r.shape not in ("MESH", "UNION") and \
                    src.shape not in ("MESH", "UNION"):
                r.shape = src.shape
                r.size = src.size
            if "BEHAVIOR" in self.groups:
                for k in ("anchored", "can_collide", "can_touch", "can_query", "locked", "massless"):
                    setattr(r, k, getattr(src, k))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Textures

TEXTURE_MODES = [
    ("DECAL", "Decal", "Stretch the image once over one face"),
    ("TEXTURE", "Texture", "Tile the image over one face (StudsPerTile)"),
    ("PART", "Part Texture", "Wrap the image over the whole part using its UVs "
                              "(like MeshPart.TextureID)"),
]


class RBLX_OT_add_texture(bpy.types.Operator, ImportHelper):
    """Add an image (e.g. downloaded from Roblox) to the selected parts"""
    bl_idname = "rblx.add_texture"
    bl_label = "Add Roblox Texture"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.webp", options={"HIDDEN"})
    mode: EnumProperty(name="Type", items=TEXTURE_MODES, default="DECAL")
    face: EnumProperty(name="Face", items=FACE_ITEMS, default="FRONT")
    studs_per_tile: FloatProperty(name="Studs Per Tile", default=2.0, min=0.01)

    @classmethod
    def poll(cls, context):
        return bool(_parts(context.selected_objects))

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mode")
        if self.mode != "PART":
            col.prop(self, "face")
        if self.mode == "TEXTURE":
            col.prop(self, "studs_per_tile")

    def execute(self, context):
        path = self.filepath
        if not os.path.isfile(path):
            self.report({"ERROR"}, "Pick an image file")
            return {"CANCELLED"}
        resolver = assets.default_resolver()
        targets = _parts(context.selected_objects)
        for part in targets:
            if self.mode == "PART":
                part.rblx.texture_id = path  # update callback assigns the material
                if part.rblx.material_mode == "SURFACE":
                    part.rblx.material_mode = "BASIC"
                    materials.refresh_texture(part, resolver)
                continue
            kind = self.mode
            name = os.path.splitext(os.path.basename(path))[0]
            obj = geometry.new_mesh_object(name, part.users_collection[0] if part.users_collection
                                           else context.collection)
            obj.parent = part
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = Matrix.Identity(4)
            with suspend_updates():
                r = obj.rblx
                r.kind = kind
                r.class_name = "Texture" if kind == "TEXTURE" else "Decal"
                r.face = self.face
                r.color = (1.0, 1.0, 1.0)
                r.studs_per_tile_u = r.studs_per_tile_v = self.studs_per_tile
                r.texture_id = path
            obj.color = (1.0, 1.0, 1.0, 1.0)
            obj.visible_shadow = False
            geometry.rebuild_decal(obj)
            materials.refresh_texture(obj, resolver)
        self.report({"INFO"}, "Added texture to %d part(s)" % len(targets))
        return {"FINISHED"}


class RBLX_OT_reload_assets(bpy.types.Operator):
    """Look for missing meshes and images again (after adding files to your Asset Folder)"""
    bl_idname = "rblx.reload_assets"
    bl_label = "Reload Missing Assets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        resolver = assets.default_resolver()
        cache = {}
        fixed = still = 0
        for obj in context.scene.objects:
            r = obj.rblx
            if r.kind == "NONE" or not r.asset_missing:
                continue
            ok = True
            if r.kind == "PART" and r.shape == "MESH" and r.mesh_id and obj.type == "MESH":
                # placeholder boxes are single-user meshes named after the part
                if obj.data.name.startswith("RBX Mesh "):
                    ok = True
                else:
                    ok = importer.reload_part_mesh(obj, resolver, cache)
            if r.texture_id:
                ok = materials.refresh_texture(obj, resolver) and ok
            r.asset_missing = not ok
            if ok:
                fixed += 1
            else:
                still += 1
        self.report({"INFO"}, "Fixed %d object(s); %d still missing assets" % (fixed, still))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Lighting

class RBLX_OT_apply_lighting(bpy.types.Operator):
    """Apply the Roblox lighting settings to the scene"""
    bl_idname = "rblx.apply_lighting"
    bl_label = "Apply Lighting"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        lighting.apply_lighting(context.scene)
        return {"FINISHED"}


class RBLX_OT_lighting_preset(bpy.types.Operator):
    """Load a Roblox lighting preset"""
    bl_idname = "rblx.lighting_preset"
    bl_label = "Lighting Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Preset", items=lighting.PRESET_ITEMS)

    def execute(self, context):
        lighting.set_props(context.scene, lighting.PRESETS[self.preset])
        return {"FINISHED"}


class RBLX_OT_load_lighting(bpy.types.Operator, ImportHelper):
    """Load only the Lighting settings from a Roblox place or model file"""
    bl_idname = "rblx.load_lighting"
    bl_label = "Load Lighting From File"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default=ROBLOX_FILES, options={"HIDDEN"})

    def execute(self, context):
        try:
            doc = load_file(self.filepath)
        except (RobloxFormatError, OSError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        inst = next((i for i in doc.all_instances() if i.class_name == "Lighting"), None)
        if inst is None:
            self.report({"WARNING"}, "No Lighting service in this file")
            return {"CANCELLED"}
        lighting.set_props(context.scene, lighting.values_from_instance(inst))
        self.report({"INFO"}, "Lighting loaded")
        return {"FINISHED"}


# ---------------------------------------------------------------------------

class VIEW3D_MT_rblx_add(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_rblx_add"
    bl_label = "Roblox Part"

    def draw(self, context):
        for ident, label, _desc, icon, _n in SHAPE_ITEMS:
            if ident in ("MESH", "UNION"):
                continue
            self.layout.operator(RBLX_OT_add_part.bl_idname, text=label, icon=icon).shape = ident


def _menu_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_rblx.bl_idname, text="Roblox (.rbxm/.rbxmx/.rbxl/.rbxlx)")


def _menu_add(self, context):
    self.layout.menu(VIEW3D_MT_rblx_add.bl_idname, icon="MESH_CUBE")


CLASSES = (
    IMPORT_SCENE_OT_rblx,
    RBLX_FH_import,
    RBLX_OT_add_part,
    RBLX_OT_convert_to_part,
    RBLX_OT_sync_size,
    RBLX_OT_copy_to_selected,
    RBLX_OT_add_texture,
    RBLX_OT_reload_assets,
    RBLX_OT_apply_lighting,
    RBLX_OT_lighting_preset,
    RBLX_OT_load_lighting,
    VIEW3D_MT_rblx_add,
)


def register():
    for c in CLASSES:
        if c is RBLX_FH_import and not hasattr(bpy.types, "FileHandler"):
            continue
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.VIEW3D_MT_add.append(_menu_add)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(_menu_add)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(CLASSES):
        if c is RBLX_FH_import and not hasattr(bpy.types, "FileHandler"):
            continue
        bpy.utils.unregister_class(c)
