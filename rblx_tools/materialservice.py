"""MaterialService in Blender: Use2022Materials and MaterialVariants.

A MaterialVariant is a custom look for one of Roblox's materials (its
BaseMaterial) made of ColorMap / NormalMap / RoughnessMap / MetalnessMap
images tiled every StudsPerTile studs. Parts use one through their
MaterialVariant property, or every part of that material uses it when
MaterialService overrides the material (MaterialService.<Material>Name)."""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

from .props import MATERIAL_ITEMS

MAP_ROLES = (("color", "ColorMap"), ("normal", "NormalMap"), ("roughness", "RoughnessMap"),
             ("metalness", "MetalnessMap"))


def _refresh_parts(context=None):
    from . import materials
    scene = getattr(context, "scene", None) or bpy.context.scene
    for obj in scene.objects:
        if obj.rblx.kind == "PART" and obj.type == "MESH" and obj.rblx.material_mode != "SURFACE":
            materials.refresh(obj)


def _on_variant(self, context):
    if getattr(_on_variant, "suspended", False):
        return
    _refresh_parts(context)


def _on_map_source(self, context):
    """Asset id / file typed for a map: load it."""
    if getattr(_on_variant, "suspended", False):
        return
    for role, _label in MAP_ROLES:
        src = getattr(self, role + "_source")
        img = getattr(self, role + "_map")
        if src and (img is None or img.get("rblx_source") != src):
            setattr(self, role + "_map", load_map(src))
    _refresh_parts(context)


def load_map(content, resolver=None):
    import os
    from . import assets, materials
    content = (content or "").strip()
    if not content:
        return None
    if os.path.isfile(bpy.path.abspath(content)):
        path = bpy.path.abspath(content)
    else:
        try:
            path = (resolver or assets.default_resolver("", True)).resolve_image(content)
        except Exception:
            path = None
    img = materials.load_image(path) if path else None
    if img is not None:
        img["rblx_source"] = content
    return img


class RBLX_MaterialVariant(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="MaterialVariant", update=_on_variant)
    base_material: EnumProperty(name="BaseMaterial", items=MATERIAL_ITEMS, default="Plastic",
                                update=_on_variant)
    studs_per_tile: FloatProperty(name="StudsPerTile", default=10.0, min=0.01, soft_max=200.0,
                                  update=_on_variant)
    override: BoolProperty(name="Override Material", default=False, update=_on_variant,
                           description="MaterialService.<BaseMaterial>Name: every part of the base "
                                       "material uses this variant")
    color_map: PointerProperty(name="ColorMap", type=bpy.types.Image, update=_on_variant)
    normal_map: PointerProperty(name="NormalMap", type=bpy.types.Image, update=_on_variant)
    roughness_map: PointerProperty(name="RoughnessMap", type=bpy.types.Image, update=_on_variant)
    metalness_map: PointerProperty(name="MetalnessMap", type=bpy.types.Image, update=_on_variant)
    color_source: StringProperty(name="ColorMap", default="", update=_on_map_source,
                                 description="Asset id, rbxassetid:// or an image file")
    normal_source: StringProperty(name="NormalMap", default="", update=_on_map_source)
    roughness_source: StringProperty(name="RoughnessMap", default="", update=_on_map_source)
    metalness_source: StringProperty(name="MetalnessMap", default="", update=_on_map_source)


def variants(scene=None):
    scene = scene or bpy.context.scene
    return getattr(scene, "rblx_variants", [])


def variant_for(obj, scene=None):
    """The MaterialVariant a part should use, or None (Roblox: a variant only
    applies to parts of its BaseMaterial)."""
    r = obj.rblx
    vs = variants(scene)
    if not vs:
        return None
    if r.material_variant:
        v = next((v for v in vs if v.name == r.material_variant), None)
        if v is not None and v.base_material == r.material:
            return v
    return next((v for v in vs if v.override and v.base_material == r.material), None)


def import_material_service(scene, inst, resolver=None, report=None):
    """Read a MaterialService instance: Use2022Materials, its MaterialVariants and
    the material overrides (<Material>Name properties)."""
    use = inst.get("Use2022Materials", "Use2022MaterialsXml")
    if isinstance(use, bool) and use != scene.rblx.use_2022_materials:
        scene.rblx.use_2022_materials = use
    _on_variant.suspended = True
    try:
        names = {}
        for v_inst in (d for d in inst.descendants() if d.class_name == "MaterialVariant"):
            v = scene.rblx_variants.add()
            v.name = v_inst.name
            from .rbx import enums
            base = enums.MATERIALS.get(v_inst.get("BaseMaterial", default=256), "Plastic")
            v.base_material = base if base in {m[0] for m in MATERIAL_ITEMS} else "Plastic"
            spt = v_inst.get("StudsPerTile")
            if isinstance(spt, (int, float)):
                v.studs_per_tile = max(float(spt), 0.01)
            for role, prop in MAP_ROLES:
                content = v_inst.get(prop, prop + "Content", default="")
                if isinstance(content, str) and content.strip():
                    setattr(v, role + "_source", content.strip())
                    img = load_map(content, resolver)
                    setattr(v, role + "_map", img)
                    if img is None and report is not None:
                        report.miss(content.strip(), v.name,
                                    resolver.error_for(content.strip()) if resolver else None)
            names[v.name] = v
            if report is not None:
                report.count("material variants")
        from .rbx import enums
        for mat_name in set(enums.MATERIALS.values()):
            override = inst.get(mat_name + "Name")
            if isinstance(override, str) and override and override != mat_name and override in names:
                names[override].override = True
    finally:
        _on_variant.suspended = False


class RBLX_UL_variants(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="MATERIAL")
        row.label(text=item.base_material)
        if item.override:
            row.label(text="", icon="PINNED")


class RBLX_OT_variant_add(bpy.types.Operator):
    """Add a MaterialVariant (a custom look for one of Roblox's materials)"""
    bl_idname = "rblx.variant_add"
    bl_label = "Add MaterialVariant"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        v = context.scene.rblx_variants.add()
        obj = context.active_object
        if obj is not None and obj.rblx.kind == "PART":
            v.base_material = obj.rblx.material
        v.name = "%s Variant %d" % (v.base_material, len(context.scene.rblx_variants))
        context.scene.rblx_variant_index = len(context.scene.rblx_variants) - 1
        return {"FINISHED"}


class RBLX_OT_variant_remove(bpy.types.Operator):
    """Remove the selected MaterialVariant"""
    bl_idname = "rblx.variant_remove"
    bl_label = "Remove MaterialVariant"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.rblx_variants) > 0

    def execute(self, context):
        s = context.scene
        s.rblx_variants.remove(min(s.rblx_variant_index, len(s.rblx_variants) - 1))
        s.rblx_variant_index = max(0, s.rblx_variant_index - 1)
        _refresh_parts(context)
        return {"FINISHED"}


class RBLX_OT_variant_assign(bpy.types.Operator):
    """Use the selected MaterialVariant on the selected parts (sets their Material too)"""
    bl_idname = "rblx.variant_assign"
    bl_label = "Use on Selected Parts"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.rblx_variants) > 0 and any(
            o.rblx.kind == "PART" for o in context.selected_objects)

    def execute(self, context):
        from .props import no_propagation
        s = context.scene
        v = s.rblx_variants[min(s.rblx_variant_index, len(s.rblx_variants) - 1)]
        with no_propagation():
            for o in context.selected_objects:
                if o.rblx.kind == "PART":
                    o.rblx.material = v.base_material
                    o.rblx.material_variant = v.name
        return {"FINISHED"}


def draw_textures(layout):
    """Roblox's own material textures: status, download, on/off."""
    from . import prefs, robloxmats
    from .operators import texture_install_status
    box = layout.box()
    col = box.column()
    status, running = texture_install_status()
    p = prefs.get()
    if running:
        col.label(text=status or "Downloading...", icon="SORTTIME")
    elif robloxmats.installed():
        col.label(text="Roblox textures installed", icon="CHECKMARK")
        if p is not None:
            col.prop(p, "use_roblox_textures", text="Use Roblox's Textures")
        row = col.row(align=True)
        row.operator("rblx.install_material_textures", text="Update", icon="FILE_REFRESH")
        row.operator("rblx.rebuild_materials", text="Rebuild", icon="MATERIAL")
    else:
        col.label(text="Using stand-in textures", icon="INFO")
        col.operator("rblx.install_material_textures", icon="IMPORT")
        sub = col.column()
        sub.scale_y = 0.8
        sub.label(text="Roblox's real material, terrain and water")
        sub.label(text="textures (~60 MB from Roblox's CDN, once)")
    if status.startswith("Download failed"):
        warn = col.column()
        warn.alert = True
        warn.label(text=status, icon="ERROR")


def draw_material_service(layout, context):
    s = context.scene
    draw_textures(layout)
    layout.prop(s.rblx, "use_2022_materials", text="Use2022Materials")
    row = layout.row()
    row.template_list("RBLX_UL_variants", "", s, "rblx_variants", s, "rblx_variant_index", rows=3)
    col = row.column(align=True)
    col.operator("rblx.variant_add", text="", icon="ADD")
    col.operator("rblx.variant_remove", text="", icon="REMOVE")
    if not len(s.rblx_variants):
        layout.label(text="No MaterialVariants", icon="INFO")
        return
    v = s.rblx_variants[min(s.rblx_variant_index, len(s.rblx_variants) - 1)]
    box = layout.box()
    col = box.column()
    col.prop(v, "name")
    col.prop(v, "base_material")
    col.prop(v, "studs_per_tile")
    col.prop(v, "override")
    for role, label in MAP_ROLES:
        sub = col.column(align=True)
        sub.prop(v, role + "_source", text=label)
        sub.template_ID(v, role + "_map", open="image.open")
    col.operator("rblx.variant_assign", icon="CHECKMARK")


CLASSES = (RBLX_MaterialVariant, RBLX_UL_variants, RBLX_OT_variant_add, RBLX_OT_variant_remove,
           RBLX_OT_variant_assign)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.rblx_variants = CollectionProperty(type=RBLX_MaterialVariant)
    bpy.types.Scene.rblx_variant_index = IntProperty(default=0, min=0)


def unregister():
    del bpy.types.Scene.rblx_variant_index
    del bpy.types.Scene.rblx_variants
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
