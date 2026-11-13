"""Terrain decoration (Terrain.Decoration: animated grass on Grass terrain)
and Roblox's Clouds (the Clouds instance under Terrain).

Roblox doesn't document either look. The grass is blades instanced over the
upward-facing Grass faces, GrassLength tall (scaled), coloured with the
terrain's Grass colour and swaying a little. The clouds are a noise-driven
layer high above the place, with Cover, Density and Color like Roblox's."""

import bpy

from . import coords
from .effects import _link, _math, _named, _set, _socket, _store, _vmath

GRASS_GROUP = "RBX Terrain Grass"
GRASS_VERSION = 2
GRASS_MATERIAL = "RBX Grass Blade"
GRASS_STUDS_PER_LENGTH = 1.6   # blade height (studs) at GrassLength 1
GRASS_DENSITY = 4.0            # clumps per square stud (render)
GRASS_VIEWPORT = 0.25          # share of them shown in the viewport
GRASS_DISTANCE = 140.0         # studs from the active camera (Roblox fades grass out too)


def _grass_material(color):
    mat = bpy.data.materials.get(GRASS_MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(GRASS_MATERIAL)
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (400, 0)
    _link(nt, bsdf.outputs["BSDF"], out.inputs["Surface"])
    col = nt.nodes.new("ShaderNodeAttribute")
    col.attribute_type = "GEOMETRY"  # stored per clump, kept per point after realizing
    col.attribute_name = "rbx_grass_color"
    col.location = (-400, 150)
    h = nt.nodes.new("ShaderNodeAttribute")
    h.attribute_type = "GEOMETRY"
    h.attribute_name = "rbx_h"
    h.location = (-400, -100)
    # darker at the root, a little lighter at the tip
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.location = (-200, -100)
    ramp.inputs["To Min"].default_value = 0.55
    ramp.inputs["To Max"].default_value = 1.15
    _link(nt, h.outputs["Fac"], ramp.inputs["Value"])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.location = (100, 100)
    mul.inputs["Factor"].default_value = 1.0
    _link(nt, col.outputs["Color"], mul.inputs["A"])
    _link(nt, ramp.outputs["Result"], mul.inputs["B"])
    _link(nt, mul.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.7
    sub = bsdf.inputs.get("Subsurface Weight")
    if sub is not None:
        sub.default_value = 0.15
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    mat.diffuse_color = (*color, 1.0)
    mat["rblx_managed_grass"] = True
    return mat


def _grass_group():
    ng = bpy.data.node_groups.get(GRASS_GROUP)
    if ng is not None and ng.get("rblx_version", 0) >= GRASS_VERSION:
        return ng
    if ng is not None:
        ng.name = GRASS_GROUP + " (old)"
    ng = bpy.data.node_groups.new(GRASS_GROUP, "GeometryNodeTree")
    ng["rblx_version"] = GRASS_VERSION
    I_ = ng.interface
    I_.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    I_.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for sname, stype, default in (("Grass Slot", "NodeSocketInt", 0),
                                  ("Density", "NodeSocketFloat", GRASS_DENSITY),
                                  ("Viewport Share", "NodeSocketFloat", GRASS_VIEWPORT),
                                  ("Length", "NodeSocketFloat", 1.0),
                                  ("Color", "NodeSocketColor", (0.2, 0.3, 0.1, 1.0)),
                                  ("Material", "NodeSocketMaterial", None),
                                  ("Sway", "NodeSocketFloat", 0.12),
                                  ("Max Distance", "NodeSocketFloat", GRASS_DISTANCE)):
        s = I_.new_socket(sname, in_out="INPUT", socket_type=stype)
        if default is not None:
            s.default_value = default
    N = ng.nodes
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    gi.location, go.location = (-1600, 0), (1400, 0)
    I = gi.outputs

    # Where: Grass faces that face up
    mi = N.new("GeometryNodeInputMaterialIndex")
    mi.location = (-1300, -300)
    cmp = N.new("FunctionNodeCompare")
    cmp.data_type = "INT"
    cmp.operation = "EQUAL"
    cmp.location = (-1100, -300)
    ints = [s for s in cmp.inputs if s.type == "INT"]
    _link(ng, mi.outputs[0], ints[0])
    _link(ng, I["Grass Slot"], ints[1])
    nrm = N.new("GeometryNodeInputNormal")
    nrm.location = (-1300, -500)
    sep = N.new("ShaderNodeSeparateXYZ")
    sep.location = (-1100, -500)
    _link(ng, nrm.outputs[0], sep.inputs[0])
    up = _math(ng, "GREATER_THAN", sep.outputs["Z"], 0.55, loc=(-950, -500))
    sel0 = N.new("FunctionNodeBooleanMath")
    sel0.operation = "AND"
    sel0.location = (-800, -350)
    _link(ng, cmp.outputs[0], sel0.inputs[0])
    _link(ng, up, sel0.inputs[1])
    # Roblox only draws decoration grass near the camera
    cam = N.new("GeometryNodeInputActiveCamera")
    cam.location = (-1300, -1000)
    cinfo = N.new("GeometryNodeObjectInfo")
    cinfo.transform_space = "RELATIVE"  # camera position in this object's space
    cinfo.location = (-1100, -1000)
    _link(ng, cam.outputs[0], cinfo.inputs["Object"])
    fpos = N.new("GeometryNodeInputPosition")
    fpos.location = (-1100, -1150)
    dist_cam = _vmath(ng, "DISTANCE", fpos.outputs[0], cinfo.outputs["Location"], loc=(-950, -1050))
    near = _math(ng, "LESS_THAN", dist_cam,
                 _math(ng, "MULTIPLY", I["Max Distance"], coords.stud_scale(), loc=(-950, -1200)),
                 loc=(-800, -1050))
    sel = N.new("FunctionNodeBooleanMath")
    sel.operation = "AND"
    sel.location = (-650, -400)
    _link(ng, sel0.outputs[0], sel.inputs[0])
    _link(ng, near, sel.inputs[1])

    # How many: per square stud, fewer in the viewport
    isvp = N.new("GeometryNodeIsViewport")
    isvp.location = (-1100, -750)
    vpd = _math(ng, "MULTIPLY", I["Density"], I["Viewport Share"], loc=(-950, -850))
    sw = N.new("GeometryNodeSwitch")
    sw.input_type = "FLOAT"
    sw.location = (-800, -750)
    _link(ng, isvp.outputs[0], sw.inputs["Switch"])
    _link(ng, I["Density"], _socket(sw.inputs, "False"))
    _link(ng, vpd, _socket(sw.inputs, "True"))
    s2 = coords.stud_scale() ** 2
    dens = _math(ng, "DIVIDE", sw.outputs[0], s2, loc=(-650, -750))

    dist = N.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "RANDOM"
    dist.location = (-500, -300)
    _link(ng, I["Geometry"], dist.inputs["Mesh"])
    _link(ng, sel.outputs[0], dist.inputs["Selection"])
    _link(ng, dens, dist.inputs["Density"])
    pts = _store(ng, dist.outputs["Points"], "rbx_grass_color", I["Color"], "FLOAT_COLOR",
                 loc=(-300, -300))

    # One clump: three thin blades fanned around, 1 unit tall, rbx_h 0..1 up the blade
    blades = []
    for k in range(3):
        cone = N.new("GeometryNodeMeshCone")
        cone.fill_type = "NONE"
        cone.location = (-800, 400 - 200 * k)
        _set(cone, "Vertices", 3)
        _set(cone, "Side Segments", 2)
        _set(cone, "Radius Top", 0.0)
        _set(cone, "Radius Bottom", 0.045)
        _set(cone, "Depth", 1.0)
        tr = N.new("GeometryNodeTransform")
        tr.location = (-600, 400 - 200 * k)
        _set(tr, "Translation", ((k - 1) * 0.06, (k % 2) * 0.05, 0.5))
        _set(tr, "Rotation", ((k - 1) * 0.25, (k % 2 - 0.5) * 0.3, k * 2.1))
        _set(tr, "Scale", (1.0, 0.35, 0.8 + 0.15 * k))
        _link(ng, cone.outputs["Mesh"], tr.inputs["Geometry"])
        blades.append(tr.outputs["Geometry"])
    join = N.new("GeometryNodeJoinGeometry")
    join.location = (-400, 300)
    for b in reversed(blades):
        _link(ng, b, join.inputs[0])
    pos = N.new("GeometryNodeInputPosition")
    pos.location = (-400, 150)
    pz = N.new("ShaderNodeSeparateXYZ")
    pz.location = (-250, 150)
    _link(ng, pos.outputs[0], pz.inputs[0])
    clump = _store(ng, join.outputs[0], "rbx_h", _math(ng, "DIVIDE", pz.outputs["Z"], 1.15,
                                                       loc=(-100, 150)), loc=(50, 300))
    smat = N.new("GeometryNodeSetMaterial")
    smat.location = (200, 300)
    _link(ng, clump, smat.inputs["Geometry"])
    _link(ng, I["Material"], smat.inputs["Material"])

    # Placement: random turn, random height, a little sway (Roblox grass moves in the wind)
    rnd_rot = N.new("FunctionNodeRandomValue")
    rnd_rot.data_type = "FLOAT"
    rnd_rot.location = (0, -550)
    _set(rnd_rot, "Max", 6.283)
    rnd_h = N.new("FunctionNodeRandomValue")
    rnd_h.data_type = "FLOAT"
    rnd_h.location = (0, -750)
    _set(rnd_h, "Min", 0.6)
    _set(rnd_h, "Max", 1.15)
    _set(rnd_h, "Seed", 7)
    t = N.new("GeometryNodeInputSceneTime")
    t.location = (-300, -950)
    pos2 = N.new("GeometryNodeInputPosition")
    pos2.location = (-300, -1100)
    wave = _vmath(ng, "DOT_PRODUCT", pos2.outputs[0], (0.35 / coords.stud_scale(),
                                                       0.2 / coords.stud_scale(), 0.0),
                  loc=(-150, -1100))
    phase = _math(ng, "ADD", _math(ng, "MULTIPLY", t.outputs["Seconds"], 1.7, loc=(-150, -950)),
                  wave, loc=(0, -1000))
    sway = _math(ng, "MULTIPLY", _math(ng, "SINE", phase, loc=(150, -1000)), I["Sway"],
                 loc=(300, -1000))
    rot = N.new("ShaderNodeCombineXYZ")
    rot.location = (450, -700)
    _link(ng, sway, rot.inputs["X"])
    _link(ng, _math(ng, "MULTIPLY", sway, 0.6, loc=(300, -850)), rot.inputs["Y"])
    _link(ng, _socket(rnd_rot.outputs, "Value"), rot.inputs["Z"])
    hgt = _math(ng, "MULTIPLY", _socket(rnd_h.outputs, "Value"), I["Length"], loc=(300, -650))
    scl = N.new("ShaderNodeCombineXYZ")
    scl.location = (450, -500)
    _link(ng, _math(ng, "MULTIPLY", hgt, 0.7, loc=(300, -500)), scl.inputs["X"])
    _link(ng, _math(ng, "MULTIPLY", hgt, 0.7, loc=(300, -560)), scl.inputs["Y"])
    _link(ng, hgt, scl.inputs["Z"])
    inst = N.new("GeometryNodeInstanceOnPoints")
    inst.location = (650, -300)
    _link(ng, pts, inst.inputs["Points"])
    _link(ng, smat.outputs["Geometry"], inst.inputs["Instance"])
    _link(ng, rot.outputs[0], inst.inputs["Rotation"])
    _link(ng, scl.outputs[0], inst.inputs["Scale"])

    # one mesh instead of ~100k instances (much lighter for EEVEE)
    real = N.new("GeometryNodeRealizeInstances")
    real.location = (850, -300)
    _link(ng, inst.outputs["Instances"], real.inputs["Geometry"])
    jall = N.new("GeometryNodeJoinGeometry")
    jall.location = (1100, 0)
    _link(ng, real.outputs[0], jall.inputs[0])
    _link(ng, I["Geometry"], jall.inputs[0])
    _link(ng, jall.outputs[0], go.inputs["Geometry"])
    return ng


def add_grass(obj, grass_slot, color, grass_length=0.7):
    """Grass decoration on a terrain object (a Geometry Nodes modifier)."""
    from .effects import _input_ids, set_input
    mod = obj.modifiers.get("RBX Grass") or obj.modifiers.new("RBX Grass", "NODES")
    mod.node_group = _grass_group()
    ids = _input_ids(mod)
    mat = _grass_material(color)
    length = max(0.1, min(1.0, grass_length)) * GRASS_STUDS_PER_LENGTH * coords.stud_scale()
    for name, value in (("Grass Slot", int(grass_slot)), ("Length", length),
                        ("Color", (*color, 1.0)), ("Material", mat)):
        if name in ids:
            set_input(mod, ids[name], value)
    obj["rblx_grass_length"] = float(grass_length)
    return mod


# ---------------------------------------------------------------------------
# Clouds

CLOUD_HEIGHT_STUDS = 1200.0
CLOUD_SIZE_STUDS = 24000.0


def _cloud_material(cover, density, color):
    mat = bpy.data.materials.get("RBX Clouds") or bpy.data.materials.new("RBX Clouds")
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    if nt.animation_data:
        nt.animation_data_clear()
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (800, 0)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = (-900, 0)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    noise.location = (-650, 0)
    noise.inputs["Scale"].default_value = 40.0  # puffs a few hundred studs across
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.55
    _link(nt, coord.outputs["UV"], noise.inputs["Vector"])
    fc = noise.inputs["W"].driver_add("default_value")
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = "frame * 0.0005"  # slow drift
    # Cover 0..1: how much of the sky is cloud (threshold on the noise)
    rng = nt.nodes.new("ShaderNodeMapRange")
    rng.location = (-400, 0)
    lo = 0.68 - 0.36 * max(0.0, min(1.0, cover))
    rng.inputs["From Min"].default_value = lo
    rng.inputs["From Max"].default_value = lo + 0.12
    _link(nt, noise.outputs["Fac"], rng.inputs["Value"])
    # fade out toward the horizon
    grad = nt.nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "SPHERICAL"
    grad.location = (-650, -300)
    centred = _vmath(nt, "MULTIPLY_ADD", coord.outputs["UV"], (2.0, 2.0, 0.0), loc=(-800, -300))
    centred.node.inputs[2].default_value = (-1.0, -1.0, 0.0)
    _link(nt, centred, grad.inputs["Vector"])
    edge = _math(nt, "MULTIPLY", rng.outputs["Result"], grad.outputs["Fac"], loc=(-200, -100))
    alpha = _math(nt, "MULTIPLY", edge, 0.35 + 0.65 * max(0.0, min(1.0, density)), loc=(0, -100))
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 100)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    sub = bsdf.inputs.get("Subsurface Weight")
    if sub is not None:
        sub.default_value = 0.3
    # thinner clouds are brighter (less self-shadowing)
    em = bsdf.inputs.get("Emission Color")
    if em is not None:
        em.default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.25
    _link(nt, alpha, bsdf.inputs["Alpha"])
    _link(nt, bsdf.outputs["BSDF"], out.inputs["Surface"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    mat["rblx_clouds"] = [float(cover), float(density)]
    return mat


def build_clouds(collection, cover=0.5, density=0.7, color=(1.0, 1.0, 1.0), enabled=True,
                 name="Clouds"):
    """A cloud layer object for a Roblox Clouds instance."""
    from .rbx.color import to_linear
    s = coords.stud_scale()
    me = bpy.data.meshes.get("RBX Clouds") or None
    if me is None:
        size = CLOUD_SIZE_STUDS * s / 2
        me = bpy.data.meshes.new("RBX Clouds")
        me.from_pydata([(-size, -size, 0), (size, -size, 0), (size, size, 0), (-size, size, 0)],
                       [], [(0, 1, 2, 3)])
        me.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    obj.location = (0.0, 0.0, CLOUD_HEIGHT_STUDS * s)
    lin = to_linear(color)
    mat = _cloud_material(cover, density, lin)
    if not me.materials:
        me.materials.append(mat)
    else:
        me.materials[0] = mat
    if hasattr(obj, "visible_shadow"):
        obj.visible_shadow = False
    obj.hide_render = obj.hide_viewport = not enabled
    obj.rblx.class_name = "Clouds"
    obj["rblx_cover"] = float(cover)
    obj["rblx_density"] = float(density)
    return obj
