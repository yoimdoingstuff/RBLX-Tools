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


def _find_material_textures(folder, name):
    """Look for <name>.png / <name>_color.png / _normal / _roughness / _metalness."""
    if not folder or not os.path.isdir(folder):
        return {}
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

def _part_shading(nt, bsdf, name, base_color, alpha):
    """Wire the Roblox material look into `bsdf`. `base_color` is a colour
    socket (the part colour, possibly with layers); `alpha` an alpha socket."""
    rough, metal, bump_strength, bump_scale, extra = PRESETS.get(name, PRESETS["Plastic"])
    p = prefs.get()
    textures = _find_material_textures(bpy.path.abspath(p.material_folder) if p else "", name)
    tile = 1.0 / max((p.material_tile_studs if p else 4.0), 0.01) / coords.stud_scale()

    if "color" in textures:
        img = load_image(textures["color"])
        if img:
            tex = _image_node(nt, img, (-200, 650), box_projection_scale=tile)
            mul = _mix_rgb(nt, "MULTIPLY", (250, 450), factor=1.0)
            _link(nt, base_color, mul.inputs["A"])
            _link(nt, tex.outputs["Color"], mul.inputs["B"])
            base_color = mul.outputs["Result"]
    _link(nt, base_color, bsdf.inputs["Base Color"])

    refl = _attr(nt, ATTR_REFLECTANCE, (-100, -150))
    rough_src = None
    if "roughness" in textures:
        img = load_image(textures["roughness"], non_color=True)
        if img:
            rough_src = _image_node(nt, img, (-200, -650), box_projection_scale=tile).outputs["Color"]
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
    _link(nt, mmax.outputs[0], bsdf.inputs["Metallic"])

    if "normal" in textures:
        img = load_image(textures["normal"], non_color=True)
        if img:
            tex = _image_node(nt, img, (-200, -900), box_projection_scale=tile)
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.location = (300, -800)
            _link(nt, tex.outputs["Color"], nmap.inputs["Color"])
            _link(nt, nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif bump_strength > 0.0:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.location = (0, -650)
        noise.inputs["Scale"].default_value = bump_scale / max(coords.stud_scale(), 1e-4)
        noise.inputs["Detail"].default_value = 6.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (300, -650)
        bump.inputs["Strength"].default_value = bump_strength
        _link(nt, noise.outputs["Fac"], bump.inputs["Height"])
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
    t = _attr(nt, ATTR_TRANSPARENCY, (-1400, 0))
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(-1200, 0))
    _link(nt, t.outputs["Fac"], inv.inputs[1])
    return color.outputs["Color"], inv.outputs[0]


def part_material(name):
    """Shared material for a Roblox material type."""
    mat_name = "RBX " + name
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material(mat_name)
    color, alpha = _base_sockets(nt)
    rough, metal = _part_shading(nt, bsdf, name, color, alpha)
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
    _part_shading(nt, bsdf, obj.rblx.material, color, alpha)
    mat["rblx_layered"] = True
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
        assign(obj, part_material(r.material))
        if old is not None and old.get("rblx_layered") and old.users == 0:
            bpy.data.materials.remove(old)


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
