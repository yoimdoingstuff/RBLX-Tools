"""Finds local files for Roblox asset references (rbxassetid://, asset URLs,
rbxasset:// built-ins). Nothing is downloaded: assets must already be on disk
(your asset folder, or Roblox Studio's own content folder)."""

import glob
import os
import re

import bpy

from . import prefs

_ID_PATTERNS = (
    re.compile(r"rbxassetid://(\d+)", re.I),
    re.compile(r"[?&]id=(\d+)", re.I),
    re.compile(r"/asset/(\d+)", re.I),
    re.compile(r"^\s*(\d+)\s*$"),
)
_NAME_ID = re.compile(r"(\d{5,})")
_MAX_FILES = 200000


def asset_id(content):
    if not content:
        return None
    for pat in _ID_PATTERNS:
        m = pat.search(content)
        if m:
            return m.group(1)
    return None


def studio_content_dirs():
    """Roblox Studio 'content' folders, newest install first."""
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Roblox", "Versions"))
    roots.append(os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                              "Roblox", "Versions"))
    roots.append("/Applications/RobloxStudio.app/Contents/Resources")
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        if os.path.isdir(os.path.join(root, "content")) and root.endswith("Resources"):
            found.append(os.path.join(root, "content"))
            continue
        for ver in glob.glob(os.path.join(root, "version-*")):
            content = os.path.join(ver, "content")
            if os.path.isfile(os.path.join(ver, "RobloxStudioBeta.exe")) and os.path.isdir(content):
                found.append(content)
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


class AssetResolver:
    def __init__(self, folders=(), use_studio=True):
        self.folders = [os.path.normpath(bpy.path.abspath(f)) for f in folders if f]
        self.folders = [f for f in self.folders if os.path.isdir(f)]
        self.studio_dirs = studio_content_dirs() if use_studio else []
        self._index = None

    def _build_index(self):
        index = {}
        count = 0
        for folder in self.folders:
            for dirpath, _dirs, files in os.walk(folder):
                for fn in files:
                    count += 1
                    if count > _MAX_FILES:
                        break
                    stem = os.path.splitext(fn)[0]
                    path = os.path.join(dirpath, fn)
                    if stem.isdigit():
                        index[stem] = path  # exact id name wins
                        continue
                    for m in _NAME_ID.findall(stem):
                        index.setdefault(m, path)
        self._index = index

    def resolve(self, content):
        """Return a local file path for `content`, or None."""
        if not content:
            return None
        content = content.strip()
        local = bpy.path.abspath(content)
        if os.path.isfile(local):
            return local
        low = content.lower()
        if low.startswith("rbxasset://"):
            rel = content[len("rbxasset://"):].replace("\\", "/")
            for d in self.studio_dirs:
                p = os.path.join(d, *rel.split("/"))
                if os.path.isfile(p):
                    return p
            # Some built-ins live in the asset folder by name
            base = os.path.basename(rel)
            for folder in self.folders:
                p = os.path.join(folder, base)
                if os.path.isfile(p):
                    return p
            return None
        aid = asset_id(content)
        if aid is None:
            return None
        if self._index is None:
            self._build_index()
        return self._index.get(aid)


def default_resolver(extra_folder=None):
    p = prefs.get()
    folders = []
    if extra_folder:
        folders.append(extra_folder)
    if p and p.asset_folder:
        folders.append(p.asset_folder)
    use_studio = p.use_studio_content if p else True
    return AssetResolver(folders, use_studio)
