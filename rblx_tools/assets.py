"""Finds files for Roblox asset references (rbxassetid://, asset URLs,
rbxasset:// built-ins).

Lookup order: your Asset Folder -> the download cache -> Roblox Studio's
content folder (rbxasset://) -> download through Open Cloud (if an API key is
set in the add-on preferences and Blender's online access is allowed)."""

import glob
import os
import re

import bpy

from . import prefs
from .download import Downloader, sniff_extension

_ID_PATTERNS = (
    re.compile(r"rbxassetid://(\d+)", re.I),
    re.compile(r"[?&]id=(\d+)", re.I),
    re.compile(r"/asset/(\d+)", re.I),
    re.compile(r"^\s*(\d+)\s*$"),
)
_NAME_ID = re.compile(r"(\d{5,})")
_MAX_FILES = 200000

# Properties that point at the real image/mesh inside a downloaded model asset
# (e.g. a Decal id -> Decal.Texture, a Shirt id -> Shirt.ShirtTemplate).
_IMAGE_PROPS = ("Texture", "ShirtTemplate", "PantsTemplate", "Graphic", "TextureID", "TextureId",
                "ColorMap", "Image")
_MESH_PROPS = ("MeshId", "MeshID")


def asset_id(content):
    if not content:
        return None
    for pat in _ID_PATTERNS:
        m = pat.search(content)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Roblox Studio install

_LAUNCHERS = ("Roblox", "Bloxstrap", "Fishstrap", "Voidstrap", "Froststrap")


def studio_version_dirs():
    """Roblox Studio version folders, newest first (official installer and
    Bloxstrap-style launchers)."""
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots += [os.path.join(local, name, "Versions") for name in _LAUNCHERS]
    roots.append(os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                              "Roblox", "Versions"))
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for ver in glob.glob(os.path.join(root, "version-*")):
            if os.path.isfile(os.path.join(ver, "RobloxStudioBeta.exe")):
                found.append(ver)
    mac = "/Applications/RobloxStudio.app/Contents/Resources"
    if os.path.isdir(os.path.join(mac, "content")):
        found.append(mac)
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def studio_content_dirs():
    dirs = []
    for ver in studio_version_dirs():
        for sub in ("content", os.path.join("PlatformContent", "pc"), "ExtraContent"):
            p = os.path.join(ver, sub)
            if os.path.isdir(p):
                dirs.append(p)
    return dirs


def studio_file(rel):
    """Path of a file inside Studio's content folder, e.g. 'avatar/character.rbxm'."""
    for d in studio_content_dirs():
        p = os.path.join(d, *rel.split("/"))
        if os.path.isfile(p):
            return p
    return None


# ---------------------------------------------------------------------------

def cache_dir():
    try:
        return bpy.utils.extension_path_user(__package__, path="asset_cache", create=True)
    except (ValueError, AttributeError, TypeError):
        return bpy.utils.user_resource("DATAFILES", path=os.path.join("rblx_tools", "asset_cache"),
                                       create=True)


def online_allowed():
    return getattr(bpy.app, "online_access", True)


def _read_head(path, n=64):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


class AssetResolver:
    def __init__(self, folders=(), use_studio=True, downloader=None, use_cache=True):
        dirs = [os.path.normpath(bpy.path.abspath(f)) for f in folders if f]
        if use_cache:
            dirs.append(cache_dir())
        self.folders = [f for f in dirs if os.path.isdir(f)]
        self.studio_dirs = studio_content_dirs() if use_studio else []
        self.downloader = downloader
        self._index = None
        self.download_note = None   # why downloads are unavailable, if they are

    # -- index of local files by asset id
    def _build_index(self):
        index = {}
        count = 0
        for folder in self.folders:
            for dirpath, _dirs, files in os.walk(folder):
                for fn in files:
                    count += 1
                    if count > _MAX_FILES or fn.endswith(".part"):
                        continue
                    stem = os.path.splitext(fn)[0]
                    path = os.path.join(dirpath, fn)
                    if stem.isdigit():
                        index.setdefault(stem, path)
                        continue
                    for m in _NAME_ID.findall(stem):
                        index.setdefault(m, path)
        self._index = index

    def _lookup(self, aid):
        if self._index is None:
            self._build_index()
        return self._index.get(aid)

    def _builtin(self, content):
        rel = content[len("rbxasset://"):].replace("\\", "/").lstrip("/")
        for d in self.studio_dirs:
            p = os.path.join(d, *rel.split("/"))
            if os.path.isfile(p):
                return p
        base = os.path.basename(rel)
        for folder in self.folders:
            p = os.path.join(folder, base)
            if os.path.isfile(p):
                return p
        return None

    def resolve(self, content):
        """Return a local file path for `content` (downloading if allowed), or None."""
        if not content or not isinstance(content, str):
            return None
        content = content.strip()
        local = bpy.path.abspath(content)
        if os.path.isfile(local):
            return local
        if content.lower().startswith("rbxasset://"):
            return self._builtin(content)
        aid = asset_id(content)
        if aid is None:
            return None
        path = self._lookup(aid)
        if path is None and self.downloader is not None:
            path = self.downloader.fetch(aid)
            if path:
                self._index[aid] = path
        return path

    def prefetch(self, contents, progress=None):
        """Download every missing asset in `contents` in parallel."""
        if self.downloader is None:
            return
        todo = []
        for c in contents:
            if not isinstance(c, str) or c.lower().startswith("rbxasset://"):
                continue
            aid = asset_id(c)
            if aid and self._lookup(aid) is None:
                todo.append(aid)
        for aid, path in self.downloader.fetch_many(todo, progress=progress).items():
            if path:
                self._index[aid] = path

    def _follow(self, path, props, depth):
        """If `path` is a Roblox model (e.g. a Decal or Shirt asset), find the
        image/mesh it points to."""
        head = _read_head(path)
        if sniff_extension(head) not in (".rbxm", ".rbxmx") or depth > 2:
            return path
        from .rbx import load_file
        try:
            doc = load_file(path)
        except Exception:
            return None
        for inst in doc.all_instances():
            for prop in props:
                v = inst.props.get(prop)
                if isinstance(v, str) and v.strip():
                    inner = self.resolve(v)
                    return self._follow(inner, props, depth + 1) if inner else None
        return None

    def resolve_image(self, content):
        path = self.resolve(content)
        return self._follow(path, _IMAGE_PROPS, 0) if path else None

    def resolve_mesh(self, content):
        path = self.resolve(content)
        return self._follow(path, _MESH_PROPS, 0) if path else None

    def error_for(self, content):
        if self.downloader is None:
            return self.download_note
        aid = asset_id(content or "")
        return self.downloader.errors.get(aid) if aid else None


def make_downloader():
    """Downloader from the add-on preferences, or (None, reason)."""
    p = prefs.get()
    if p is None or not p.api_key.strip():
        return None, "No Roblox Open Cloud API key set (add-on preferences)"
    if not p.download_assets:
        return None, "Downloading is turned off in the add-on preferences"
    if not online_allowed():
        return None, "Blender's online access is off (Preferences > System > Network)"
    return Downloader(p.api_key, cache_dir()), None


def default_resolver(extra_folder=None, allow_download=True):
    p = prefs.get()
    folders = []
    if extra_folder:
        folders.append(extra_folder)
    if p and p.asset_folder:
        folders.append(p.asset_folder)
    use_studio = p.use_studio_content if p else True
    downloader, note = make_downloader() if allow_download else (None, "Downloads disabled")
    r = AssetResolver(folders, use_studio, downloader)
    r.download_note = note
    return r
