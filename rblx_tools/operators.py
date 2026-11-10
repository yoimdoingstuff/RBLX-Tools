import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector

from . import assets, character, coords, geometry, importer, lighting, materials
from .download import DownloadError
from .props import (FACE_ITEMS, LAYER_MAPPING_ITEMS, SHAPE_ITEMS, TEMPLATE_REGION_ITEMS,
                    suspend_updates)
from .rbx import RobloxFormatError, load_file

ROBLOX_FILES = "*.rbxm;*.rbxmx;*.rbxl;*.rbxlx"
IMAGE_FILES = "*.png;*.jpg;*.jpeg;*.webp;*.tga;*.bmp;*.gif"
IMAGE_EXTS = ".png;.jpg;.jpeg;.webp;.tga;.bmp;.gif"

DEFAULT_SIZES = {
    "BLOCK": (4.0, 1.0, 2.0),
    "BALL": (2.0, 2.0, 2.0),
    "CYLINDER": (2.0, 2.0, 2.0),
    "WEDGE": (4.0, 1.0, 2.0),
    "CORNER_WEDGE": (2.0, 2.0, 2.0),
    "TRUSS": (2.0, 2.0, 2.0),
    "HEAD": (2.0, 1.0, 1.0),
}
from .rbx.color import to_linear  # noqa: E402

MEDIUM_STONE_GREY = to_linear((163 / 255.0, 162 / 255.0, 165 / 255.0))  # linear


def _parts(objects):
    return [o for o in objects if o.rblx.kind == "PART"]


def _ensure_object_mode(context):
    if context.mode != "OBJECT" and context.active_object is not None:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass


def _import_options(op):
    return importer.ImportOptions(
        stud_scale=op.stud_scale, import_lighting=op.import_lighting,
        import_lights=op.import_lights, import_attachments=op.import_attachments,
        import_storage=op.import_storage, asset_folder=op.asset_folder,
        hide_invisible=op.hide_invisible, build_rigs=op.build_rigs,
        allow_download=op.download)


def _report_import(op, name, report):
    level = {"WARNING"} if report.missing else {"INFO"}
    op.report(level, "%s: %s (details: Text Editor > RBX Import Report)" % (name, report.summary()))


def _active_layer(context):
    obj = context.active_object
    if obj is None or obj.rblx.kind != "PART" or not obj.rblx.layers:
        return obj, None
    idx = min(obj.rblx.active_layer, len(obj.rblx.layers) - 1)
    return obj, obj.rblx.layers[idx]


# ---------------------------------------------------------------------------
# Import

class IMPORT_SCENE_OT_rblx(bpy.types.Operator, ImportHelper):
    """Import a Roblox model or place file"""
    bl_idname = "import_scene.rblx"
    bl_label = "Import Roblox File"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filename_ext = ".rbxm"
    # SKIP_SAVE: Blender otherwise remembers the last file, and the next import
    # would silently re-import it instead of opening the file browser.
    filepath: StringProperty(name="File Path", subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})
    filter_glob: StringProperty(default=ROBLOX_FILES, options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    stud_scale: FloatProperty(name="Stud Scale", default=1.0, min=0.0001, soft_max=10.0,
                              description="Blender units per stud")
    download: BoolProperty(name="Download Missing Assets", default=True,
                           description="Download meshes/images not found on disk (needs an "
                                       "Open Cloud API key in the add-on preferences)")
    build_rigs: BoolProperty(name="Rig Characters", default=True,
                             description="Build an armature for characters (Models with a "
                                         "Humanoid) from their Motor6D joints")
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
        col.prop(self, "download")
        if self.download:
            col.label(text=assets.describe_access(), icon="INFO")
        col.prop(self, "build_rigs")
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
        # Drag & drop passes the file in; a normal import opens the file browser
        if self.properties.is_property_set("filepath", ghost=False) and os.path.isfile(self.filepath):
            return self.execute(context)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        _ensure_object_mode(context)
        paths = []
        if self.files and self.directory:
            paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        if not paths:
            paths = [self.filepath]
        opts = _import_options(self)
        for path in paths:
            try:
                report = importer.import_file(context, path, opts)
            except (RobloxFormatError, OSError) as ex:
                self.report({"ERROR"}, "%s: %s" % (os.path.basename(path), ex))
                return {"CANCELLED"}
            _report_import(self, os.path.basename(path), report)
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

def create_part(context, shape="BLOCK", size=None, name=None, collection=None):
    scene = context.scene
    size = size or DEFAULT_SIZES.get(shape, (4.0, 1.0, 2.0))
    name = name or {"WEDGE": "Wedge", "CORNER_WEDGE": "CornerWedge", "TRUSS": "Truss",
                    "HEAD": "Head"}.get(shape, "Part")
    obj = geometry.new_mesh_object(name, collection or context.collection)
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
        _ensure_object_mode(context)
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
                r.color = MEDIUM_STONE_GREY
                r.material_mode = "SURFACE" if self.keep_material else "BASIC"
            if not self.keep_material:
                materials.refresh(obj)
            n += 1
        self.report({"INFO"}, "Converted %d object(s)" % n)
        return {"FINISHED"}


class RBLX_OT_use_roblox_material(bpy.types.Operator):
    """Switch this part from its custom material to Roblox materials and texture layers"""
    bl_idname = "rblx.use_roblox_material"
    bl_label = "Use Roblox Material"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.rblx.kind == "PART"

    def execute(self, context):
        for obj in _parts(context.selected_objects) or [context.active_object]:
            obj.rblx.material_mode = "BASIC"
            materials.refresh(obj)
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
        scene = context.scene
        multi = scene.rblx.edit_all_selected
        scene.rblx.edit_all_selected = False
        try:
            for obj in _parts(context.selected_objects):
                r = obj.rblx
                s = coords.size_to_rbx(obj.scale)
                if r.shape in ("MESH", "UNION"):
                    r.size = tuple(i * k for i, k in zip(r.initial_size, s))
                else:
                    r.size = tuple(v * k for v, k in zip(r.size, s))  # rebuild resets scale
        finally:
            scene.rblx.edit_all_selected = multi
        return {"FINISHED"}


COPY_GROUPS = [
    ("APPEARANCE", "Appearance", "Color, Material, Transparency, Reflectance, CastShadow"),
    ("SIZE", "Size", "Size and Shape"),
    ("BEHAVIOR", "Behavior", "Anchored, CanCollide, ..."),
    ("TEXTURES", "Textures", "Texture layers"),
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
        src_obj = context.active_object
        src = src_obj.rblx
        scene = context.scene
        multi = scene.rblx.edit_all_selected
        scene.rblx.edit_all_selected = False
        try:
            for obj in _parts(context.selected_objects):
                if obj == src_obj:
                    continue
                r = obj.rblx
                if "APPEARANCE" in self.groups:
                    r.color = src.color
                    r.transparency = src.transparency
                    r.reflectance = src.reflectance
                    r.cast_shadow = src.cast_shadow
                    r.material = src.material
                if "SIZE" in self.groups and r.shape not in ("MESH", "UNION") and \
                        src.shape not in ("MESH", "UNION"):
                    r.shape = src.shape
                    r.size = src.size
                if "BEHAVIOR" in self.groups:
                    for k in ("anchored", "can_collide", "can_touch", "can_query", "locked", "massless"):
                        setattr(r, k, getattr(src, k))
                if "TEXTURES" in self.groups:
                    with suspend_updates():
                        r.layers.clear()
                        for l in src.layers:
                            n = r.layers.add()
                            for k in l.bl_rna.properties.keys():
                                if k not in ("rna_type",):
                                    try:
                                        setattr(n, k, getattr(l, k))
                                    except (AttributeError, TypeError):
                                        pass
                    materials.refresh(obj)
        finally:
            scene.rblx.edit_all_selected = multi
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Texture layers

def _layer_defaults(obj, mapping):
    if mapping == "AUTO":
        return "UV" if obj.rblx.shape in ("MESH", "UNION", "BALL", "HEAD") else "FACE"
    return mapping


class RBLX_OT_layer_add(bpy.types.Operator, ImportHelper):
    """Add an image (yours, or one downloaded from Roblox) as a texture layer on the selected parts"""
    bl_idname = "rblx.layer_add"
    bl_label = "Add Texture"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default=IMAGE_FILES, options={"HIDDEN"})
    mapping: EnumProperty(name="Type", items=[("AUTO", "Automatic",
                                               "Wrap for meshes, Decal on the front face for blocks")]
                          + [i[:3] for i in LAYER_MAPPING_ITEMS], default="AUTO")
    face: EnumProperty(name="Face", items=FACE_ITEMS, default="FRONT")
    template_region: EnumProperty(name="Template Area", items=TEMPLATE_REGION_ITEMS, default="TORSO")
    studs_per_tile: FloatProperty(name="Studs Per Tile", default=2.0, min=0.01)
    asset: StringProperty(name="Or Roblox Asset", default="",
                          description="rbxassetid://123 or just the id; downloaded with your "
                                      "API key (used instead of the file when set)")

    @classmethod
    def poll(cls, context):
        return bool(_parts(context.selected_objects))

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mapping")
        if self.mapping in ("FACE", "TILED"):
            col.prop(self, "face")
        if self.mapping == "TILED":
            col.prop(self, "studs_per_tile")
        if self.mapping == "TEMPLATE":
            col.prop(self, "template_region")
        col.separator()
        col.prop(self, "asset")

    def execute(self, context):
        resolver = assets.default_resolver()
        source = self.asset.strip()
        if source:
            if source.isdigit():
                source = "rbxassetid://" + source
            path = resolver.resolve_image(source)
            if path is None:
                why = resolver.error_for(source) or "not found"
                self.report({"ERROR"}, "Couldn't get %s: %s" % (source, why))
                return {"CANCELLED"}
        else:
            path = self.filepath
            source = path
        if not os.path.isfile(path):
            self.report({"ERROR"}, "Pick an image file")
            return {"CANCELLED"}
        img = materials.load_image(path)
        if img is None:
            self.report({"ERROR"}, "Blender can't read that image")
            return {"CANCELLED"}
        targets = _parts(context.selected_objects)
        for obj in targets:
            if obj.rblx.material_mode == "SURFACE":
                obj.rblx.material_mode = "BASIC"
            materials.add_layer(obj, img, _layer_defaults(obj, self.mapping),
                                os.path.splitext(os.path.basename(path))[0], "Image", source,
                                self.face, region=self.template_region,
                                tiling=(self.studs_per_tile, self.studs_per_tile, 0.0, 0.0))
        self.report({"INFO"}, "Added texture to %d part(s)" % len(targets))
        return {"FINISHED"}


class RBLX_OT_layer_remove(bpy.types.Operator):
    """Remove the active texture layer"""
    bl_idname = "rblx.layer_remove"
    bl_label = "Remove Texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_layer(context)[1] is not None

    def execute(self, context):
        obj = context.active_object
        r = obj.rblx
        r.layers.remove(min(r.active_layer, len(r.layers) - 1))
        r.active_layer = max(0, min(r.active_layer, len(r.layers) - 1))
        materials.refresh(obj)
        return {"FINISHED"}


class RBLX_OT_layer_move(bpy.types.Operator):
    """Move the active texture layer up (drawn on top) or down"""
    bl_idname = "rblx.layer_move"
    bl_label = "Move Texture"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    @classmethod
    def poll(cls, context):
        return _active_layer(context)[1] is not None

    def execute(self, context):
        obj = context.active_object
        r = obj.rblx
        i = min(r.active_layer, len(r.layers) - 1)
        # The list shows the top layer first, so "Up" moves later in the stack
        j = i + 1 if self.direction == "UP" else i - 1
        if 0 <= j < len(r.layers):
            r.layers.move(i, j)
            r.active_layer = j
            materials.refresh(obj)
        return {"FINISHED"}


class RBLX_OT_layer_replace(bpy.types.Operator, ImportHelper):
    """Replace the active texture layer's image"""
    bl_idname = "rblx.layer_replace"
    bl_label = "Replace Image"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default=IMAGE_FILES, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_layer(context)[1] is not None

    def execute(self, context):
        obj, layer = _active_layer(context)
        img = materials.load_image(self.filepath)
        if img is None:
            self.report({"ERROR"}, "Blender can't read that image")
            return {"CANCELLED"}
        layer.source = self.filepath
        layer.missing = False
        layer.image = img  # update callback rebuilds the material
        return {"FINISHED"}


class RBLX_OT_layer_make_unique(bpy.types.Operator):
    """Give this layer its own copy of the image, so painting on it doesn't change other parts"""
    bl_idname = "rblx.layer_make_unique"
    bl_label = "Make Image Unique"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        l = _active_layer(context)[1]
        return l is not None and l.image is not None

    def execute(self, context):
        obj, layer = _active_layer(context)
        copy = layer.image.copy()
        copy.name = "%s (%s)" % (layer.image.name, obj.name)
        try:
            copy.pack()
        except RuntimeError:
            pass
        layer.image = copy
        return {"FINISHED"}


class RBLX_OT_layer_paint(bpy.types.Operator):
    """Paint the active texture layer directly on the part in the 3D view (Texture Paint mode)"""
    bl_idname = "rblx.layer_paint"
    bl_label = "Paint on Part"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        l = _active_layer(context)[1]
        return l is not None and l.image is not None and l.mapping in ("UV", "TEMPLATE")

    def execute(self, context):
        obj, layer = _active_layer(context)
        me = obj.data
        uv_name = "UVMap"
        if layer.mapping == "TEMPLATE" and me.uv_layers.get("RBX_Template_" + layer.template_region):
            uv_name = "RBX_Template_" + layer.template_region
        if me.uv_layers.get(uv_name) is not None:
            me.uv_layers.active = me.uv_layers[uv_name]
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
        ip = context.scene.tool_settings.image_paint
        ip.mode = "IMAGE"
        ip.canvas = layer.image
        self.report({"INFO"}, "Painting on '%s'. Save it from the Textures panel when done"
                    % layer.image.name)
        return {"FINISHED"}


class RBLX_OT_layer_edit(bpy.types.Operator):
    """Open the active layer's image in an Image Editor to view, paint or adjust it"""
    bl_idname = "rblx.layer_edit"
    bl_label = "Edit Image"

    @classmethod
    def poll(cls, context):
        l = _active_layer(context)[1]
        return l is not None and l.image is not None

    def execute(self, context):
        img = _active_layer(context)[1].image
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    area.spaces.active.image = img
                    area.spaces.active.ui_mode = "PAINT"
                    return {"FINISHED"}
        bpy.ops.wm.window_new()
        win = context.window_manager.windows[-1]
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = img
        area.spaces.active.ui_mode = "PAINT"
        return {"FINISHED"}


class RBLX_OT_layer_save(bpy.types.Operator, ExportHelper):
    """Save the active layer's image (with your edits) to a file"""
    bl_idname = "rblx.layer_save"
    bl_label = "Save Image As"

    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        l = _active_layer(context)[1]
        return l is not None and l.image is not None

    def invoke(self, context, event):
        layer = _active_layer(context)[1]
        self.filepath = bpy.path.clean_name(layer.image.name) + ".png"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        layer = _active_layer(context)[1]
        img = layer.image
        if img.packed_file is not None:
            img.unpack(method="REMOVE")
        img.filepath_raw = self.filepath
        img.file_format = "PNG"
        img.save()
        layer.source = self.filepath
        self.report({"INFO"}, "Saved " + self.filepath)
        return {"FINISHED"}


class RBLX_OT_layer_pack(bpy.types.Operator):
    """Keep the active layer's image (with your edits) inside the .blend file"""
    bl_idname = "rblx.layer_pack"
    bl_label = "Pack into .blend"

    @classmethod
    def poll(cls, context):
        l = _active_layer(context)[1]
        return l is not None and l.image is not None

    def execute(self, context):
        img = _active_layer(context)[1].image
        img.pack()
        return {"FINISHED"}


def _hit_part(context, event):
    """The Roblox part under the mouse and the face that was hit."""
    area = context.area
    if area is None or area.type != "VIEW_3D":
        return None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    rv3d = area.spaces.active.region_3d
    if region is None or rv3d is None:
        return None, None
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _loc, normal, _idx, obj, _m = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit or obj is None:
        return None, None
    obj = obj.original
    if obj.rblx.kind != "PART":
        return None, None
    local_n = obj.matrix_world.to_3x3().transposed() @ normal  # world -> local normal
    rbx_n = geometry._rbx(local_n).normalized()
    return obj, geometry.nearest_face(rbx_n)


class RBLX_OT_drop_image(bpy.types.Operator):
    """Drop an image onto a Roblox part: it becomes a Decal on the face you dropped it on
    (or wraps the whole part for meshes)"""
    bl_idname = "rblx.drop_image"
    bl_label = "Roblox Texture"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        paths = [os.path.join(self.directory, f.name) for f in self.files if f.name] \
            if self.files and self.directory else [self.filepath]
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            return {"CANCELLED"}
        obj, face = _hit_part(context, event)
        targets = [obj] if obj is not None else _parts(context.selected_objects)
        if not targets:
            self.report({"WARNING"}, "Drop the image onto a Roblox part (or select parts first)")
            return {"CANCELLED"}
        for path in paths:
            img = materials.load_image(path)
            if img is None:
                self.report({"ERROR"}, "Blender can't read " + os.path.basename(path))
                continue
            for t in targets:
                if t.rblx.material_mode == "SURFACE":
                    t.rblx.material_mode = "BASIC"
                mapping = "UV" if t.rblx.shape in ("MESH", "UNION", "BALL", "HEAD") else "FACE"
                materials.add_layer(t, img, mapping, os.path.splitext(os.path.basename(path))[0],
                                    "Image", path, face or "FRONT")
        if obj is not None:
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        return {"FINISHED"}

    def execute(self, context):
        return {"CANCELLED"}


class RBLX_FH_image(bpy.types.FileHandler):
    bl_idname = "RBLX_FH_image"
    bl_label = "Roblox Texture (on part)"
    bl_import_operator = "rblx.drop_image"
    bl_file_extensions = IMAGE_EXTS

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"


# ---------------------------------------------------------------------------
# Characters

def _character_parts(context):
    obj = context.active_object
    model = obj
    while model is not None and not model.get("rblx_character"):
        model = model.parent
    if model is None:
        return None, _parts(context.selected_objects)
    found = []
    stack = list(model.children)
    while stack:
        o = stack.pop()
        if o.rblx.kind == "PART":
            found.append(o)
        stack.extend(o.children)
    return model, found


CLOTHING_ITEMS = [
    ("SHIRT", "Shirt", "Roblox shirt template on the torso and arms"),
    ("PANTS", "Pants", "Roblox pants template on the torso and legs"),
    ("TSHIRT", "T-Shirt", "Image on the front of the torso"),
]


class RBLX_OT_apply_clothing(bpy.types.Operator, ImportHelper):
    """Put a Roblox shirt, pants or T-shirt image on the selected character"""
    bl_idname = "rblx.apply_clothing"
    bl_label = "Add Clothing"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default=IMAGE_FILES, options={"HIDDEN"})
    kind: EnumProperty(name="Clothing", items=CLOTHING_ITEMS, default="SHIRT")
    asset: StringProperty(name="Or Roblox Asset", default="",
                          description="Shirt/Pants/T-Shirt asset id or rbxassetid:// (downloaded "
                                      "with your API key)")
    replace: BoolProperty(name="Replace Existing", default=True,
                          description="Remove clothing of the same kind first")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        resolver = assets.default_resolver()
        source = self.asset.strip()
        if source:
            if source.isdigit():
                source = "rbxassetid://" + source
            path = resolver.resolve_image(source)
            if path is None:
                self.report({"ERROR"}, "Couldn't get %s: %s" % (source, resolver.error_for(source)
                                                                or "not found"))
                return {"CANCELLED"}
        else:
            path, source = self.filepath, self.filepath
        img = materials.load_image(path) if path and os.path.isfile(path) else None
        if img is None:
            self.report({"ERROR"}, "Pick a clothing image")
            return {"CANCELLED"}
        _model, parts = _character_parts(context)
        by_name = {}
        for p in parts:
            by_name.setdefault(p.name.split(".")[0], p)
        kind_name = {"SHIRT": "Shirt", "PANTS": "Pants", "TSHIRT": "ShirtGraphic"}[self.kind]
        character.set_clothing_boxes(None, by_name, coords.stud_scale(context.scene),
                                     lambda o: o.matrix_world)
        n = 0
        if self.kind == "TSHIRT":
            target = by_name.get("Torso") or by_name.get("UpperTorso")
            table = {target.name.split(".")[0]: None} if target else {}
        else:
            table = character.SHIRT_PARTS if self.kind == "SHIRT" else character.PANTS_PARTS
        for pname, region in table.items():
            obj = by_name.get(pname)
            if obj is None:
                continue
            r = obj.rblx
            if self.replace:
                for i in reversed(range(len(r.layers))):
                    if r.layers[i].kind == kind_name:
                        r.layers.remove(i)
            if r.material_mode == "SURFACE":
                r.material_mode = "BASIC"
            if self.kind == "TSHIRT":
                materials.add_layer(obj, img, "FACE", "T-Shirt", kind_name, source, "FRONT")
            else:
                materials.add_layer(obj, img, "TEMPLATE", kind_name, kind_name, source,
                                    region=region)
                # Shirts sit on top of pants
                if self.kind == "PANTS":
                    names = [l.kind for l in r.layers]
                    if "Shirt" in names:
                        r.layers.move(len(r.layers) - 1, names.index("Shirt"))
                        materials.refresh(obj)
            n += 1
        if n == 0:
            self.report({"WARNING"}, "Select a character (R6 or R15) first")
            return {"CANCELLED"}
        self.report({"INFO"}, "%s applied to %d body part(s)" % (kind_name, n))
        return {"FINISHED"}


def _import_document(op, context, doc, title, place_at_cursor=True):
    opts = importer.ImportOptions(stud_scale=context.scene.rblx.stud_scale)
    imp = importer.Importer(context, opts)
    report = imp.run_document(doc, title)
    if place_at_cursor:
        for o in imp.roots:
            o.location = o.location + context.scene.cursor.location
    rig = next((o for o in imp.collection.objects if o.rblx.kind == "RIG"), None)
    for o in context.selected_objects:
        o.select_set(False)
    if rig is not None:
        rig.select_set(True)
        context.view_layer.objects.active = rig
    _report_import(op, title, report)
    return imp


class RBLX_OT_add_character(bpy.types.Operator):
    """Add a rigged Roblox character (R6 works offline; R15 uses Roblox Studio's rig)"""
    bl_idname = "rblx.add_character"
    bl_label = "Add Roblox Character"
    bl_options = {"REGISTER", "UNDO"}

    rig_type: EnumProperty(name="Rig", items=[("R6", "R6", "Classic 6-part body"),
                                              ("R15", "R15", "15-part body (needs Roblox Studio "
                                                             "installed; meshes download with "
                                                             "your API key)")],
                           default="R6")

    def execute(self, context):
        _ensure_object_mode(context)
        if self.rig_type == "R6":
            doc = character.build_r6_document()
        else:
            doc = character.load_r15_document()
            if doc is None:
                self.report({"ERROR"}, "R15 needs Roblox Studio installed (it provides the rig)")
                return {"CANCELLED"}
        _import_document(self, context, doc, self.rig_type + " Rig")
        return {"FINISHED"}


class RBLX_OT_import_avatar(bpy.types.Operator):
    """Import a Roblox user's avatar (body colors, clothing, face, accessories) as a rigged character"""
    bl_idname = "rblx.import_avatar"
    bl_label = "Import Avatar"
    bl_options = {"REGISTER", "UNDO"}

    username: StringProperty(name="Username or User ID", default="")
    rig_type: EnumProperty(name="Rig", items=[("AUTO", "Avatar's Own", "R6 or R15, as set on Roblox"),
                                              ("R6", "R6", ""), ("R15", "R15", "")],
                           default="AUTO")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "username")
        col.prop(self, "rig_type")
        col.label(text=assets.describe_access(), icon="INFO")
        if assets.make_downloader()[1]:
            col.label(text="Clothing/accessories need an API key or cookie")

    def execute(self, context):
        if not self.username.strip():
            self.report({"ERROR"}, "Enter a username")
            return {"CANCELLED"}
        if not assets.online_allowed():
            self.report({"ERROR"}, "Blender's online access is off (Preferences > System > Network)")
            return {"CANCELLED"}
        _ensure_object_mode(context)
        resolver = assets.default_resolver()
        report = importer.ImportReport()
        try:
            doc, name, rig = character.build_avatar_document(self.username, resolver, report,
                                                             self.rig_type)
        except (DownloadError, ValueError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        imp = _import_document(self, context, doc, "%s (%s)" % (name, rig))
        imp.report.warnings.extend(report.warnings)
        for content, who in report.missing.items():
            for w in who:
                imp.report.miss(content, w, resolver.error_for(content))
        blocked = getattr(report, "avatar_needs_login", [])
        if blocked:
            imp.report.warnings.insert(0, "Avatar items that couldn't be downloaded: " + ", ".join(blocked))
            hint = ("add an API key or .ROBLOSECURITY cookie (Sidebar > Roblox > Import & Assets)"
                    if resolver.download_note else "check the reasons in Text Editor > RBX Import Report")
            self.report({"WARNING"}, "%d item(s) not downloaded (%s): %s" % (
                len(blocked), ", ".join(blocked[:4]) + ("..." if len(blocked) > 4 else ""), hint))
        imp.report.write_text(name)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Assets

class RBLX_OT_reload_assets(bpy.types.Operator):
    """Look for missing meshes and images again (downloads them if an API key is set)"""
    bl_idname = "rblx.reload_assets"
    bl_label = "Reload Missing Assets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        resolver = assets.default_resolver()
        cache = {}
        fixed = still = 0
        for obj in context.scene.objects:
            r = obj.rblx
            if r.kind != "PART" or not r.asset_missing:
                continue
            ok = True
            if r.shape == "MESH" and r.mesh_id and obj.type == "MESH" and \
                    not obj.data.name.startswith("RBX Mesh "):
                ok = importer.reload_part_mesh(obj, resolver, cache)
            for layer in r.layers:
                if layer.missing or layer.image is None:
                    ok = materials.resolve_layer_image(layer, resolver) and ok
            materials.refresh(obj)
            r.asset_missing = not ok
            fixed += ok
            still += not ok
        note = resolver.download_note
        self.report({"INFO"}, "Fixed %d object(s); %d still missing%s" % (
            fixed, still, (" (%s)" % note) if still and note else ""))
        return {"FINISHED"}


class RBLX_OT_clear_cache(bpy.types.Operator):
    """Delete the downloaded meshes, textures and models from the asset library
    (they'll be downloaded again when needed)"""
    bl_idname = "rblx.clear_cache"
    bl_label = "Clear Asset Library"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, message="Delete all downloaded Roblox assets from the library?")

    def execute(self, context):
        from .download import LIBRARY_SUBFOLDERS
        lib = assets.library_dir()
        n = 0
        for sub in LIBRARY_SUBFOLDERS:
            d = os.path.join(lib, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                # only files this add-on downloaded (named <asset id>.<ext>)
                if os.path.isfile(p) and os.path.splitext(fn)[0].split(".")[0].isdigit():
                    os.remove(p)
                    n += 1
        self.report({"INFO"}, "Removed %d downloaded file(s)" % n)
        return {"FINISHED"}


class RBLX_OT_test_download(bpy.types.Operator):
    """Download one asset to check your API key / cookie (saved into the asset library)"""
    bl_idname = "rblx.test_download"
    bl_label = "Test Download"

    asset: StringProperty(name="Asset ID", default="",
                          description="Any mesh, texture or model id. Use one of your own or a "
                                      "creator's asset to test your key/cookie (Roblox-made "
                                      "assets download without any login)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "asset")
        col.label(text=assets.describe_access(), icon="INFO")

    def execute(self, context):
        aid = assets.asset_id(self.asset.strip()) or self.asset.strip()
        if not aid.isdigit():
            self.report({"ERROR"}, "Enter an asset id (the number in the asset's URL)")
            return {"CANCELLED"}
        downloader, note = assets.make_downloader()
        if downloader is None:
            self.report({"ERROR"}, note)
            return {"CANCELLED"}
        path = downloader.fetch(aid)
        if path is None:
            self.report({"ERROR"}, "Couldn't download %s: %s" % (aid, downloader.errors.get(aid)))
            return {"CANCELLED"}
        self.report({"INFO"}, "Downloaded %s with %s -> %s" % (
            aid, downloader.methods.get(aid), os.path.relpath(path, assets.library_dir())))
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
    bl_label = "Roblox"

    def draw(self, context):
        layout = self.layout
        for ident, label, _desc, icon, _n in SHAPE_ITEMS:
            if ident in ("MESH", "UNION"):
                continue
            layout.operator(RBLX_OT_add_part.bl_idname, text=label, icon=icon).shape = ident
        layout.separator()
        layout.operator(RBLX_OT_add_character.bl_idname, text="R6 Character",
                        icon="ARMATURE_DATA").rig_type = "R6"
        layout.operator(RBLX_OT_add_character.bl_idname, text="R15 Character",
                        icon="ARMATURE_DATA").rig_type = "R15"
        layout.operator(RBLX_OT_import_avatar.bl_idname, text="Avatar from Username...",
                        icon="USER")


def _menu_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_rblx.bl_idname, text="Roblox (.rbxm/.rbxmx/.rbxl/.rbxlx)")


def _menu_add(self, context):
    self.layout.menu(VIEW3D_MT_rblx_add.bl_idname, icon="MESH_CUBE")


CLASSES = (
    IMPORT_SCENE_OT_rblx,
    RBLX_FH_import,
    RBLX_OT_add_part,
    RBLX_OT_convert_to_part,
    RBLX_OT_use_roblox_material,
    RBLX_OT_sync_size,
    RBLX_OT_copy_to_selected,
    RBLX_OT_layer_add,
    RBLX_OT_layer_remove,
    RBLX_OT_layer_move,
    RBLX_OT_layer_replace,
    RBLX_OT_layer_make_unique,
    RBLX_OT_layer_paint,
    RBLX_OT_layer_edit,
    RBLX_OT_layer_save,
    RBLX_OT_layer_pack,
    RBLX_OT_drop_image,
    RBLX_FH_image,
    RBLX_OT_apply_clothing,
    RBLX_OT_add_character,
    RBLX_OT_import_avatar,
    RBLX_OT_reload_assets,
    RBLX_OT_clear_cache,
    RBLX_OT_test_download,
    RBLX_OT_apply_lighting,
    RBLX_OT_lighting_preset,
    RBLX_OT_load_lighting,
    VIEW3D_MT_rblx_add,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.VIEW3D_MT_add.append(_menu_add)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(_menu_add)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
