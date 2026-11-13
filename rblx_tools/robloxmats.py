"""Roblox's own material textures.

Roblox Studio stopped shipping its material textures as files in 2024 (they're
streamed now), but every earlier Studio build is still on Roblox's setup CDN
(setup.rbxcdn.com, the same place Bloxstrap / Fishstrap install from). This
downloads the texture packages of one such build once and converts them to
plain PNGs in the asset library:

  roblox_materials/Legacy/<Material>[ _normal | _roughness | _metalness ].png
      the pre-2022 part materials (content-textures3.zip)
  roblox_materials/2022/<Material>[ _side ][ _normal | _roughness ].png
      the 2022 terrain materials (content-terrain.zip), which 2022 parts of the
      same materials also use
  roblox_materials/LegacyTerrain/<Material>[ _side | _bottom ][ _normal | _roughness ].png
      the pre-2022 terrain materials (the atlas in content-terrain.zip)
  roblox_materials/Water/normal_01..25.png
      terrain water's animated wave normal maps (content-textures3.zip)

Colour maps are detail textures tinted by the part / terrain colour, like in
Roblox. manifest.json records each map's average brightness so the tint keeps
the part's colour."""

import io
import json
import os
import urllib.request
import zipfile

import numpy as np

from .rbx import dds

CDN = "https://setup.rbxcdn.com/"
# Studio builds that still shipped the material textures (newest first)
BUILDS = ("version-954719f125be4a9d", "version-cb457944642b4d94")
FOLDER = "roblox_materials"
LEGACY_NAMES = {
    "brick": "Brick", "cobblestone": "Cobblestone", "concrete": "Concrete",
    "corrodedmetal": "CorrodedMetal", "diamondplate": "DiamondPlate", "fabric": "Fabric",
    "foil": "Foil", "glass": "Glass", "granite": "Granite", "grass": "Grass", "ice": "Ice",
    "marble": "Marble", "metal": "Metal", "pebble": "Pebble", "sand": "Sand", "slate": "Slate",
    "wood": "Wood", "woodplanks": "WoodPlanks",
}


def root():
    from . import assets
    return os.path.join(assets.library_dir(), FOLDER)


def installed():
    return os.path.isfile(os.path.join(root(), "manifest.json"))


_manifest_cache = {}


def manifest():
    path = os.path.join(root(), "manifest.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _manifest_cache.get("mtime") != mtime:
        with open(path, encoding="utf-8") as f:
            _manifest_cache["data"] = json.load(f)
        _manifest_cache["mtime"] = mtime
    return _manifest_cache["data"]


DEFAULT_TILE_STUDS = 8.0


def textures_for(name, style, side=False, terrain=False):
    """{role: path} for a material in a style ("2022" / "LEGACY"), plus "gain"
    (brightness correction), "tile" (studs per repeat) and "set".
    2022 falls back to the Legacy set for part-only materials (Wood, Metal,
    ...) whose 2022 textures Roblox never shipped as files; legacy terrain
    uses Roblox's old terrain textures."""
    m = manifest()
    if not m:
        return {}
    if style == "2022":
        order = ("2022", "Legacy")
    elif terrain:
        order = ("LegacyTerrain", "Legacy", "2022")
    else:
        order = ("Legacy", "LegacyTerrain", "2022")
    for sub in order:
        entry = m.get(sub, {}).get(name)
        if not entry:
            continue
        key = "side" if side and "side" in entry else "top"
        maps = entry.get(key) or entry.get("top")
        if not maps:
            continue
        out = {role: os.path.join(root(), sub, fn) for role, fn in maps.items()
               if role not in ("gain", "tile")}
        out["gain"] = maps.get("gain", 1.0)
        out["tile"] = float(maps.get("tile", DEFAULT_TILE_STUDS)) if sub != "Legacy" \
            else DEFAULT_TILE_STUDS
        out["set"] = sub
        return out
    return {}


def water_frames():
    """Paths of the terrain water normal-map animation frames (or [])."""
    files = manifest().get("Water", {}).get("frames", [])
    paths = [os.path.join(root(), "Water", f) for f in files]
    return paths if paths and all(os.path.isfile(p) for p in paths) else []


# ---------------------------------------------------------------------------
# Install

def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "RBLX-Tools-Blender"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _save(path, rgb):
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=2)
    rgba = np.concatenate([rgb[..., :3], np.full(rgb.shape[:2] + (1,), 255, np.uint8)], axis=2)
    dds.write_png(path, rgba)


def _normal_rgb(px):
    """DXT5 normal map (X in alpha, Y in green) -> RGB tangent-space normal."""
    x = px[..., 3].astype(np.float32) / 127.5 - 1.0
    y = px[..., 1].astype(np.float32) / 127.5 - 1.0
    z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
    return np.clip(np.stack([x, y, z], axis=-1) * 127.5 + 127.5, 0, 255).astype(np.uint8)


def _tile_studs(tex):
    """Studs one repeat of a terrain texture covers: Roblox's terrain shader
    scales world position (in 4-stud voxels) by the texture's `tiling`."""
    t = float(tex.get("tiling", 0.5) or 0.5)
    return round(4.0 / max(t, 0.01), 3)


def _write_set(out_dir, name, suffix, color, normal, rough, metal=None):
    """Write one material's maps; returns the manifest entry."""
    entry = {}
    base = name + suffix
    lum = color.astype(np.float32).mean(axis=-1) if color.ndim == 3 else color.astype(np.float32)
    _save(os.path.join(out_dir, base + ".png"), color)
    entry["color"] = base + ".png"
    entry["gain"] = round(float(255.0 / max(lum.mean(), 1.0)), 4)
    if normal is not None:
        _save(os.path.join(out_dir, base + "_normal.png"), normal)
        entry["normal"] = base + "_normal.png"
    if rough is not None:
        _save(os.path.join(out_dir, base + "_roughness.png"), rough)
        entry["roughness"] = base + "_roughness.png"
    if metal is not None and metal.max() > 8:
        _save(os.path.join(out_dir, base + "_metalness.png"), metal)
        entry["metalness"] = base + "_metalness.png"
    return entry


def install(progress=None):
    """Download and convert Roblox's material textures. Returns the manifest."""
    def step(msg):
        if progress:
            progress(msg)

    last_error = None
    tex3 = terrain = None
    for build in BUILDS:
        try:
            step("Downloading Roblox's legacy part textures (%s)..." % build)
            tex3 = zipfile.ZipFile(io.BytesIO(_get(CDN + build + "-content-textures3.zip")))
            step("Downloading Roblox's 2022 terrain textures...")
            terrain = zipfile.ZipFile(io.BytesIO(_get(CDN + build + "-content-terrain.zip")))
            break
        except Exception as ex:  # try the next build
            last_error = ex
            tex3 = terrain = None
    if tex3 is None or terrain is None:
        raise RuntimeError("couldn't download Roblox's texture packages (%s)" % last_error)

    out = root()
    man = {"Legacy": {}, "2022": {}}
    legacy_dir = os.path.join(out, "Legacy")
    new_dir = os.path.join(out, "2022")
    os.makedirs(legacy_dir, exist_ok=True)
    os.makedirs(new_dir, exist_ok=True)

    names = set(tex3.namelist())
    for folder, name in sorted(LEGACY_NAMES.items()):
        if folder + "/diffuse.dds" not in names:
            continue
        step("Converting legacy " + name)
        diffuse = dds.decode(tex3.read(folder + "/diffuse.dds"))[0][1]
        normal = refl = None
        if folder + "/normal.dds" in names:
            n = dds.decode(tex3.read(folder + "/normal.dds"))[0][1]
            if n.shape[0] > 8:
                normal = _normal_rgb(n)
        if folder + "/reflection.dds" in names:
            refl = dds.decode(tex3.read(folder + "/reflection.dds"))[0][1]
        if diffuse.shape[0] <= 8:
            diffuse = np.full((4, 4, 4), 255, np.uint8)  # flat (Foil, Ice)
        man["Legacy"][name] = {"top": _write_set(
            legacy_dir, name, "", diffuse[..., :3], normal,
            refl[..., 1] if refl is not None else None,
            refl[..., 0] if refl is not None else None)}

    # Terrain water's animated wave normals (25 frames)
    frames = sorted(n for n in names if n.startswith("water/normal_") and n.endswith(".dds"))
    if frames:
        step("Converting water waves")
        water_dir = os.path.join(out, "Water")
        os.makedirs(water_dir, exist_ok=True)
        files = []
        for i, n in enumerate(frames, 1):
            fn = "normal_%02d.png" % i
            _save(os.path.join(water_dir, fn), _normal_rgb(dds.decode(tex3.read(n))[0][1]))
            files.append(fn)
        man["Water"] = {"frames": files}

    step("Converting 2022 terrain textures")
    mats = json.loads(terrain.read("materials2022.json"))["materials"]
    diff = dict(dds.decode(terrain.read("diffusearray.dds")))
    norm = dict(dds.decode(terrain.read("normalarray.dds")))
    refl = dict(dds.decode(terrain.read("reflectionarray.dds")))
    index = 0
    # The arrays hold one slice per texture listed in materials2022.json, except
    # Slate's bottom (it reuses its side): 37 entries, 36 slices. Checked against
    # the slices' look (brick, sand ripples, planks, lava cracks, pavers line up).
    no_slice = {("Slate", "texture_bottom")}
    for m in mats:
        keys = [k for k in ("texture", "texture_top", "texture_side", "texture_bottom")
                if k in m and (m["name"], k) not in no_slice]
        if not keys:
            continue
        entry = {}
        for k in keys:
            if index not in diff:
                break
            part = {"texture": "top", "texture_top": "top", "texture_side": "side",
                    "texture_bottom": "bottom"}[k]
            suffix = "" if part == "top" else "_" + part
            # colour detail is the green channel (luminance) of the packed diffuse
            entry[part] = _write_set(new_dir, m["name"], suffix, diff[index][..., 1],
                                     _normal_rgb(norm[index]), refl[index][..., 1])
            entry[part]["tile"] = _tile_studs(m[k])
            index += 1
        if entry:
            base = m.get("base_color")
            if base:
                entry["base_color"] = base
            man["2022"][m["name"]] = entry
    # Legacy terrain (Use2022Materials off): one 6x6 atlas of 256px tiles with
    # 42px wrap-around borders, in materials.json's texture order
    if "materials.json" in terrain.namelist():
        step("Converting legacy terrain textures")
        info = json.loads(terrain.read("materials.json"))
        atlas = info.get("atlas", {}).get("pc", {})
        tsize, border = atlas.get("tileSize", 256), atlas.get("borderSize", 42)
        per_row = atlas.get("tileCount", 6)
        a_diff = dds.decode(terrain.read("diffuse.dds"))[0][1]
        a_norm = dds.decode(terrain.read("normal.dds"))[0][1]
        a_refl = dds.decode(terrain.read("reflection.dds"))[0][1]
        scale = a_diff.shape[1] / float(atlas.get("width", a_diff.shape[1]))
        cell = tsize + 2 * border
        old_dir = os.path.join(out, "LegacyTerrain")
        os.makedirs(old_dir, exist_ok=True)
        man["LegacyTerrain"] = {}
        index = 0
        for m in info.get("materials", []):
            keys = [k for k in ("texture", "texture_top", "texture_side", "texture_bottom") if k in m]
            entry = {}
            for k in keys:
                row, col = divmod(index, per_row)
                y0 = int((row * cell + border) * scale)
                x0 = int((col * cell + border) * scale)
                n = int(tsize * scale)
                if y0 + n > a_diff.shape[0] or x0 + n > a_diff.shape[1]:
                    break
                sl = (slice(y0, y0 + n), slice(x0, x0 + n))
                part = {"texture": "top", "texture_top": "top", "texture_side": "side",
                        "texture_bottom": "bottom"}[k]
                suffix = "" if part == "top" else "_" + part
                entry[part] = _write_set(old_dir, m["name"], suffix, a_diff[sl][..., 1],
                                         _normal_rgb(a_norm[sl]), a_refl[sl][..., 1])
                entry[part]["tile"] = _tile_studs(m[k])
                index += 1
            if entry:
                man["LegacyTerrain"][m["name"]] = entry
    man["source"] = "setup.rbxcdn.com (Roblox Studio content-textures3.zip, content-terrain.zip)"
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    _manifest_cache.clear()
    return man
