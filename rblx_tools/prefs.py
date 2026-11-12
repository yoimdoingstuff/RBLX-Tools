import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

ADDON_ID = __package__

API_KEY_URL = "https://create.roblox.com/dashboard/credentials"

# The .ROBLOSECURITY cookie is kept only in memory unless the user chooses to
# remember it. A get/set property backed by this variable is never saved to a
# .blend or preferences file.
_session_cookie = ""


def _get_session_cookie(self):
    return _session_cookie


def _set_session_cookie(self, value):
    global _session_cookie
    _session_cookie = value or ""


def _on_remember(self, context):
    global _session_cookie
    if self.remember_cookie:
        if _session_cookie and not self.cookie:
            self.cookie = _session_cookie
        _session_cookie = ""
    else:
        if self.cookie:
            _session_cookie = self.cookie
        self.cookie = ""


def get_cookie():
    p = get()
    if p is not None and p.remember_cookie:
        return p.cookie or ""
    return _session_cookie


def cookie_owner():
    """(data, property name) to draw the cookie field with."""
    p = get()
    if p is not None and p.remember_cookie:
        return p, "cookie"
    return bpy.context.window_manager, "rblx_session_cookie"


def _on_panel_location(self, context):
    from . import panels
    panels.reregister()


PANEL_LOCATIONS = [
    ("PROPERTIES", "Properties Editor (Tool tab)",
     "Show the Roblox panels in the Properties Editor's Tool tab, next to Render, Modifiers, ... "
     "so the 3D View sidebar can stay closed"),
    ("SIDEBAR", "3D View Sidebar (Roblox tab)", "Show the Roblox panels in the 3D View's N panel"),
]


class RBLX_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    panel_location: EnumProperty(
        name="Roblox Panels", items=PANEL_LOCATIONS, default="PROPERTIES",
        update=_on_panel_location,
        description="Where the Roblox panels are shown")
    studio_camera: BoolProperty(
        name="Studio Camera Controls", default=True,
        description="In Build Mode: WASD/QE to move, hold right mouse to look, middle mouse to "
                    "pan, scroll to zoom toward the cursor, like Roblox Studio. Off: Blender's "
                    "own navigation")
    camera_speed: FloatProperty(
        name="Camera Speed", default=20.0, min=0.5, max=2000.0, soft_max=200.0,
        description="Studio camera speed in studs per second (scroll while moving to change it)")

    api_key: StringProperty(
        name="Open Cloud API Key", subtype="PASSWORD", default="",
        description="Your own Roblox Open Cloud API key, used to download meshes and textures. "
                    "Create one at create.roblox.com > Dashboard > Credentials with the "
                    "legacy-asset:manage permission. Stored in your Blender preferences")
    cookie: StringProperty(
        name=".ROBLOSECURITY", subtype="PASSWORD", default="",
        description="Saved copy of your .ROBLOSECURITY cookie (only when Remember is on)")
    remember_cookie: BoolProperty(
        name="Remember Cookie", default=False, update=_on_remember,
        description="Save the cookie in your Blender preferences (plain text on this computer). "
                    "Off: it's forgotten when Blender closes")
    allow_anonymous: BoolProperty(
        name="Try Without Login", default=True,
        description="Also try downloading without credentials. Works for Roblox-made assets "
                    "(default body meshes, many built-in textures)")
    download_assets: BoolProperty(
        name="Download Missing Assets", default=True,
        description="Download meshes and textures that aren't on disk yet (needs Blender's online "
                    "access)")
    library_folder: StringProperty(
        name="Asset Library", subtype="DIR_PATH", default="",
        description="Where downloaded meshes, textures and models are saved for future use "
                    "(sorted into meshes/, textures/, models/). Empty: the add-on's own folder")
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
        self.layout.prop(self, "panel_location")
        row = self.layout.row()
        row.prop(self, "studio_camera")
        row.prop(self, "camera_speed")
        draw_download_settings(self.layout, context, full=True)

        from . import assets, draco
        box = self.layout.box()
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


def draw_download_settings(layout, context, full=False):
    """Shared by the preferences and the sidebar panel."""
    from . import assets
    p = get()
    if p is None:
        return
    box = layout.box()
    box.label(text="Downloading meshes & textures", icon="URL")
    col = box.column()
    col.label(text=assets.describe_access(), icon="INFO")

    col.label(text="1. Open Cloud API key (recommended)")
    col.prop(p, "api_key", text="API Key")
    col.operator("wm.url_open", text="Create an API key", icon="URL").url = API_KEY_URL
    if full:
        col.label(text="   Give it the 'legacy-asset:manage' permission (Assets API).")

    col.separator()
    col.label(text="2. Or your .ROBLOSECURITY cookie")
    owner, prop = cookie_owner()
    col.prop(owner, prop, text="Cookie")
    col.prop(p, "remember_cookie")
    warn = col.column()
    warn.scale_y = 0.8
    warn.label(text="Never share your cookie:", icon="ERROR")
    warn.label(text="it gives full access to your account.")
    if full:
        warn.label(text="It's only sent to assetdelivery.roblox.com. Roblox recommends API keys;")
        warn.label(text="cookie downloads may stop working if Roblox removes them.")

    col.separator()
    col.prop(p, "allow_anonymous")
    col.prop(p, "download_assets")
    if not assets.online_allowed():
        w = col.column()
        w.alert = True
        w.label(text="Blender's online access is off: Preferences > System > Network",
                icon="ERROR")
    col.operator("rblx.test_download", icon="IMPORT")

    box = layout.box()
    box.label(text="Asset library (downloads are kept here)", icon="ASSET_MANAGER")
    col = box.column()
    col.prop(p, "library_folder", text="")
    lib = assets.library_dir()
    stats = assets.library_stats(lib)
    col.label(text="%d meshes, %d textures, %d models" % (stats["meshes"], stats["textures"],
                                                           stats["models"]))
    row = col.row(align=True)
    row.operator("wm.path_open", text="Open Folder", icon="FILE_FOLDER").filepath = lib
    row.operator("rblx.clear_cache", text="Clear", icon="TRASH")


def get():
    try:
        return bpy.context.preferences.addons[ADDON_ID].preferences
    except (KeyError, AttributeError):
        return None


def register():
    bpy.utils.register_class(RBLX_AddonPreferences)
    bpy.types.WindowManager.rblx_session_cookie = StringProperty(
        name=".ROBLOSECURITY", subtype="PASSWORD", get=_get_session_cookie,
        set=_set_session_cookie, options={"SKIP_SAVE"},
        description="Your .ROBLOSECURITY cookie, kept in memory for this Blender session only")


def unregister():
    del bpy.types.WindowManager.rblx_session_cookie
    bpy.utils.unregister_class(RBLX_AddonPreferences)
