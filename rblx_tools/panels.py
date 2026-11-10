"""UI: View3D > Sidebar (N) > Roblox, and Properties Editor > Object > Roblox."""

import bpy

from . import assets, prefs
from .props import SHAPE_ITEMS

CATEGORY = "Roblox"


class _RBLXPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


def _scale_mismatch(obj):
    r = obj.rblx
    if r.shape in ("MESH", "UNION"):
        return False
    return any(abs(s - 1.0) > 1e-4 for s in obj.scale)


def _kind_icon(kind):
    return {"PART": "MESH_CUBE", "MODEL": "OUTLINER_OB_EMPTY", "LIGHT": "LIGHT",
            "ATTACHMENT": "EMPTY_AXIS", "RIG": "ARMATURE_DATA"}.get(kind, "DOT")


def _section(layout, title, icon):
    box = layout.box()
    box.label(text=title, icon=icon)
    return box.column()


def _character_root(obj):
    while obj is not None:
        if obj.get("rblx_character"):
            return obj
        obj = obj.parent
    return None


# ---------------------------------------------------------------------------
# Properties (Studio-style)

def draw_properties(layout, context, obj):
    if obj is None:
        layout.label(text="Select an object", icon="INFO")
        return
    r = obj.rblx
    if r.kind == "NONE":
        layout.label(text=obj.name + " is not a Roblox object", icon="INFO")
        if obj.type == "MESH":
            layout.operator("rblx.convert_to_part", icon="MESH_CUBE")
        return

    nsel = len([o for o in context.selected_objects if o.rblx.kind == r.kind])
    row = layout.row()
    row.label(text=r.class_name or r.kind.title(), icon=_kind_icon(r.kind))
    if nsel > 1:
        row.prop(context.scene.rblx, "edit_all_selected", text="Edit %d selected" % nsel,
                 toggle=True, icon="LINKED")

    if r.kind == "PART":
        _draw_part(layout, context, obj)
    elif r.kind == "LIGHT":
        layout.prop(obj, "name", text="Name")
        _draw_light(layout, obj)
    elif r.kind == "RIG":
        layout.prop(obj, "name", text="Name")
        layout.label(text="%d joints (bones)" % len(obj.data.bones), icon="BONE_DATA")
        row = layout.row()
        row.operator("object.mode_set", text="Pose Mode", icon="POSE_HLT").mode = "POSE"
        row.operator("object.mode_set", text="Object Mode", icon="OBJECT_DATA").mode = "OBJECT"
    else:
        col = _section(layout, "Data", "OBJECT_DATA")
        col.prop(obj, "name", text="Name")
        col.prop(r, "position", text="Pivot Position")
        col.prop(r, "orientation", text="Pivot Orientation")


def _draw_part(layout, context, obj):
    r = obj.rblx

    col = _section(layout, "Appearance", "SHADING_RENDERED")
    col.prop(r, "brick_color")
    col.prop(r, "cast_shadow")
    col.prop(r, "color")
    sub = col.row()
    sub.enabled = r.material_mode != "SURFACE"
    sub.prop(r, "material")
    if r.material_mode == "SURFACE":
        row = col.row()
        row.label(text="Custom material / SurfaceAppearance", icon="MATERIAL")
        row.operator("rblx.use_roblox_material", text="", icon="LOOP_BACK")
    col.prop(r, "reflectance", slider=True)
    col.prop(r, "transparency", slider=True)

    col = _section(layout, "Data", "OBJECT_DATA")
    row = col.row()
    row.enabled = False
    row.prop(r, "class_name", text="ClassName")
    col.prop(obj, "name", text="Name")
    col.prop(r, "position")
    col.prop(r, "orientation")

    col = _section(layout, "Behavior", "PHYSICS")
    grid = col.grid_flow(columns=2, even_columns=True)
    for p in ("anchored", "can_collide", "can_touch", "can_query", "locked", "massless"):
        grid.prop(r, p)

    col = _section(layout, "Part", "MESH_CUBE")
    if r.shape not in ("MESH", "UNION"):
        col.prop(r, "shape")
    else:
        col.label(text="Shape: " + dict((s[0], s[1]) for s in SHAPE_ITEMS)[r.shape])
    col.prop(r, "size")
    if _scale_mismatch(obj):
        warn = col.column()
        warn.alert = True
        warn.label(text="Object is scaled in Blender", icon="ERROR")
        warn.operator("rblx.sync_size", icon="FULLSCREEN_ENTER")
    if r.mesh_id:
        row = col.row()
        row.enabled = False
        row.prop(r, "mesh_id")
    if r.asset_missing:
        warn = col.column()
        warn.alert = True
        warn.label(text="Some assets are missing", icon="ERROR")
        warn.operator("rblx.reload_assets", icon="FILE_REFRESH")

    if len(context.selected_objects) > 1:
        layout.operator("rblx.copy_to_selected", icon="PASTEDOWN")


def _draw_light(layout, obj):
    col = layout.column()
    if obj.type == "LIGHT":
        col.prop(obj.data, "color")
        col.prop(obj.data, "energy")
        if obj.data.type == "SPOT":
            col.prop(obj.data, "spot_size", text="Angle")
        col.prop(obj.data, "use_shadow", text="Shadows")
    r = obj.rblx
    col.label(text="Roblox Brightness %.2f, Range %.1f" % (r.light_brightness, r.light_range))


class RBLX_PT_properties(_RBLXPanel, bpy.types.Panel):
    bl_label = "Properties"
    bl_order = 0

    def draw(self, context):
        draw_properties(self.layout, context, context.active_object)


class RBLX_PT_object_properties(bpy.types.Panel):
    bl_label = "Roblox"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.rblx.kind != "NONE"

    def draw(self, context):
        draw_properties(self.layout, context, context.object)
        if context.object.rblx.kind == "PART":
            self.layout.separator()
            draw_textures(self.layout, context, context.object)


# ---------------------------------------------------------------------------
# Textures

_MAPPING_ICONS = {"UV": "UV", "FACE": "IMAGE_PLANE", "TILED": "TEXTURE", "TEMPLATE": "MOD_CLOTH"}


class RBLX_UL_layers(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        if item.missing or item.image is None:
            row.alert = True
        label = item.name
        if item.mapping in ("FACE", "TILED"):
            label += "  [%s]" % item.face.title()
        row.label(text=label, icon=_MAPPING_ICONS.get(item.mapping, "IMAGE_DATA"))
        row.label(text=item.kind)

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        n = len(items)
        # Show the top-most layer first, like a layer stack
        return [], [n - 1 - i for i in range(n)]


def draw_textures(layout, context, obj):
    r = obj.rblx
    row = layout.row()
    row.template_list("RBLX_UL_layers", "", r, "layers", r, "active_layer", rows=3)
    col = row.column(align=True)
    col.operator("rblx.layer_add", text="", icon="ADD")
    col.operator("rblx.layer_remove", text="", icon="REMOVE")
    col.separator()
    col.operator("rblx.layer_move", text="", icon="TRIA_UP").direction = "UP"
    col.operator("rblx.layer_move", text="", icon="TRIA_DOWN").direction = "DOWN"

    if not r.layers:
        layout.label(text="Add an image, or drag one onto the part", icon="INFO")
        return
    layer = r.layers[min(r.active_layer, len(r.layers) - 1)]
    box = layout.box()
    col = box.column()
    col.prop(layer, "name")
    col.template_ID(layer, "image", open="image.open")
    if layer.missing:
        warn = col.column()
        warn.alert = True
        warn.label(text="Image not found: " + (layer.source or "?"), icon="ERROR")
    col.prop(layer, "mapping")
    if layer.mapping in ("FACE", "TILED"):
        col.prop(layer, "face")
    if layer.mapping == "TEMPLATE" and r.shape in ("BLOCK", "TRUSS"):
        col.prop(layer, "template_region")
    col.prop(layer, "color")
    col.prop(layer, "transparency", slider=True)
    if layer.mapping == "TILED":
        sub = col.column(align=True)
        sub.prop(layer, "studs_per_tile_u")
        sub.prop(layer, "studs_per_tile_v")
        sub = col.column(align=True)
        sub.prop(layer, "offset_studs_u")
        sub.prop(layer, "offset_studs_v")

    col = box.column(align=True)
    row = col.row(align=True)
    row.operator("rblx.layer_replace", icon="FILEBROWSER")
    row.operator("rblx.layer_make_unique", icon="DUPLICATE")
    row = col.row(align=True)
    row.operator("rblx.layer_edit", icon="IMAGE")
    row.operator("rblx.layer_paint", icon="BRUSH_DATA")
    row = col.row(align=True)
    row.operator("rblx.layer_save", icon="FILE_TICK")
    row.operator("rblx.layer_pack", icon="PACKAGE")


class RBLX_PT_textures(_RBLXPanel, bpy.types.Panel):
    bl_label = "Textures"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.rblx.kind == "PART"

    def draw(self, context):
        draw_textures(self.layout, context, context.active_object)


# ---------------------------------------------------------------------------
# Characters & inserting

class RBLX_PT_character(_RBLXPanel, bpy.types.Panel):
    bl_label = "Character"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and (_character_root(o) is not None or o.rblx.kind == "RIG")

    def draw(self, context):
        layout = self.layout
        o = context.active_object
        root = _character_root(o) or o
        layout.label(text=root.name, icon="ARMATURE_DATA")
        col = layout.column(align=True)
        col.operator("rblx.apply_clothing", text="Add Shirt", icon="MOD_CLOTH").kind = "SHIRT"
        col.operator("rblx.apply_clothing", text="Add Pants", icon="MOD_CLOTH").kind = "PANTS"
        col.operator("rblx.apply_clothing", text="Add T-Shirt", icon="IMAGE_PLANE").kind = "TSHIRT"
        rig = next((c for c in root.children if c.rblx.kind == "RIG"), None) \
            if root.rblx.kind != "RIG" else root
        if rig is not None:
            layout.label(text="Rig: " + rig.name, icon="BONE_DATA")
            layout.label(text="Select the rig and use Pose Mode to animate")


class RBLX_PT_add(_RBLXPanel, bpy.types.Panel):
    bl_label = "Insert"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, even_columns=True, align=True)
        for ident, label, _d, icon, _n in SHAPE_ITEMS:
            if ident in ("MESH", "UNION"):
                continue
            grid.operator("rblx.add_part", text=label, icon=icon).shape = ident
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator("rblx.add_character", text="R6 Character", icon="ARMATURE_DATA").rig_type = "R6"
        row.operator("rblx.add_character", text="R15 Character", icon="ARMATURE_DATA").rig_type = "R15"
        col.operator("rblx.import_avatar", text="Avatar from Username...", icon="USER")


# ---------------------------------------------------------------------------
# Lighting

class RBLX_PT_lighting(_RBLXPanel, bpy.types.Panel):
    bl_label = "Lighting"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        L = context.scene.rblx_lighting
        row = layout.row(align=True)
        row.operator_menu_enum("rblx.lighting_preset", "preset", text="Presets", icon="PRESET")
        row.operator("rblx.load_lighting", text="", icon="FILEBROWSER")
        row = layout.row(align=True)
        row.prop(L, "live_update")
        row.operator("rblx.apply_lighting", text="Apply", icon="FILE_REFRESH")

        col = _section(layout, "Sun & Time", "LIGHT_SUN")
        col.prop(L, "clock_time", slider=True)
        col.prop(L, "geographic_latitude")
        col.prop(L, "brightness")
        col.prop(L, "sun_strength_multiplier")
        col.prop(L, "global_shadows")
        col.prop(L, "shadow_softness", slider=True)

        col = _section(layout, "Ambient", "WORLD")
        col.prop(L, "ambient")
        col.prop(L, "outdoor_ambient")
        col.prop(L, "color_shift_top")
        col.prop(L, "color_shift_bottom")
        col.prop(L, "environment_diffuse_scale", slider=True)
        col.prop(L, "environment_specular_scale", slider=True)
        col.prop(L, "exposure_compensation")


class RBLX_PT_lighting_sky(_RBLXPanel, bpy.types.Panel):
    bl_label = "Sky, Fog & Atmosphere"
    bl_parent_id = "RBLX_PT_lighting"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        L = context.scene.rblx_lighting
        col = _section(layout, "Sky", "OUTLINER_OB_LIGHTPROBE")
        col.prop(L, "sky_mode", text="")
        if L.sky_mode == "IMAGE":
            col.prop(L, "sky_image")
        col.prop(L, "sky_strength")
        col.prop(L, "celestial_bodies_shown")
        col.prop(L, "sun_angular_size")

        col = _section(layout, "Fog", "MOD_FLUID")
        col.prop(L, "fog_color")
        col.prop(L, "fog_start")
        col.prop(L, "fog_end")

        col = _section(layout, "Atmosphere", "MOD_OCEAN")
        col.prop(L, "atmosphere_density", slider=True)
        col.prop(L, "atmosphere_color")
        col.prop(L, "atmosphere_haze")


# ---------------------------------------------------------------------------
# Import / assets

class RBLX_PT_import(_RBLXPanel, bpy.types.Panel):
    bl_label = "Import & Assets"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        layout.operator("import_scene.rblx", text="Import Roblox File", icon="IMPORT")
        layout.prop(context.scene.rblx, "stud_scale")

        p = prefs.get()
        col = _section(layout, "Downloads", "URL")
        if p is not None:
            if p.api_key.strip():
                col.label(text="API key set", icon="CHECKMARK")
            else:
                warn = col.column()
                warn.alert = True
                warn.label(text="No API key: meshes/images can't download", icon="ERROR")
            col.prop(p, "api_key", text="Key")
            col.operator("wm.url_open", text="Create an API key",
                         icon="URL").url = prefs.API_KEY_URL
            if not assets.online_allowed():
                warn = col.column()
                warn.alert = True
                warn.label(text="Online access is off in Blender", icon="ERROR")
        col = _section(layout, "Local Files", "FILE_FOLDER")
        if p is not None:
            col.prop(p, "asset_folder", text="")
            col.prop(p, "material_folder", text="Materials")
        col.operator("rblx.reload_assets", icon="FILE_REFRESH")
        missing = sum(1 for o in context.scene.objects if o.rblx.asset_missing)
        if missing:
            warn = col.column()
            warn.alert = True
            warn.label(text="%d object(s) missing assets" % missing, icon="ERROR")
        if bpy.data.texts.get("RBX Import Report"):
            col.label(text="Report: Text Editor > RBX Import Report", icon="TEXT")


CLASSES = (
    RBLX_UL_layers,
    RBLX_PT_properties,
    RBLX_PT_object_properties,
    RBLX_PT_textures,
    RBLX_PT_character,
    RBLX_PT_add,
    RBLX_PT_lighting,
    RBLX_PT_lighting_sky,
    RBLX_PT_import,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
