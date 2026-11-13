"""Roblox-style materials.

Parts without textures share one material per Roblox material type
("RBX Plastic", ...). Each part's Color / Transparency / Reflectance are read
per object through Attribute nodes (rblx.color, ...), so they can be
keyframed and one material serves every part.

Parts with texture layers (Decals, Textures, clothing, TextureID, your own
images) get their own material: the Roblox material shading with the layers
composited over the part Color. Each layer's tint (Color3) and Transparency
are also read live through Attribute nodes."""

import os

import bpy
from mathutils import Vector

from . import coords, prefs

ATTR_COLOR = "rblx.color"
ATTR_TRANSPARENCY = "rblx.transparency"
ATTR_REFLECTANCE = "rblx.reflectance"
MATERIAL_VERSION = 3  # bump when the shared material nodes change (2: Highlight, 3: union colours)

# rough, metal, bump strength, bump scale, extra
PRESETS = {
    "Plastic": (0.55, 0.0, 0.0, 0.0, {}),
    "SmoothPlastic": (0.35, 0.0, 0.0, 0.0, {}),
    "Neon": (0.5, 0.0, 0.0, 0.0, {"emission": 4.0}),
    "Wood": (0.7, 0.0, 0.08, 6.0, {}),
    "WoodPlanks": (0.7, 0.0, 0.08, 4.0, {}),
    "Marble": (0.25, 0.0, 0.03, 2.0, {}),
    "Basalt": (0.85, 0.0, 0.2, 3.0, {}),
    "Slate": (0.8, 0.0, 0.2, 2.0, {}),
    "CrackedLava": (0.8, 0.0, 0.25, 2.0, {}),
    "Concrete": (0.85, 0.0, 0.12, 8.0, {}),
    "Limestone": (0.8, 0.0, 0.12, 4.0, {}),
    "Granite": (0.6, 0.0, 0.1, 6.0, {}),
    "Pavement": (0.85, 0.0, 0.12, 6.0, {}),
    "Brick": (0.85, 0.0, 0.15, 3.0, {}),
    "Pebble": (0.75, 0.0, 0.3, 4.0, {}),
    "Cobblestone": (0.8, 0.0, 0.3, 2.0, {}),
    "Rock": (0.85, 0.0, 0.3, 2.0, {}),
    "Sandstone": (0.8, 0.0, 0.12, 4.0, {}),
    "CorrodedMetal": (0.75, 0.7, 0.2, 4.0, {}),
    "DiamondPlate": (0.35, 0.85, 0.1, 6.0, {}),
    "Foil": (0.2, 1.0, 0.05, 6.0, {}),
    "Metal": (0.35, 0.85, 0.0, 0.0, {}),
    "Grass": (0.9, 0.0, 0.15, 10.0, {}),
    "LeafyGrass": (0.9, 0.0, 0.2, 8.0, {}),
    "Sand": (0.9, 0.0, 0.08, 12.0, {}),
    "Fabric": (0.95, 0.0, 0.05, 16.0, {}),
    "Snow": (0.8, 0.0, 0.06, 6.0, {}),
    "Mud": (0.7, 0.0, 0.1, 4.0, {}),
    "Ground": (0.9, 0.0, 0.1, 6.0, {}),
    "Asphalt": (0.9, 0.0, 0.08, 12.0, {}),
    "Salt": (0.7, 0.0, 0.08, 8.0, {}),
    "Ice": (0.1, 0.0, 0.02, 2.0, {"transmission": 0.3}),
    "Glacier": (0.15, 0.0, 0.05, 2.0, {"transmission": 0.3}),
    "Glass": (0.05, 0.0, 0.0, 0.0, {"transmission": 0.9}),
    "ForceField": (0.5, 0.0, 0.0, 0.0, {"forcefield": True}),
    "Air": (0.5, 0.0, 0.0, 0.0, {}),
    "Water": (0.05, 0.0, 0.0, 0.0, {"transmission": 0.9}),
}

_SOCKETS = {
    "emission_color": ("Emission Color", "Emission"),
    "transmission": ("Transmission Weight", "Transmission"),
}


def _input(node, *names):
    for n in names:
        sock = node.inputs.get(n)
        if sock is not None:
            return sock
    return None


def _set_render_method(mat):
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "HASHED"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False


def _init_tree(mat):
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (600, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    _set_render_method(mat)
    mat["rblx_managed"] = True
    return nt, bsdf


def _new_material(name):
    mat = bpy.data.materials.new(name)
    nt, bsdf = _init_tree(mat)
    return mat, nt, bsdf


def _attr(nt, name, loc):
    n = nt.nodes.new("ShaderNodeAttribute")
    n.attribute_type = "OBJECT"
    n.attribute_name = name
    n.location = loc
    return n


def _math(nt, op, a=None, b=None, loc=(0, 0), c=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    if a is not None:
        n.inputs[0].default_value = a
    if b is not None:
        n.inputs[1].default_value = b
    if c is not None:
        n.inputs[2].default_value = c
    return n


def _vmath(nt, op, loc, b=None):
    n = nt.nodes.new("ShaderNodeVectorMath")
    n.operation = op
    n.location = loc
    if b is not None:
        n.inputs[1].default_value = b
    return n


def _mix_rgb(nt, blend, loc, factor=None):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    n.location = loc
    if factor is not None:
        n.inputs["Factor"].default_value = factor
    return n


def _link(nt, a, b):
    nt.links.new(a, b)


# ---------------------------------------------------------------------------
# Images

def _load_image(path, non_color=False):
    abspath = os.path.normcase(os.path.abspath(path))
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(os.path.abspath(bpy.path.abspath(img.filepath))) == abspath:
            break
    else:
        img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        try:
            img.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    return img


def load_image(path, non_color=False):
    try:
        return _load_image(path, non_color)
    except RuntimeError:
        return None  # unreadable / not an image


def classic_face_image():
    """Stand-in for rbxasset://textures/face.png (the classic smile), which
    Roblox Studio no longer ships as a file: drawn procedurally."""
    img = bpy.data.images.get("RBX Classic Face")
    if img is not None:
        return img
    size = 128
    img = bpy.data.images.new("RBX Classic Face", size, size, alpha=True)
    px = [0.0] * (size * size * 4)

    def dot(cx, cy, rx, ry):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if 0 <= x < size and 0 <= y < size and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                    px[(y * size + x) * 4 + 3] = 1.0

    dot(44, 78, 7, 13)
    dot(84, 78, 7, 13)
    import math
    for i in range(200):
        a = math.pi * (1.15 + 0.7 * i / 199)
        cx, cy = 64 + 34 * math.cos(a), 62 + 30 * math.sin(a)
        dot(cx, cy, 3.2, 3.2)
    img.pixels.foreach_set(px)
    img.pack()
    return img


def _image_node(nt, img, loc, extension="REPEAT", box_projection_scale=None):
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = loc
    tex.extension = extension
    if box_projection_scale:
        tex.projection = "BOX"
        tex.projection_blend = 0.2
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (loc[0] - 400, loc[1])
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (loc[0] - 200, loc[1])
        mapping.inputs["Scale"].default_value = (box_projection_scale,) * 3
        _link(nt, coord.outputs["Object"], mapping.inputs["Vector"])
        _link(nt, mapping.outputs["Vector"], tex.inputs["Vector"])
    return tex


def material_style(scene=None):
    """"2022" (MaterialService.Use2022Materials on, Roblox's default) or "LEGACY"."""
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    try:
        return "2022" if scene.rblx.use_2022_materials else "LEGACY"
    except AttributeError:
        return "2022"


STYLE_FOLDERS = {"2022": ("2022",), "LEGACY": ("Legacy", "Classic", "Old")}


def _find_material_textures(folder, name, style="2022"):
    """Look for <name>.png / <name>_color.png / _normal / _roughness / _metalness,
    first in the style's subfolder (2022/ or Legacy/), then in the folder itself."""
    if not folder or not os.path.isdir(folder):
        return {}
    for sub in STYLE_FOLDERS.get(style, ()):
        found = _find_material_textures(os.path.join(folder, sub), name, None)
        if found:
            return found
    exts = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".webp")
    roles = {
        "color": ("", "_color", "_albedo", "_diffuse", "_basecolor"),
        "normal": ("_normal", "_nor"),
        "roughness": ("_roughness", "_rough"),
        "metalness": ("_metalness", "_metallic", "_metal"),
    }
    files = {f.lower(): f for f in os.listdir(folder)}
    found = {}
    for role, suffixes in roles.items():
        for suf in suffixes:
            for ext in exts:
                key = (name + suf + ext).lower()
                if key in files:
                    found[role] = os.path.join(folder, files[key])
                    break
            if role in found:
                break
    return found


# ---------------------------------------------------------------------------
# Shared Roblox-material shading

# Procedural surface detail per material: (pattern, scale per stud, colour
# variation, bump strength). 2022 materials are finer and subtler; the
# pre-2022 ("legacy") set has bolder, chunkier patterns.
DETAIL_2022 = {
    "Wood": ("wood", 0.6, 0.18, 0.04),
    "WoodPlanks": ("planks", 1.0, 0.2, 0.08),
    "Marble": ("marble", 0.4, 0.15, 0.02),
    "Brick": ("brick", 1.0, 0.18, 0.15),
    "Pavement": ("tiles", 0.5, 0.1, 0.12),
    "Cobblestone": ("stones", 0.8, 0.25, 0.3),
    "Pebble": ("stones", 2.0, 0.2, 0.25),
    "CrackedLava": ("stones", 0.6, 0.35, 0.25),
    "DiamondPlate": ("plate", 2.0, 0.08, 0.15),
    "Concrete": ("noise", 4.0, 0.08, 0.1),
    "Slate": ("noise", 1.5, 0.15, 0.2),
    "Basalt": ("noise", 2.0, 0.15, 0.2),
    "Rock": ("noise", 1.5, 0.2, 0.3),
    "Granite": ("noise", 6.0, 0.12, 0.08),
    "Limestone": ("noise", 3.0, 0.1, 0.1),
    "Sandstone": ("noise", 2.0, 0.12, 0.12),
    "Grass": ("noise", 8.0, 0.15, 0.15),
    "LeafyGrass": ("noise", 5.0, 0.2, 0.2),
    "Sand": ("noise", 12.0, 0.08, 0.08),
    "Snow": ("noise", 4.0, 0.05, 0.06),
    "Mud": ("noise", 3.0, 0.15, 0.1),
    "Ground": ("noise", 4.0, 0.15, 0.1),
    "Asphalt": ("noise", 14.0, 0.1, 0.08),
    "Salt": ("noise", 10.0, 0.08, 0.08),
    "Fabric": ("noise", 20.0, 0.08, 0.05),
    "CorrodedMetal": ("noise", 3.0, 0.3, 0.2),
    "Foil": ("noise", 6.0, 0.05, 0.05),
    "Ice": ("noise", 1.0, 0.05, 0.02),
    "Glacier": ("noise", 1.0, 0.05, 0.02),
}
DETAIL_LEGACY_OVERRIDES = {
    "Wood": ("wood", 0.35, 0.35, 0.06),
    "WoodPlanks": ("planks", 0.5, 0.35, 0.12),
    "Brick": ("brick", 0.5, 0.3, 0.2),
    "DiamondPlate": ("plate", 1.0, 0.12, 0.25),
}


def surface_detail(name, style):
    if style == "LEGACY":
        if name in DETAIL_LEGACY_OVERRIDES:
            return DETAIL_LEGACY_OVERRIDES[name]
        d = DETAIL_2022.get(name)
        if d is None:
            return None
        return (d[0], d[1] * 0.5, min(d[2] * 1.8, 0.6), d[3] * 1.4)
    return DETAIL_2022.get(name)


def _planar_coords(nt, tc, vec, loc):
    """2D coordinates that follow the part's faces (x,y on top/bottom, x,z on
    front/back, y,z on the sides), so brick-like patterns work on every face."""
    x, y = loc
    absn = _vmath(nt, "ABSOLUTE", (x, y - 200))
    _link(nt, tc.outputs["Normal"], absn.inputs[0])
    n = nt.nodes.new("ShaderNodeSeparateXYZ")
    n.location = (x + 180, y - 200)
    _link(nt, absn.outputs["Vector"], n.inputs[0])
    p = nt.nodes.new("ShaderNodeSeparateXYZ")
    p.location = (x + 180, y)
    _link(nt, vec, p.inputs[0])

    def gt(a, b, dx):
        m = _math(nt, "GREATER_THAN", loc=(x + 360 + dx, y - 300))
        _link(nt, a, m.inputs[0])
        _link(nt, b, m.inputs[1])
        return m.outputs[0]

    def both(a, b, dx):
        m = _math(nt, "MULTIPLY", loc=(x + 520 + dx, y - 300))
        _link(nt, a, m.inputs[0])
        _link(nt, b, m.inputs[1])
        return m.outputs[0]

    wx = both(gt(n.outputs["X"], n.outputs["Y"], 0), gt(n.outputs["X"], n.outputs["Z"], 40), 0)
    wz = both(gt(n.outputs["Z"], n.outputs["X"], 80), gt(n.outputs["Z"], n.outputs["Y"], 120), 40)

    def pick(a, b, w, dy):  # a + w * (b - a)
        d = _math(nt, "SUBTRACT", loc=(x + 680, y + dy))
        _link(nt, b, d.inputs[0])
        _link(nt, a, d.inputs[1])
        m = _math(nt, "MULTIPLY_ADD", loc=(x + 840, y + dy))
        _link(nt, d.outputs[0], m.inputs[0])
        _link(nt, w, m.inputs[1])
        _link(nt, a, m.inputs[2])
        return m.outputs[0]

    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    comb.location = (x + 1000, y)
    _link(nt, pick(p.outputs["X"], p.outputs["Y"], wx, 0), comb.inputs["X"])
    _link(nt, pick(p.outputs["Z"], p.outputs["Y"], wz, -150), comb.inputs["Y"])
    return comb.outputs["Vector"]


def _map(nt, sock, a, b, c, d, loc):
    m = nt.nodes.new("ShaderNodeMapRange")
    m.location = loc
    m.clamp = True
    m.inputs["From Min"].default_value = a
    m.inputs["From Max"].default_value = b
    m.inputs["To Min"].default_value = c
    m.inputs["To Max"].default_value = d
    _link(nt, sock, m.inputs["Value"])
    return m.outputs["Result"]


def _wave(nt, vec, scale, distortion, detail, loc):
    w = nt.nodes.new("ShaderNodeTexWave")
    w.location = loc
    w.wave_type = "BANDS"
    w.bands_direction = "X"
    w.inputs["Scale"].default_value = scale
    w.inputs["Distortion"].default_value = distortion
    w.inputs["Detail"].default_value = detail
    _link(nt, vec, w.inputs["Vector"])
    return w.outputs["Fac"]


def _brick(nt, vec, scale, width, height, mortar, offset, loc):
    b = nt.nodes.new("ShaderNodeTexBrick")
    b.location = loc
    b.offset = offset
    b.inputs["Color1"].default_value = (0.0, 0.0, 0.0, 1.0)
    b.inputs["Color2"].default_value = (0.4, 0.4, 0.4, 1.0)
    b.inputs["Mortar"].default_value = (1.0, 1.0, 1.0, 1.0)
    b.inputs["Scale"].default_value = scale
    b.inputs["Mortar Size"].default_value = mortar
    b.inputs["Brick Width"].default_value = width
    b.inputs["Row Height"].default_value = height
    _link(nt, vec, b.inputs["Vector"])
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    bw.location = (loc[0] + 200, loc[1])
    _link(nt, b.outputs["Color"], bw.inputs["Color"])
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(loc[0] + 200, loc[1] - 150))
    _link(nt, b.outputs["Fac"], inv.inputs[1])
    return bw.outputs["Val"], inv.outputs[0]  # darkness, height


def _pattern(nt, kind, scale, loc):
    """Build a procedural pattern in stud space. Returns (darkness 0..1, height)."""
    x, y = loc
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (x - 600, y)
    studs = _vmath(nt, "SCALE", (x - 400, y))
    studs.inputs["Scale"].default_value = 1.0 / max(coords.stud_scale(), 1e-4)
    _link(nt, tc.outputs["Object"], studs.inputs[0])
    vec = studs.outputs["Vector"]

    if kind == "noise":
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.location = (x, y)
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = 6.0
        _link(nt, vec, n.inputs["Vector"])
        return _map(nt, n.outputs["Fac"], 0.35, 0.65, 0.0, 1.0, (x + 200, y)), n.outputs["Fac"]
    if kind == "wood":
        grain = _wave(nt, vec, scale, 6.0, 2.0, (x, y))
        dark = _math(nt, "POWER", b=3.0, loc=(x + 200, y))
        _link(nt, grain, dark.inputs[0])
        return dark.outputs[0], dark.outputs[0]
    if kind == "marble":
        veins = _wave(nt, vec, scale, 15.0, 6.0, (x, y))
        dark = _math(nt, "POWER", b=4.0, loc=(x + 200, y))
        _link(nt, veins, dark.inputs[0])
        return dark.outputs[0], dark.outputs[0]
    if kind in ("planks", "brick", "tiles"):
        uv = _planar_coords(nt, tc, vec, (x - 1200, y - 400))
        if kind == "planks":
            dark, height = _brick(nt, uv, scale, 4.0, 1.0, 0.015, 0.5, (x, y))
            grain = _wave(nt, vec, scale * 1.5, 6.0, 2.0, (x, y - 300))
            g = _math(nt, "MULTIPLY", b=0.6, loc=(x + 200, y - 300))
            _link(nt, grain, g.inputs[0])
            mx = _math(nt, "MAXIMUM", loc=(x + 400, y))
            _link(nt, dark, mx.inputs[0])
            _link(nt, g.outputs[0], mx.inputs[1])
            return mx.outputs[0], height
        if kind == "brick":
            return _brick(nt, uv, scale, 2.0, 1.0, 0.06, 0.5, (x, y))
        return _brick(nt, uv, scale, 1.0, 1.0, 0.03, 0.0, (x, y))
    if kind in ("stones", "plate"):
        v = nt.nodes.new("ShaderNodeTexVoronoi")
        v.location = (x, y)
        v.inputs["Scale"].default_value = scale
        _link(nt, vec, v.inputs["Vector"])
        if kind == "stones":
            v.feature = "DISTANCE_TO_EDGE"
            edge = _map(nt, v.outputs["Distance"], 0.0, 0.12, 1.0, 0.0, (x + 200, y))
            height = _map(nt, v.outputs["Distance"], 0.0, 0.12, 0.0, 1.0, (x + 200, y - 200))
            return edge, height
        v.inputs["Randomness"].default_value = 0.0
        bump = _map(nt, v.outputs["Distance"], 0.0, 0.35, 1.0, 0.0, (x + 200, y))
        dark = _math(nt, "MULTIPLY", b=0.3, loc=(x + 400, y))
        _link(nt, bump, dark.inputs[0])
        return dark.outputs[0], bump
    return None, None


def _tex(v, non_color=False):
    """An image from a path or an already-loaded image."""
    if isinstance(v, bpy.types.Image):
        if non_color:
            try:
                v.colorspace_settings.name = "Non-Color"
            except TypeError:
                pass
        return v
    return load_image(v, non_color=non_color)


ROBLOX_TILE_STUDS = 8.0  # Roblox's material textures repeat every 8 studs


def use_roblox_textures():
    p = prefs.get()
    return getattr(p, "use_roblox_textures", True) if p is not None else True


def texture_signature():
    """Changes when Roblox's textures get installed or switched on/off."""
    from . import robloxmats
    if not use_roblox_textures() or not robloxmats.installed():
        return "procedural"
    return "roblox:%d" % int(os.path.getmtime(os.path.join(robloxmats.root(), "manifest.json")))


def _part_shading(nt, bsdf, name, base_color, alpha, style=None, variant=None, terrain=False):
    """Wire the Roblox material look into `bsdf`. `base_color` is a colour
    socket (the part colour, possibly with layers); `alpha` an alpha socket.
    `variant`: a MaterialService MaterialVariant whose maps replace the material's."""
    style = style or material_style()
    rough, metal, _bump_strength, _bump_scale, extra = PRESETS.get(name, PRESETS["Plastic"])
    if style == "LEGACY" and metal < 0.5:
        rough = min(1.0, rough + 0.08)  # the old materials were a little less glossy
    p = prefs.get()
    if variant is not None:
        textures = {role: img for role, img in (("color", variant.color_map),
                                                 ("normal", variant.normal_map),
                                                 ("roughness", variant.roughness_map),
                                                 ("metalness", variant.metalness_map)) if img}
        tile = 1.0 / max(variant.studs_per_tile, 0.01) / coords.stud_scale()
    else:
        textures = _find_material_textures(bpy.path.abspath(p.material_folder) if p else "", name,
                                           style)
        tile = 1.0 / max((p.material_tile_studs if p else 4.0), 0.01) / coords.stud_scale()
        if not textures and use_roblox_textures():
            # Roblox's own textures (downloaded once from Roblox's CDN)
            from . import robloxmats
            textures = robloxmats.textures_for(name, style, terrain=terrain)
            if textures:
                tile = 1.0 / float(textures.get("tile", ROBLOX_TILE_STUDS)) / coords.stud_scale()
                if terrain:
                    side = robloxmats.textures_for(name, style, side=True, terrain=True)
                    if side and side.get("color") != textures.get("color"):
                        textures["side"] = side
    side_tex = textures.pop("side", None) if isinstance(textures, dict) else None
    gain = min(float(textures.pop("gain", 1.0)), 3.0) if isinstance(textures, dict) else 1.0
    textures.pop("set", None)
    textures.pop("tile", None)
    side_tile = tile
    if side_tex:
        side_tile = 1.0 / float(side_tex.get("tile", ROBLOX_TILE_STUDS)) / coords.stud_scale()

    def tex_socket(role, loc, non_color=False):
        """Colour output for a map, blending the side texture in on steep terrain."""
        img = _tex(textures[role], non_color=non_color)
        if not img:
            return None
        top = _image_node(nt, img, loc, box_projection_scale=tile).outputs["Color"]
        if side_tex and role in side_tex:
            simg = _tex(side_tex[role], non_color=non_color)
            if simg:
                side_node = _image_node(nt, simg, (loc[0], loc[1] - 250),
                                        box_projection_scale=side_tile)
                geo = nt.nodes.new("ShaderNodeNewGeometry")
                geo.location = (loc[0] - 400, loc[1] - 400)
                sep = nt.nodes.new("ShaderNodeSeparateXYZ")
                sep.location = (loc[0] - 250, loc[1] - 400)
                _link(nt, geo.outputs["Normal"], sep.inputs[0])
                fac = nt.nodes.new("ShaderNodeMapRange")
                fac.location = (loc[0] - 100, loc[1] - 400)
                fac.inputs["From Min"].default_value = 0.55
                fac.inputs["From Max"].default_value = 0.8
                _link(nt, sep.outputs["Z"], fac.inputs["Value"])
                mix = _mix_rgb(nt, "MIX", (loc[0] + 200, loc[1] - 100))
                _link(nt, fac.outputs["Result"], mix.inputs["Factor"])
                _link(nt, side_node.outputs["Color"], mix.inputs["A"])
                _link(nt, top, mix.inputs["B"])
                return mix.outputs["Result"]
        return top

    detail = None if "color" in textures else surface_detail(name, style)
    height = None
    if detail is not None:
        kind, dscale, var, bump_strength = detail
        dark, height = _pattern(nt, kind, dscale, (-700, 1100))
        if dark is not None:
            f = _math(nt, "MULTIPLY", b=var, loc=(-100, 900))
            _link(nt, dark, f.inputs[0])
            shade = _mix_rgb(nt, "MIX", (100, 700))
            shade.inputs["B"].default_value = (0.0, 0.0, 0.0, 1.0)
            _link(nt, f.outputs[0], shade.inputs["Factor"])
            _link(nt, base_color, shade.inputs["A"])
            base_color = shade.outputs["Result"]

    if "color" in textures:
        col_out = tex_socket("color", (-200, 650))
        if col_out is not None:
            if abs(gain - 1.0) > 1e-3:
                # Roblox's maps are detail textures: keep the part's colour on average
                g = _mix_rgb(nt, "MULTIPLY", (50, 650), factor=1.0)
                g.clamp_result = False
                _link(nt, col_out, g.inputs["A"])
                g.inputs["B"].default_value = (gain, gain, gain, 1.0)
                col_out = g.outputs["Result"]
            mul = _mix_rgb(nt, "MULTIPLY", (250, 450), factor=1.0)
            _link(nt, base_color, mul.inputs["A"])
            _link(nt, col_out, mul.inputs["B"])
            base_color = mul.outputs["Result"]
    # Highlight fill (0 unless the part has a Roblox Highlight)
    fill = _attr(nt, "rblx.highlight_fill", (-100, 950))
    fill_a = _attr(nt, "rblx.highlight_fill_alpha", (-100, 800))
    hmix = _mix_rgb(nt, "MIX", (300, 750))
    _link(nt, fill_a.outputs["Fac"], hmix.inputs["Factor"])
    _link(nt, base_color, hmix.inputs["A"])
    _link(nt, fill.outputs["Color"], hmix.inputs["B"])
    base_color = hmix.outputs["Result"]
    if not extra.get("emission") and not extra.get("forcefield"):
        _link(nt, fill.outputs["Color"], _input(bsdf, *_SOCKETS["emission_color"]))
        glow = _math(nt, "MULTIPLY", b=0.6, loc=(300, 900))
        _link(nt, fill_a.outputs["Fac"], glow.inputs[0])
        _link(nt, glow.outputs[0], bsdf.inputs["Emission Strength"])
    _link(nt, base_color, bsdf.inputs["Base Color"])

    refl = _attr(nt, ATTR_REFLECTANCE, (-100, -150))
    rough_src = None
    if "roughness" in textures:
        rough_src = tex_socket("roughness", (-200, -650), non_color=True)
    if rough_src is not None:
        lerp = nt.nodes.new("ShaderNodeMix")
        lerp.data_type = "FLOAT"
        lerp.location = (300, -150)
        lerp.inputs["B"].default_value = 0.05
        _link(nt, refl.outputs["Fac"], lerp.inputs["Factor"])
        _link(nt, rough_src, lerp.inputs["A"])
        _link(nt, lerp.outputs["Result"], bsdf.inputs["Roughness"])
    else:
        rmap = nt.nodes.new("ShaderNodeMapRange")
        rmap.location = (300, -150)
        rmap.inputs["To Min"].default_value = rough
        rmap.inputs["To Max"].default_value = 0.05
        _link(nt, refl.outputs["Fac"], rmap.inputs["Value"])
        _link(nt, rmap.outputs["Result"], bsdf.inputs["Roughness"])

    mmax = _math(nt, "MAXIMUM", b=metal, loc=(300, 0))
    _link(nt, refl.outputs["Fac"], mmax.inputs[0])
    if "metalness" in textures:
        mtex = tex_socket("metalness", (-200, -400), non_color=True)
        if mtex is not None:
            _link(nt, mtex, mmax.inputs[1])
    _link(nt, mmax.outputs[0], bsdf.inputs["Metallic"])

    if "normal" in textures:
        nrm = tex_socket("normal", (-200, -900), non_color=True)
        if nrm is not None:
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.location = (300, -800)
            _link(nt, nrm, nmap.inputs["Color"])
            _link(nt, nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif height is not None and detail[3] > 0.0:
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (300, -650)
        bump.inputs["Strength"].default_value = detail[3]
        if "Distance" in bump.inputs:
            bump.inputs["Distance"].default_value = 0.05 * coords.stud_scale()
        _link(nt, height, bump.inputs["Height"])
        _link(nt, bump.outputs["Normal"], bsdf.inputs["Normal"])

    if extra.get("emission"):
        _link(nt, base_color, _input(bsdf, *_SOCKETS["emission_color"]))
        bsdf.inputs["Emission Strength"].default_value = extra["emission"]
    if extra.get("transmission"):
        sock = _input(bsdf, *_SOCKETS["transmission"])
        if sock:
            sock.default_value = extra["transmission"]

    if extra.get("forcefield"):
        _link(nt, base_color, _input(bsdf, *_SOCKETS["emission_color"]))
        bsdf.inputs["Emission Strength"].default_value = 2.0
        fres = nt.nodes.new("ShaderNodeLayerWeight")
        fres.location = (0, -400)
        mul = _math(nt, "MULTIPLY", loc=(300, -400))
        _link(nt, alpha, mul.inputs[0])
        _link(nt, fres.outputs["Facing"], mul.inputs[1])
        alpha = mul.outputs[0]
    if name == "Air":
        bsdf.inputs["Alpha"].default_value = 0.0
    else:
        _link(nt, alpha, bsdf.inputs["Alpha"])
    return rough, metal


def _base_sockets(nt):
    color = _attr(nt, ATTR_COLOR, (-1400, 300))
    # Unions with UsePartColor off keep each original part's colour per face
    face_col = nt.nodes.new("ShaderNodeAttribute")
    face_col.attribute_type = "GEOMETRY"
    face_col.attribute_name = "rbx_color"
    face_col.location = (-1600, 500)
    use = nt.nodes.new("ShaderNodeAttribute")
    use.attribute_type = "GEOMETRY"
    use.attribute_name = "rbx_use_color"
    use.location = (-1600, 650)
    mix = _mix_rgb(nt, "MIX", (-1200, 400))
    _link(nt, use.outputs["Fac"], mix.inputs["Factor"])
    _link(nt, color.outputs["Color"], mix.inputs["A"])
    _link(nt, face_col.outputs["Color"], mix.inputs["B"])
    t = _attr(nt, ATTR_TRANSPARENCY, (-1400, 0))
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(-1200, 0))
    _link(nt, t.outputs["Fac"], inv.inputs[1])
    return mix.outputs["Result"], inv.outputs[0]


def variant_signature(variant):
    if variant is None:
        return ""
    return "|".join([variant.base_material, str(round(variant.studs_per_tile, 4))] +
                    [i.name if i else "" for i in (variant.color_map, variant.normal_map,
                                                   variant.roughness_map, variant.metalness_map)])


def terrain_material(name):
    """Terrain material: like the part material, with the side texture on slopes."""
    return part_material(name, terrain=True)


WATER_TILE_STUDS = 20.0  # how far one wave texture tile spans (estimated by eye)


def _water_sequence(path, label):
    """One copy of the wave frame sequence per sampler (a Blender image keeps
    only one frame on the GPU, so two frames of a crossfade need two images)."""
    name = "RBX Water Waves " + label
    img = bpy.data.images.get(name)
    if img is None or os.path.normcase(bpy.path.abspath(img.filepath)) != os.path.normcase(path):
        img = bpy.data.images.load(path, check_existing=False)
        img.name = name
    img.source = "SEQUENCE"
    try:
        img.colorspace_settings.name = "Non-Color"
    except TypeError:
        pass
    return img


def water_material(wave_size=0.15, wave_speed=10.0, reflectance=1.0):
    """Terrain water: Roblox's animated wave normal maps (once downloaded, else
    animated noise), Fresnel reflections, and a WaterColor tint that never
    fully disappears (Roblox still shows the surface at WaterTransparency 1)."""
    from . import robloxmats
    name = "RBX Terrain Water"
    sig = "water|%s|%.3f|%.3f|%.3f" % (texture_signature(), wave_size, wave_speed, reflectance)
    mat = bpy.data.materials.get(name)
    if mat is not None:
        if not mat.get("rblx_managed") or (mat.get("rblx_variant_sig") == sig and
                                           mat.get("rblx_version", 1) >= MATERIAL_VERSION):
            return mat
        if mat.node_tree is not None and mat.node_tree.animation_data:
            mat.node_tree.animation_data_clear()
        nt, bsdf = _init_tree(mat)
    else:
        mat, nt, bsdf = _new_material(name)
    mat["rblx_style"] = material_style()
    mat["rblx_version"] = MATERIAL_VERSION
    mat["rblx_variant_sig"] = sig
    mat["rblx_water"] = [float(wave_size), float(wave_speed), float(reflectance)]
    mat["rblx_terrain"] = True
    out = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial")

    color = _attr(nt, ATTR_COLOR, (-600, 300))
    trans = _attr(nt, ATTR_TRANSPARENCY, (-900, -300))
    _link(nt, color.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.33
    spec = _input(bsdf, "Specular IOR Level", "Specular")
    if spec is not None:
        spec.default_value = 0.5 * max(0.0, min(1.0, reflectance)) + 0.1

    # Waves: frames per second follow WaterWaveSpeed (10 = Roblox's default)
    fps = bpy.context.scene.render.fps / max(bpy.context.scene.render.fps_base, 1e-6) \
        if bpy.context.scene else 24.0
    rate = max(wave_speed, 0.0) * 0.8 / max(fps, 1.0)  # wave frames per scene frame
    strength = max(0.0, min(3.0, 0.55 * wave_size / 0.15))
    frames = robloxmats.water_frames() if use_roblox_textures() else []
    normal_col = None
    if frames and strength > 0.0:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (-1300, -700)
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (-1100, -700)
        mapping.inputs["Scale"].default_value = (1.0 / (WATER_TILE_STUDS * coords.stud_scale()),) * 3
        _link(nt, coord.outputs["Object"], mapping.inputs["Vector"])
        texs = []
        for k, label in enumerate(("A", "B")):
            node = _image_node(nt, _water_sequence(frames[0], label), (-850, -600 - 300 * k))
            node.name = "Water Waves " + label
            iu = node.image_user
            iu.frame_duration = len(frames)
            iu.frame_start = 1
            iu.use_cyclic = True
            iu.use_auto_refresh = True
            fc = iu.driver_add("frame_offset")
            fc.driver.type = "SCRIPTED"
            fc.driver.expression = "floor(frame * %.6f) + %d - frame" % (rate, k)
            _link(nt, mapping.outputs["Vector"], node.inputs["Vector"])
            texs.append(node)
        blend = nt.nodes.new("ShaderNodeValue")
        blend.name = blend.label = "Water Wave Blend"
        blend.location = (-850, -1250)
        fc = blend.outputs[0].driver_add("default_value")
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = "frame * %.6f - floor(frame * %.6f)" % (rate, rate)
        mix = _mix_rgb(nt, "MIX", (-550, -700))
        _link(nt, blend.outputs[0], mix.inputs["Factor"])
        _link(nt, texs[0].outputs["Color"], mix.inputs["A"])
        _link(nt, texs[1].outputs["Color"], mix.inputs["B"])
        normal_col = mix.outputs["Result"]
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -700)
        nmap.inputs["Strength"].default_value = strength
        _link(nt, normal_col, nmap.inputs["Color"])
        _link(nt, nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif strength > 0.0:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (-1100, -700)
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.noise_dimensions = "4D"
        noise.location = (-850, -700)
        noise.inputs["Scale"].default_value = 0.6 / coords.stud_scale()
        noise.inputs["Detail"].default_value = 4.0
        _link(nt, coord.outputs["Object"], noise.inputs["Vector"])
        fc = noise.inputs["W"].driver_add("default_value")
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = "frame * %.6f" % (rate * 0.1)
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (-300, -700)
        bump.inputs["Strength"].default_value = 0.25 * strength
        _link(nt, noise.outputs["Fac"], bump.inputs["Height"])
        _link(nt, bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Opacity: WaterTransparency, a minimum tint, plus Fresnel at grazing angles
    opacity = _math(nt, "MULTIPLY_ADD", loc=(-600, -300))
    opacity.inputs[1].default_value = -0.8
    opacity.inputs[2].default_value = 0.92  # T=0 -> 0.92, T=1 -> 0.12
    _link(nt, trans.outputs["Fac"], opacity.inputs[0])
    fres = nt.nodes.new("ShaderNodeFresnel")
    fres.location = (-600, -500)
    fres.inputs["IOR"].default_value = 1.33
    if bsdf.inputs["Normal"].is_linked:
        _link(nt, bsdf.inputs["Normal"].links[0].from_socket, fres.inputs["Normal"])
    refl = _math(nt, "MULTIPLY", b=max(0.0, min(1.0, reflectance)), loc=(-400, -500))
    _link(nt, fres.outputs["Fac"], refl.inputs[0])
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(-400, -350))
    _link(nt, opacity.outputs[0], inv.inputs[1])
    extra = _math(nt, "MULTIPLY", loc=(-250, -400))
    _link(nt, inv.outputs[0], extra.inputs[0])
    _link(nt, refl.outputs[0], extra.inputs[1])
    total = _math(nt, "ADD", loc=(-100, -350))
    total.use_clamp = True
    _link(nt, opacity.outputs[0], total.inputs[0])
    _link(nt, extra.outputs[0], total.inputs[1])
    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (600, -250)
    mixs = nt.nodes.new("ShaderNodeMixShader")
    mixs.location = (750, 0)
    _link(nt, total.outputs[0], mixs.inputs[0])
    _link(nt, transparent.outputs[0], mixs.inputs[1])
    _link(nt, bsdf.outputs["BSDF"], mixs.inputs[2])
    _link(nt, mixs.outputs[0], out.inputs["Surface"])
    out.location = (950, 0)
    mat.diffuse_color = (0.05, 0.33, 0.36, 0.6)
    mat.roughness = 0.03
    return mat


def part_material(name, variant=None, terrain=False):
    """Shared material for a Roblox material type (or one of MaterialService's
    MaterialVariants of it)."""
    if variant is not None:
        mat_name = "RBX Variant " + variant.name
    else:
        mat_name = ("RBX Terrain " if terrain else "RBX ") + name
    style = material_style()
    sig = variant_signature(variant) + "|" + texture_signature()
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        if not mat.get("rblx_managed") or (mat.get("rblx_style", "2022") == style and
                                           mat.get("rblx_version", 1) >= MATERIAL_VERSION and
                                           mat.get("rblx_variant_sig", "") == sig):
            return mat
        nt, bsdf = _init_tree(mat)  # rebuild in place (other style, version or variant maps)
    else:
        mat, nt, bsdf = _new_material(mat_name)
    mat["rblx_style"] = style
    mat["rblx_version"] = MATERIAL_VERSION
    mat["rblx_variant_sig"] = sig
    color, alpha = _base_sockets(nt)
    rough, metal = _part_shading(nt, bsdf, name, color, alpha, style, variant, terrain)
    mat["rblx_terrain"] = terrain
    mat.diffuse_color = (0.64, 0.64, 0.65, 1.0)
    mat.roughness = rough
    mat.metallic = metal
    return mat


# ---------------------------------------------------------------------------
# Texture layers

def decal_wraps(obj, layer):
    """Roblox draws Decals and Textures on mesh parts (MeshParts and
    SpecialMesh file meshes) with the mesh's own UVs, ignoring Face, so they
    wrap like TextureID. Only blocks and other basic shapes project onto a face."""
    return layer.mapping in ("FACE", "TILED") and obj.rblx.shape == "MESH"


def _layer_vector(nt, obj, layer, idx, x, y, shared):
    """Image coordinates for one layer; returns (vector socket, mask socket or None)."""
    r = obj.rblx
    if layer.mapping in ("UV", "TEMPLATE") or decal_wraps(obj, layer):
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.location = (x - 250, y)
        name = "UVMap"
        if layer.mapping == "TEMPLATE" and obj.type == "MESH" and \
                obj.data.uv_layers.get("RBX_Template_" + layer.template_region) is not None:
            name = "RBX_Template_" + layer.template_region
        if obj.type == "MESH" and obj.data.uv_layers.get(name) is not None:
            uv.uv_map = name
        return uv.outputs["UV"], None

    # Projection onto one face (Decal / Texture)
    from .geometry import _bl, face_axes
    n, u, up = face_axes(layer.face)
    n_bl, u_bl, up_bl = _bl(n), _bl(u), _bl(up)
    scale = coords.stud_scale()

    obj_co = shared["object"]
    su = _vmath(nt, "DOT_PRODUCT", (x - 700, y + 60), b=u_bl)
    sv = _vmath(nt, "DOT_PRODUCT", (x - 700, y - 60), b=up_bl)
    _link(nt, obj_co, su.inputs[0])
    _link(nt, obj_co, sv.inputs[0])

    size = shared["size"]  # studs, Roblox axes
    hu = _vmath(nt, "DOT_PRODUCT", (x - 900, y + 200),
                b=Vector((abs(u.x), abs(u.y), abs(u.z))) * (scale / 2.0))
    hv = _vmath(nt, "DOT_PRODUCT", (x - 900, y + 100),
                b=Vector((abs(up.x), abs(up.y), abs(up.z))) * (scale / 2.0))
    _link(nt, size, hu.inputs[0])
    _link(nt, size, hv.inputs[0])

    if layer.mapping == "FACE":
        # U = su / (2 hu) + 0.5
        du = _math(nt, "MULTIPLY", b=2.0, loc=(x - 600, y + 200))
        _link(nt, hu.outputs["Value"], du.inputs[0])
        uu = _math(nt, "DIVIDE", loc=(x - 450, y + 60))
        _link(nt, su.outputs["Value"], uu.inputs[0])
        _link(nt, du.outputs[0], uu.inputs[1])
        uu2 = _math(nt, "ADD", b=0.5, loc=(x - 300, y + 60))
        _link(nt, uu.outputs[0], uu2.inputs[0])
        dv = _math(nt, "MULTIPLY", b=2.0, loc=(x - 600, y + 100))
        _link(nt, hv.outputs["Value"], dv.inputs[0])
        vv = _math(nt, "DIVIDE", loc=(x - 450, y - 60))
        _link(nt, sv.outputs["Value"], vv.inputs[0])
        _link(nt, dv.outputs[0], vv.inputs[1])
        vv2 = _math(nt, "ADD", b=0.5, loc=(x - 300, y - 60))
        _link(nt, vv.outputs[0], vv2.inputs[0])
        u_out, v_out = uu2.outputs[0], vv2.outputs[0]
    else:
        # TILED: U = (su + hu + OffsetStudsU*scale) / (StudsPerTileU*scale)
        base = "rblx.layers[%d]." % idx
        ou = _attr(nt, base + "offset_studs_u", (x - 900, y - 150))
        ov = _attr(nt, base + "offset_studs_v", (x - 900, y - 250))
        tu = _attr(nt, base + "studs_per_tile_u", (x - 900, y - 350))
        tv = _attr(nt, base + "studs_per_tile_v", (x - 900, y - 450))

        def axis(s_sock, h_sock, off, tile, yy):
            a = _math(nt, "ADD", loc=(x - 600, yy))
            _link(nt, s_sock, a.inputs[0])
            _link(nt, h_sock, a.inputs[1])
            b = _math(nt, "MULTIPLY_ADD", loc=(x - 450, yy))
            _link(nt, off.outputs["Fac"], b.inputs[0])
            b.inputs[1].default_value = scale
            _link(nt, a.outputs[0], b.inputs[2])
            t = _math(nt, "MULTIPLY", b=scale, loc=(x - 600, yy - 120))
            _link(nt, tile.outputs["Fac"], t.inputs[0])
            d = _math(nt, "DIVIDE", loc=(x - 300, yy))
            _link(nt, b.outputs[0], d.inputs[0])
            _link(nt, t.outputs[0], d.inputs[1])
            return d.outputs[0]

        u_out = axis(su.outputs["Value"], hu.outputs["Value"], ou, tu, y + 60)
        v_out = axis(sv.outputs["Value"], hv.outputs["Value"], ov, tv, y - 60)

    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    comb.location = (x - 150, y)
    _link(nt, u_out, comb.inputs["X"])
    _link(nt, v_out, comb.inputs["Y"])

    # Only surfaces facing the chosen side receive the image
    nd = _vmath(nt, "DOT_PRODUCT", (x - 450, y - 200), b=n_bl)
    _link(nt, shared["normal"], nd.inputs[0])
    mask = nt.nodes.new("ShaderNodeMapRange")
    mask.location = (x - 300, y - 200)
    mask.inputs["From Min"].default_value = 0.35
    mask.inputs["From Max"].default_value = 0.5
    _link(nt, nd.outputs["Value"], mask.inputs["Value"])
    return comb.outputs["Vector"], mask.outputs["Result"]


def _shared_inputs(nt, obj):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-2600, -400)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-2600, -700)
    vt = nt.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type = "NORMAL"
    vt.convert_from = "WORLD"
    vt.convert_to = "OBJECT"
    vt.location = (-2400, -700)
    _link(nt, geo.outputs["Normal"], vt.inputs["Vector"])
    norm = _vmath(nt, "NORMALIZE", (-2200, -700))
    _link(nt, vt.outputs["Vector"], norm.inputs[0])
    size_attr = "rblx.initial_size" if obj.rblx.shape in ("MESH", "UNION") else "rblx.size"
    size = _attr(nt, size_attr, (-2600, -1000))
    return {"object": tc.outputs["Object"], "normal": norm.outputs["Vector"],
            "size": size.outputs["Vector"]}


def _build_layered(mat, obj):
    nt, bsdf = _init_tree(mat)
    color, alpha = _base_sockets(nt)
    shared = None
    x, y = -1000, 600
    for idx, layer in enumerate(obj.rblx.layers):
        if not layer.enabled or layer.image is None:
            continue
        if layer.mapping in ("FACE", "TILED") and not decal_wraps(obj, layer) and shared is None:
            shared = _shared_inputs(nt, obj)
        vec, mask = _layer_vector(nt, obj, layer, idx, x, y, shared)
        ext = "REPEAT" if layer.mapping in ("UV", "TILED") or decal_wraps(obj, layer) else "CLIP"
        tex = _image_node(nt, layer.image, (x, y), extension=ext)
        _link(nt, vec, tex.inputs["Vector"])

        base = "rblx.layers[%d]." % idx
        tint = _attr(nt, base + "color", (x, y - 300))
        tinted = _mix_rgb(nt, "MULTIPLY", (x + 300, y), factor=1.0)
        _link(nt, tex.outputs["Color"], tinted.inputs["A"])
        _link(nt, tint.outputs["Color"], tinted.inputs["B"])

        lt = _attr(nt, base + "transparency", (x, y - 450))
        lvis = _math(nt, "SUBTRACT", a=1.0, loc=(x + 200, y - 450))
        _link(nt, lt.outputs["Fac"], lvis.inputs[1])
        la = _math(nt, "MULTIPLY", loc=(x + 350, y - 350))
        _link(nt, tex.outputs["Alpha"], la.inputs[0])
        _link(nt, lvis.outputs[0], la.inputs[1])
        la_out = la.outputs[0]
        if mask is not None:
            m = _math(nt, "MULTIPLY", loc=(x + 450, y - 450))
            _link(nt, la_out, m.inputs[0])
            _link(nt, mask, m.inputs[1])
            la_out = m.outputs[0]

        mix = _mix_rgb(nt, "MIX", (x + 550, y + 100))
        _link(nt, la_out, mix.inputs["Factor"])
        _link(nt, color, mix.inputs["A"])
        _link(nt, tinted.outputs["Result"], mix.inputs["B"])
        color = mix.outputs["Result"]

        # alpha = alpha + (1 - alpha) * layer_alpha
        inv = _math(nt, "SUBTRACT", a=1.0, loc=(x + 550, y - 300))
        _link(nt, alpha, inv.inputs[1])
        acc = _math(nt, "MULTIPLY_ADD", loc=(x + 700, y - 300))
        _link(nt, inv.outputs[0], acc.inputs[0])
        _link(nt, la_out, acc.inputs[1])
        _link(nt, alpha, acc.inputs[2])
        alpha = acc.outputs[0]
        y -= 700
    style = material_style()
    from . import materialservice
    _part_shading(nt, bsdf, obj.rblx.material, color, alpha, style,
                  materialservice.variant_for(obj))
    mat["rblx_layered"] = True
    mat["rblx_style"] = style
    mat.diffuse_color = (*obj.rblx.color, 1.0)


def _has_layers(obj):
    return any(l.enabled and l.image is not None for l in obj.rblx.layers)


def refresh(obj):
    """Assign the right material for the part's current settings/layers."""
    r = obj.rblx
    if r.kind != "PART" or obj.type != "MESH":
        return
    if r.material_mode == "SURFACE":
        return
    if _has_layers(obj):
        from .geometry import ensure_template_uvs
        ensure_template_uvs(obj)
        ensure_slot(obj)
        mat = obj.material_slots[0].material
        if mat is None or not mat.get("rblx_layered") or mat.users > 1:
            mat = bpy.data.materials.new("RBX " + obj.name)
            assign(obj, mat)
        _build_layered(mat, obj)
        r.material_mode = "LAYERED"
    else:
        old = obj.material_slots[0].material if obj.material_slots else None
        r.material_mode = "BASIC"
        from . import materialservice
        assign(obj, part_material(r.material, materialservice.variant_for(obj)))
        if old is not None and old.get("rblx_layered") and old.users == 0:
            bpy.data.materials.remove(old)


def apply_material_style(scene):
    """Rebuild every Roblox material for the scene's material style
    (MaterialService.Use2022Materials)."""
    for obj in scene.objects:
        if obj.rblx.kind == "PART" and obj.type == "MESH" and obj.rblx.material_mode != "SURFACE":
            refresh(obj)
    # shared materials (and terrain ones): part_material rebuilds whichever are out of date
    for mat in list(bpy.data.materials):
        if not mat.get("rblx_managed") or mat.get("rblx_layered"):
            continue
        if mat.get("rblx_water") is not None:
            water_material(*[float(v) for v in mat["rblx_water"]])
        elif mat.name.startswith("RBX Terrain ") and mat.name[12:] in PRESETS:
            terrain_material(mat.name[12:])
        elif mat.name.startswith("RBX ") and mat.name[4:] in PRESETS:
            part_material(mat.name[4:])


rebuild_all = apply_material_style


# ---------------------------------------------------------------------------
# SurfaceAppearance

def surface_appearance_material(name, maps, alpha_mode=0, tint=(1.0, 1.0, 1.0)):
    """maps: dict of role -> image (color, normal, roughness, metalness)."""
    mat_name = "RBX SurfaceAppearance " + name
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material(mat_name)
    color_attr = _attr(nt, ATTR_COLOR, (-900, 0))
    base = color_attr.outputs["Color"]
    alpha_extra = None
    if maps.get("color"):
        tex = _image_node(nt, maps["color"], (-900, 300))
        tinted = _mix_rgb(nt, "MULTIPLY", (-600, 300), factor=1.0)
        tinted.inputs["B"].default_value = (*tint, 1.0)
        _link(nt, tex.outputs["Color"], tinted.inputs["A"])
        if alpha_mode == 1:  # Transparency: alpha cuts the surface
            base = tinted.outputs["Result"]
            alpha_extra = tex.outputs["Alpha"]
        else:  # Overlay: alpha reveals the part color underneath
            mix = _mix_rgb(nt, "MIX", (-350, 200))
            _link(nt, tex.outputs["Alpha"], mix.inputs["Factor"])
            _link(nt, color_attr.outputs["Color"], mix.inputs["A"])
            _link(nt, tinted.outputs["Result"], mix.inputs["B"])
            base = mix.outputs["Result"]
    _link(nt, base, bsdf.inputs["Base Color"])
    if maps.get("roughness"):
        tex = _image_node(nt, maps["roughness"], (-600, -250))
        _link(nt, tex.outputs["Color"], bsdf.inputs["Roughness"])
    if maps.get("metalness"):
        tex = _image_node(nt, maps["metalness"], (-600, -500))
        _link(nt, tex.outputs["Color"], bsdf.inputs["Metallic"])
    if maps.get("normal"):
        tex = _image_node(nt, maps["normal"], (-600, -750))
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -700)
        _link(nt, tex.outputs["Color"], nmap.inputs["Color"])
        _link(nt, nmap.outputs["Normal"], bsdf.inputs["Normal"])
    t = _attr(nt, ATTR_TRANSPARENCY, (-700, -1000))
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(-450, -1000))
    _link(nt, t.outputs["Fac"], inv.inputs[1])
    alpha = inv.outputs[0]
    if alpha_extra is not None:
        mul = _math(nt, "MULTIPLY", loc=(-250, -1000))
        _link(nt, alpha, mul.inputs[0])
        _link(nt, alpha_extra, mul.inputs[1])
        alpha = mul.outputs[0]
    _link(nt, alpha, bsdf.inputs["Alpha"])
    return mat


# ---------------------------------------------------------------------------
# Assignment and layers

def ensure_slot(obj):
    if obj.type != "MESH" or obj.data is None:
        return
    if len(obj.data.materials) == 0:
        obj.data.materials.append(None)
    slot = obj.material_slots[0]
    if slot.link != "OBJECT":
        slot.link = "OBJECT"


def assign(obj, mat):
    ensure_slot(obj)
    if obj.material_slots:
        obj.material_slots[0].material = mat


def add_layer(obj, image=None, mapping="FACE", name=None, kind="Image", source="",
              face="FRONT", color=(1.0, 1.0, 1.0), transparency=0.0, region="TORSO",
              tiling=(2.0, 2.0, 0.0, 0.0), rebuild=True):
    """Add a texture layer to a part (on top of the existing ones)."""
    from .props import suspend_updates
    r = obj.rblx
    with suspend_updates():
        layer = r.layers.add()
        layer.name = name or (image.name if image else kind)
        layer.kind = kind
        layer.source = source or ""
        layer.mapping = mapping
        layer.face = face
        layer.template_region = region
        layer.color = color
        layer.transparency = transparency
        (layer.studs_per_tile_u, layer.studs_per_tile_v,
         layer.offset_studs_u, layer.offset_studs_v) = tiling
        layer.image = image
        layer.missing = image is None and bool(source)
    r.active_layer = len(r.layers) - 1
    if rebuild:
        refresh(obj)
    return layer


def resolve_layer_image(layer, resolver):
    """Find/download the image for a layer from its source. Returns True if found."""
    src = layer.source
    if not src:
        return layer.image is not None
    if src.strip().lower() == "rbxasset://textures/face.png":
        path = resolver.resolve_image(src)
        img = load_image(path) if path else classic_face_image()
    else:
        path = resolver.resolve_image(src)
        img = load_image(path) if path else None
    if img is not None:
        layer.image = img
        layer.missing = False
        return True
    layer.missing = True
    return False
