# RBLX-Tools: Roblox workflow tools for Blender.
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "RBLX Tools",
    "author": "RBLX-Tools contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Roblox, File > Import > Roblox",
    "description": "Import Roblox models/places, Roblox lighting, part properties and textures",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    for _m in ("rbx", "coords", "prefs", "assets", "props", "geometry", "materials",
               "lighting", "importer", "operators", "panels"):
        if _m in locals():
            importlib.reload(locals()[_m])

import bpy

from . import (assets, coords, geometry, importer, lighting, materials, operators, panels, prefs,
               props, rbx)

_MODULES = (prefs, props, lighting, operators, panels)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
