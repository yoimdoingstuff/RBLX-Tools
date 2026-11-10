# RBLX-Tools: Roblox workflow tools for Blender.
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "RBLX Tools",
    "author": "RBLX-Tools contributors",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Roblox, File > Import > Roblox, Add > Roblox",
    "description": "Import Roblox models, places and avatars; Roblox lighting, part properties "
                   "and textures",
    "category": "Import-Export",
}

import sys

# When the add-on is updated or re-enabled without restarting Blender, Python
# still holds the previous version's submodules (e.g. rblx_tools.rbx.mesh),
# and the new code would mix with the old. Drop them so everything below is
# imported fresh from the installed files.
for _name in [n for n in sys.modules if n.startswith(__name__ + ".")]:
    del sys.modules[_name]

import bpy

from . import (assets, character, coords, download, draco, geometry, importer, lighting,
               materials, operators, panels, prefs, props, rbx)

_MODULES = (draco, prefs, props, lighting, operators, panels)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
