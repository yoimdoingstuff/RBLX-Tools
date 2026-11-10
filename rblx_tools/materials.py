"""Roblox-style materials.

Part materials are shared per Roblox material type ("RBX Plastic", ...). The
part's Color / Transparency / Reflectance are read per object through
Attribute nodes (rblx.color, rblx.transparency, rblx.reflectance), so one
material serves every part and those values can be keyframed."""

import os

import bpy

from . import assets, prefs

ATTR_COLOR = "rblx.color"
ATTR_TRANSPARENCY = "rblx.transparency"
ATTR_REFLECTANCE = "rblx.reflectance"

# Approximations of Roblox materials when no texture folder is provided.
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

# Socket names changed between Blender versions; try each.
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


def _new_material(name):
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    _set_render_method(mat)
    mat["rblx_managed"] = True
    return mat, nt, bsdf


def _attr(nt, name, loc):
    n = nt.nodes.new("ShaderNodeAttribute")
    n.attribute_type = "OBJECT"
    n.attribute_name = name
    n.location = loc
    return n


def _math(nt, op, a=None, b=None, loc=(0, 0)):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    if a is not None:
        n.inputs[0].default_value = a
    if b is not None:
        n.inputs[1].default_value = b
    return n


def _alpha_from_transparency(nt, bsdf, extra_alpha_socket=None):
    """Alpha = (1 - rblx.transparency) [* extra]."""
    t = _attr(nt, ATTR_TRANSPARENCY, (-700, -350))
    inv = _math(nt, "SUBTRACT", a=1.0, loc=(-450, -350))
    nt.links.new(t.outputs["Fac"], inv.inputs[1])
    alpha_out = inv.outputs[0]
    if extra_alpha_socket is not None:
        mul = _math(nt, "MULTIPLY", loc=(-250, -350))
        nt.links.new(alpha_out, mul.inputs[0])
        nt.links.new(extra_alpha_socket, mul.inputs[1])
        alpha_out = mul.outputs[0]
    nt.links.new(alpha_out, bsdf.inputs["Alpha"])
    return alpha_out


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


def _image_node(nt, img, loc, box_projection_scale=None):
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = loc
    if box_projection_scale:
        tex.projection = "BOX"
        tex.projection_blend = 0.2
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (loc[0] - 400, loc[1])
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (loc[0] - 200, loc[1])
        mapping.inputs["Scale"].default_value = (box_projection_scale,) * 3
        nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
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
# Material builders

def part_material(name):
    """Shared material for a Roblox material type."""
    mat_name = "RBX " + name
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material(mat_name)
    rough, metal, bump_strength, bump_scale, extra = PRESETS.get(name, PRESETS["Plastic"])

    color = _attr(nt, ATTR_COLOR, (-900, 200))
    base_color = color.outputs["Color"]

    p = prefs.get()
    textures = _find_material_textures(bpy.path.abspath(p.material_folder) if p else "", name)
    tile = 1.0 / max((p.material_tile_studs if p else 4.0), 0.01)
    from . import coords
    tile /= coords.stud_scale()

    if "color" in textures:
        img = load_image(textures["color"])
        if img:
            tex = _image_node(nt, img, (-700, 450), box_projection_scale=tile)
            mul = nt.nodes.new("ShaderNodeMix")
            mul.data_type = "RGBA"
            mul.blend_type = "MULTIPLY"
            mul.location = (-300, 300)
            mul.inputs["Factor"].default_value = 1.0
            nt.links.new(base_color, mul.inputs["A"])
            nt.links.new(tex.outputs["Color"], mul.inputs["B"])
            base_color = mul.outputs["Result"]
    nt.links.new(base_color, bsdf.inputs["Base Color"])

    # Roughness / metallic, pushed toward mirror-like by Reflectance
    refl = _attr(nt, ATTR_REFLECTANCE, (-900, -100))
    rough_src = None
    if "roughness" in textures:
        img = load_image(textures["roughness"], non_color=True)
        if img:
            rough_src = _image_node(nt, img, (-700, -650), box_projection_scale=tile).outputs["Color"]
    rmap = nt.nodes.new("ShaderNodeMapRange")
    rmap.location = (-450, -50)
    rmap.inputs["To Min"].default_value = rough
    rmap.inputs["To Max"].default_value = 0.05
    nt.links.new(refl.outputs["Fac"], rmap.inputs["Value"])
    if rough_src is not None:
        # Lerp texture roughness toward 0.05 by reflectance
        lerp = nt.nodes.new("ShaderNodeMix")
        lerp.data_type = "FLOAT"
        lerp.location = (-250, -50)
        lerp.inputs["B"].default_value = 0.05
        nt.links.new(refl.outputs["Fac"], lerp.inputs["Factor"])
        nt.links.new(rough_src, lerp.inputs["A"])
        nt.links.new(lerp.outputs["Result"], bsdf.inputs["Roughness"])
    else:
        nt.links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])

    mmax = _math(nt, "MAXIMUM", b=metal, loc=(-450, 100))
    nt.links.new(refl.outputs["Fac"], mmax.inputs[0])
    nt.links.new(mmax.outputs[0], bsdf.inputs["Metallic"])

    # Surface detail
    if "normal" in textures:
        img = load_image(textures["normal"], non_color=True)
        if img:
            tex = _image_node(nt, img, (-700, -900), box_projection_scale=tile)
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.location = (-300, -800)
            nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif bump_strength > 0.0:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.location = (-700, -600)
        noise.inputs["Scale"].default_value = bump_scale / max(coords.stud_scale(), 1e-4)
        noise.inputs["Detail"].default_value = 6.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (-300, -600)
        bump.inputs["Strength"].default_value = bump_strength
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    if extra.get("emission"):
        nt.links.new(color.outputs["Color"], _input(bsdf, *_SOCKETS["emission_color"]))
        bsdf.inputs["Emission Strength"].default_value = extra["emission"]
    if extra.get("transmission"):
        sock = _input(bsdf, *_SOCKETS["transmission"])
        if sock:
            sock.default_value = extra["transmission"]

    if extra.get("forcefield"):
        # Glowing, see-through shell
        nt.links.new(color.outputs["Color"], _input(bsdf, *_SOCKETS["emission_color"]))
        bsdf.inputs["Emission Strength"].default_value = 2.0
        fres = nt.nodes.new("ShaderNodeLayerWeight")
        fres.location = (-700, -450)
        _alpha_from_transparency(nt, bsdf, fres.outputs["Facing"])
    elif name == "Air":
        bsdf.inputs["Alpha"].default_value = 0.0
    else:
        _alpha_from_transparency(nt, bsdf)

    mat.diffuse_color = (0.64, 0.64, 0.65, 1.0)
    mat.roughness = rough
    mat.metallic = metal
    return mat


def textured_material(img):
    """MeshPart.TextureID / SpecialMesh.TextureId: image over the part
    color (transparent areas of the image show the part's Color)."""
    mat_name = "RBX Texture " + img.name
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material(mat_name)
    tex = _image_node(nt, img, (-700, 250))
    color = _attr(nt, ATTR_COLOR, (-700, 0))
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-300, 150)
    nt.links.new(tex.outputs["Alpha"], mix.inputs["Factor"])
    nt.links.new(color.outputs["Color"], mix.inputs["A"])
    nt.links.new(tex.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55
    _alpha_from_transparency(nt, bsdf)
    return mat


def decal_material(img, tiled=False):
    """Decal/Texture: image tinted by Color3, alpha = image alpha * (1 - Transparency)."""
    mat_name = ("RBX TiledTexture " if tiled else "RBX Decal ") + img.name
    mat = bpy.data.materials.get(mat_name)
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material(mat_name)
    tex = _image_node(nt, img, (-700, 250))
    if tiled:
        tex.extension = "REPEAT"
    else:
        tex.extension = "CLIP"
    color = _attr(nt, ATTR_COLOR, (-700, 0))
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.location = (-300, 150)
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], mul.inputs["A"])
    nt.links.new(color.outputs["Color"], mul.inputs["B"])
    nt.links.new(mul.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    _alpha_from_transparency(nt, bsdf, tex.outputs["Alpha"])
    return mat


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
        tinted = nt.nodes.new("ShaderNodeMix")
        tinted.data_type = "RGBA"
        tinted.blend_type = "MULTIPLY"
        tinted.location = (-600, 300)
        tinted.inputs["Factor"].default_value = 1.0
        tinted.inputs["B"].default_value = (*tint, 1.0)
        nt.links.new(tex.outputs["Color"], tinted.inputs["A"])
        if alpha_mode == 1:  # Transparency: alpha cuts the surface
            base = tinted.outputs["Result"]
            alpha_extra = tex.outputs["Alpha"]
        else:  # Overlay: alpha reveals the part color underneath
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.location = (-350, 200)
            nt.links.new(tex.outputs["Alpha"], mix.inputs["Factor"])
            nt.links.new(color_attr.outputs["Color"], mix.inputs["A"])
            nt.links.new(tinted.outputs["Result"], mix.inputs["B"])
            base = mix.outputs["Result"]
    nt.links.new(base, bsdf.inputs["Base Color"])
    if maps.get("roughness"):
        tex = _image_node(nt, maps["roughness"], (-600, -250))
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
    if maps.get("metalness"):
        tex = _image_node(nt, maps["metalness"], (-600, -500))
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Metallic"])
    if maps.get("normal"):
        tex = _image_node(nt, maps["normal"], (-600, -750))
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -700)
        nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    _alpha_from_transparency(nt, bsdf, alpha_extra)
    return mat


def missing_material():
    """Invisible stand-in for decals whose image hasn't been found yet."""
    mat = bpy.data.materials.get("RBX Missing Image")
    if mat is not None:
        return mat
    mat, nt, bsdf = _new_material("RBX Missing Image")
    bsdf.inputs["Alpha"].default_value = 0.0
    mat.diffuse_color = (1.0, 0.0, 1.0, 0.3)
    return mat


# ---------------------------------------------------------------------------
# Assignment

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


def refresh_texture(obj, resolver=None):
    """Re-resolve obj.rblx.texture_id and assign the matching material.
    Returns True if the image was found (or none is needed)."""
    r = obj.rblx
    if resolver is None:
        resolver = assets.default_resolver()

    if r.kind in ("DECAL", "TEXTURE"):
        path = resolver.resolve(r.texture_id)
        img = load_image(path) if path else None
        if img:
            assign(obj, decal_material(img, tiled=(r.kind == "TEXTURE")))
            r.asset_missing = False
            return True
        assign(obj, missing_material())
        r.asset_missing = bool(r.texture_id)
        return not r.texture_id

    if r.kind == "PART":
        if r.material_mode == "SURFACE":
            return True
        if r.texture_id:
            path = resolver.resolve(r.texture_id)
            img = load_image(path) if path else None
            if img:
                r.material_mode = "TEXTURED"
                assign(obj, textured_material(img))
                r.asset_missing = False
                return True
            r.asset_missing = True
        else:
            r.asset_missing = False
        r.material_mode = "BASIC"
        assign(obj, part_material(r.material))
        return not r.texture_id
    return True
