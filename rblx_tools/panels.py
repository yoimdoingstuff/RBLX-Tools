"""Sidebar UI: View3D > Sidebar (N) > Roblox."""

import bpy

from . import prefs
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


# ---------------------------------------------------------------------------
# Properties

class RBLX_PT_properties(_RBLXPanel, bpy.types.Panel):
    bl_label = "Properties"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if obj is None:
            layout.label(text="Select an object", icon="INFO")
            return
        r = obj.rblx
        if r.kind == "NONE":
            layout.label(text=obj.name + " is not a Roblox object", icon="INFO")
            if obj.type == "MESH":
                layout.operator("rblx.convert_to_part", icon="MESH_CUBE")
            return

        row = layout.row()
        row.label(text=r.class_name or r.kind.title(), icon=_kind_icon(r.kind))
        layout.prop(obj, "name", text="Name")

        if r.kind == "PART":
            _draw_part(layout, context, obj)
        elif r.kind in ("DECAL", "TEXTURE"):
            _draw_decal(layout, obj)
        elif r.kind == "LIGHT":
            _draw_light(layout, obj)
        else:
            col = layout.column(align=True)
            col.prop(r, "position", text="Pivot Position")
            col = layout.column(align=True)
            col.prop(r, "orientation", text="Pivot Orientation")


def _kind_icon(kind):
    return {"PART": "MESH_CUBE", "DECAL": "IMAGE_DATA", "TEXTURE": "TEXTURE",
            "MODEL": "OUTLINER_OB_EMPTY", "LIGHT": "LIGHT", "ATTACHMENT": "EMPTY_AXIS"}.get(kind, "DOT")


def _section(layout, title, icon):
    box = layout.box()
    box.label(text=title, icon=icon)
    return box.column()


def _draw_part(layout, context, obj):
    r = obj.rblx

    col = _section(layout, "Appearance", "SHADING_RENDERED")
    col.prop(r, "color")
    sub = col.row()
    sub.enabled = r.material_mode == "BASIC"
    sub.prop(r, "material")
    if r.material_mode != "BASIC":
        col.label(text="Surface: " + {"TEXTURED": "TextureID image",
                                      "SURFACE": "Custom / SurfaceAppearance"}[r.material_mode],
                  icon="TEXTURE")
    col.prop(r, "transparency", slider=True)
    col.prop(r, "reflectance", slider=True)
    col.prop(r, "cast_shadow")

    col = _section(layout, "Data", "OBJECT_DATA")
    col.prop(r, "position")
    col.prop(r, "orientation")
    col.prop(r, "size")
    if r.shape not in ("MESH", "UNION"):
        col.prop(r, "shape")
    else:
        col.label(text="Shape: " + dict((s[0], s[1]) for s in SHAPE_ITEMS)[r.shape])
    if _scale_mismatch(obj):
        warn = col.column()
        warn.alert = True
        warn.label(text="Object is scaled in Blender", icon="ERROR")
        warn.operator("rblx.sync_size", icon="FULLSCREEN_ENTER")

    col = _section(layout, "Behavior", "PHYSICS")
    grid = col.grid_flow(columns=2, even_columns=True)
    for p in ("anchored", "can_collide", "can_touch", "can_query", "locked", "massless"):
        grid.prop(r, p)

    col = _section(layout, "Assets", "FILE_IMAGE")
    if r.mesh_id:
        row = col.row()
        row.enabled = False
        row.prop(r, "mesh_id")
    col.prop(r, "texture_id")
    op = col.operator("rblx.add_texture", text="Browse Image...", icon="FILEBROWSER")
    op.mode = "PART"
    if r.asset_missing:
        warn = col.column()
        warn.alert = True
        warn.label(text="Asset not found in your Asset Folder", icon="ERROR")

    if len(context.selected_objects) > 1:
        layout.operator("rblx.copy_to_selected", icon="PASTEDOWN")


def _draw_decal(layout, obj):
    r = obj.rblx
    col = layout.column()
    col.prop(r, "face")
    col.prop(r, "color", text="Color3")
    col.prop(r, "transparency", slider=True)
    col.prop(r, "texture_id", text="Texture")
    if r.kind == "TEXTURE":
        sub = col.column(align=True)
        sub.prop(r, "studs_per_tile_u")
        sub.prop(r, "studs_per_tile_v")
        sub = col.column(align=True)
        sub.prop(r, "offset_studs_u")
        sub.prop(r, "offset_studs_v")
    if r.asset_missing:
        warn = col.column()
        warn.alert = True
        warn.label(text="Image not found in your Asset Folder", icon="ERROR")


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


class RBLX_PT_add(_RBLXPanel, bpy.types.Panel):
    bl_label = "Insert"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, even_columns=True, align=True)
        for ident, label, _d, icon, _n in SHAPE_ITEMS:
            if ident in ("MESH", "UNION"):
                continue
            grid.operator("rblx.add_part", text=label, icon=icon).shape = ident


# ---------------------------------------------------------------------------
# Lighting

class RBLX_PT_lighting(_RBLXPanel, bpy.types.Panel):
    bl_label = "Lighting"
    bl_order = 2

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
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        layout.operator("import_scene.rblx", text="Import Roblox File", icon="IMPORT")
        layout.prop(context.scene.rblx, "stud_scale")

        p = prefs.get()
        col = _section(layout, "Assets", "FILE_FOLDER")
        if p is not None:
            col.prop(p, "asset_folder", text="")
            col.label(text="Name files by asset id, e.g. 12345678.png")
            col.prop(p, "material_folder", text="Materials")
        col.operator("rblx.add_texture", icon="IMAGE_DATA")
        col.operator("rblx.reload_assets", icon="FILE_REFRESH")
        missing = sum(1 for o in context.scene.objects if o.rblx.asset_missing)
        if missing:
            warn = col.column()
            warn.alert = True
            warn.label(text="%d object(s) missing assets" % missing, icon="ERROR")
        if bpy.data.texts.get("RBX Import Report"):
            col.label(text="Report: Text Editor > RBX Import Report", icon="TEXT")


CLASSES = (
    RBLX_PT_properties,
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
