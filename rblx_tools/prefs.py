import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty

ADDON_ID = __package__


class RBLX_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    asset_folder: StringProperty(
        name="Asset Folder", subtype="DIR_PATH", default="",
        description="Folder with Roblox assets you've downloaded (images, .mesh files). "
                    "Files are matched by the asset id in their name, e.g. 12345678.png "
                    "or Sword_12345678.mesh. Subfolders are searched too")
    material_folder: StringProperty(
        name="Material Textures", subtype="DIR_PATH", default="",
        description="Optional folder of tileable textures for Roblox materials, named after "
                    "the material: Wood.png, Wood_normal.png, Wood_roughness.png, ...")
    material_tile_studs: FloatProperty(
        name="Material Tile Size", default=4.0, min=0.1, soft_max=64.0,
        description="How many studs one tile of a material texture covers")
    use_studio_content: BoolProperty(
        name="Use Roblox Studio Content", default=True,
        description="Resolve built-in rbxasset:// paths from your Roblox Studio install")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "asset_folder")
        col.prop(self, "material_folder")
        col.prop(self, "material_tile_studs")
        col.prop(self, "use_studio_content")
        from . import assets
        dirs = assets.studio_content_dirs()
        col.label(text="Studio content: " + (dirs[0] if dirs else "not found"),
                  icon="CHECKMARK" if dirs else "ERROR")


def get():
    try:
        return bpy.context.preferences.addons[ADDON_ID].preferences
    except (KeyError, AttributeError):
        return None


def register():
    bpy.utils.register_class(RBLX_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(RBLX_AddonPreferences)
