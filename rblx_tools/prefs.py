import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty

ADDON_ID = __package__

API_KEY_URL = "https://create.roblox.com/dashboard/credentials"


class RBLX_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    api_key: StringProperty(
        name="Open Cloud API Key", subtype="PASSWORD", default="",
        description="Your own Roblox Open Cloud API key, used to download meshes and images. "
                    "Create one at create.roblox.com > Dashboard > Credentials with the "
                    "legacy-asset:manage permission. Stored in your Blender preferences")
    download_assets: BoolProperty(
        name="Download Missing Assets", default=True,
        description="Download meshes and images that aren't on disk yet (needs an API key and "
                    "Blender's online access)")
    asset_folder: StringProperty(
        name="Asset Folder", subtype="DIR_PATH", default="",
        description="Optional folder with Roblox assets you've saved yourself (images, .mesh "
                    "files). Files are matched by the asset id in their name, e.g. 12345678.png "
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
        description="Use built-in files (rbxasset://, character rigs, head mesh) from your Roblox "
                    "Studio install")

    def draw(self, context):
        from . import assets, draco
        layout = self.layout

        box = layout.box()
        box.label(text="Downloading meshes & images", icon="URL")
        col = box.column()
        col.prop(self, "api_key")
        col.prop(self, "download_assets")
        row = col.row()
        row.operator("wm.url_open", text="Create an API key", icon="URL").url = API_KEY_URL
        col.label(text="Give the key the 'legacy-asset:manage' permission (Assets API).")
        if not assets.online_allowed():
            warn = col.column()
            warn.alert = True
            warn.label(text="Blender's online access is off: Preferences > System > Network",
                       icon="ERROR")
        col.label(text="Cache: " + assets.cache_dir(), icon="FILE_FOLDER")
        col.operator("rblx.clear_cache", icon="TRASH")

        box = layout.box()
        box.label(text="Local files", icon="FILE_FOLDER")
        col = box.column()
        col.prop(self, "asset_folder")
        col.prop(self, "material_folder")
        col.prop(self, "material_tile_studs")
        col.prop(self, "use_studio_content")
        dirs = assets.studio_version_dirs()
        col.label(text="Roblox Studio: " + (dirs[0] if dirs else "not found"),
                  icon="CHECKMARK" if dirs else "ERROR")
        col.label(text="Draco mesh decoder: " + ("available" if draco.available() else
                                                  (draco.load_error() or "missing")),
                  icon="CHECKMARK" if draco.available() else "ERROR")


def get():
    try:
        return bpy.context.preferences.addons[ADDON_ID].preferences
    except (KeyError, AttributeError):
        return None


def register():
    bpy.utils.register_class(RBLX_AddonPreferences)


def unregister():
    bpy.utils.unregister_class(RBLX_AddonPreferences)
