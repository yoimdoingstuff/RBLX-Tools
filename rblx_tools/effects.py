"""Roblox graphics effects in Blender.

Post-processing (Lighting / Camera children in Roblox): BloomEffect,
BlurEffect, ColorCorrectionEffect, SunRaysEffect (compositor) and
DepthOfFieldEffect (camera depth of field).

Effect objects: ParticleEmitter, Fire, Smoke and Sparkles (a Geometry Nodes
particle simulation with camera-facing sprites), Beam (textured ribbon between
two attachments) and Highlight (fill tint + outline)."""

import math

import bpy
from bpy.props import (BoolProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty)
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector

from . import coords
from .rbx.color import to_linear

COMP_NAME = "RBX Post Effects"
TEXTURE_DIR = "rbxasset://textures/particles/"
DEFAULT_PARTICLE_TEXTURE = TEXTURE_DIR + "sparkles_main.dds"
EFFECT_CLASSES = {"ParticleEmitter", "Fire", "Smoke", "Sparkles"}
POST_CLASSES = {"BloomEffect", "BlurEffect", "ColorCorrectionEffect", "DepthOfFieldEffect",
                "SunRaysEffect"}


# ---------------------------------------------------------------------------
# Small node helpers

def _socket(sockets, name, index=0):
    """The `index`-th enabled socket called `name` (nodes reuse names per type)."""
    found = [s for s in sockets if s.name == name and getattr(s, "enabled", True)]
    if not found:
        found = [s for s in sockets if s.name == name]
    return found[min(index, len(found) - 1)]


def _set(node, name, value):
    _socket(node.inputs, name).default_value = value


def _link(nt, a, b):
    nt.links.new(a, b)


def _math(nt, op, a=None, b=None, loc=(0, 0)):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            _link(nt, v, n.inputs[i])
    return n.outputs[0]


def _vmath(nt, op, a=None, b=None, loc=(0, 0), scale=None):
    n = nt.nodes.new("ShaderNodeVectorMath")
    n.operation = op
    n.location = loc
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (tuple, list, Vector)):
            n.inputs[i].default_value = v
        else:
            _link(nt, v, n.inputs[i])
    if scale is not None:
        if isinstance(scale, (int, float)):
            n.inputs["Scale"].default_value = scale
        else:
            _link(nt, scale, n.inputs["Scale"])
    out = "Value" if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else "Vector"
    return n.outputs[out]


def _sequence_curve(node, keypoints, normalize=1.0):
    """Load a Roblox NumberSequence [(time, value, envelope), ...] into a
    Float Curve node, as straight segments like Roblox."""
    mapping = node.mapping
    mapping.use_clip = True
    curve = mapping.curves[0]
    pts = sorted((max(0.0, min(1.0, k[0])), k[1] / normalize) for k in keypoints) or [(0, 1), (1, 1)]
    if pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1:
        pts.append((1.0, pts[-1][1]))
    while len(curve.points) > 2:
        curve.points.remove(curve.points[-1])
    curve.points[0].location = pts[0]
    curve.points[1].location = pts[-1]
    for p in pts[1:-1]:
        curve.points.new(*p)
    for p in curve.points:
        p.handle_type = "VECTOR"
    mapping.update()


def _color_ramp(ramp, keypoints):
    """Load a Roblox ColorSequence [(time, r, g, b, envelope), ...] (sRGB)."""
    cr = ramp.color_ramp
    cr.interpolation = "LINEAR"
    pts = sorted(keypoints) or [(0, 1, 1, 1, 0), (1, 1, 1, 1, 0)]
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    first = True
    for k in pts:
        col = (*to_linear(tuple(k[1:4])), 1.0)
        if first:
            cr.elements[0].position = max(0.0, min(1.0, k[0]))
            cr.elements[0].color = col
            first = False
        else:
            e = cr.elements.new(max(0.0, min(1.0, k[0])))
            e.color = col


def number_range(v, default):
    if isinstance(v, (tuple, list)) and len(v) >= 2:
        return float(v[0]), float(v[1])
    if isinstance(v, (int, float)):
        return float(v), float(v)
    return default


def number_sequence(v, default):
    if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)):
        return [tuple(k) for k in v]
    if isinstance(v, (int, float)):
        return [(0.0, float(v), 0.0), (1.0, float(v), 0.0)]
    return default


def color_sequence(v, default):
    if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)) and len(v[0]) >= 4:
        return [tuple(k) for k in v]
    if isinstance(v, tuple) and len(v) == 3:
        return [(0.0, *v, 0.0), (1.0, *v, 0.0)]
    return default


# ---------------------------------------------------------------------------
# Post-processing

def _on_post(self, context):
    if not getattr(self, "_applying", False):
        scene = getattr(context, "scene", None) or bpy.context.scene
        try:
            apply_post_effects(scene)
        except Exception as ex:  # never break property editing
            print("RBLX Tools: post effects:", ex)


def _on_preview(self, context):
    mode = "ALWAYS" if self.viewport_preview else "DISABLED"
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                shading = area.spaces.active.shading
                if hasattr(shading, "use_compositor"):
                    shading.use_compositor = mode
                area.tag_redraw()


class RBLX_PostEffectsProps(bpy.types.PropertyGroup):
    bloom_enabled: BoolProperty(name="Bloom", default=False, update=_on_post,
                                description="BloomEffect: bright parts glow")
    bloom_intensity: FloatProperty(name="Intensity", default=1.0, min=0.0, soft_max=1.0,
                                   update=_on_post)
    bloom_size: FloatProperty(name="Size", default=24.0, min=0.0, max=56.0, update=_on_post)
    bloom_threshold: FloatProperty(name="Threshold", default=2.0, min=0.0, max=4.0,
                                   update=_on_post)

    blur_enabled: BoolProperty(name="Blur", default=False, update=_on_post,
                               description="BlurEffect: blurs the whole screen")
    blur_size: FloatProperty(name="Size", default=24.0, min=0.0, max=56.0, update=_on_post)

    cc_enabled: BoolProperty(name="Color Correction", default=False, update=_on_post,
                             description="ColorCorrectionEffect")
    cc_brightness: FloatProperty(name="Brightness", default=0.0, min=-1.0, max=1.0,
                                 update=_on_post)
    cc_contrast: FloatProperty(name="Contrast", default=0.0, min=-1.0, max=1.0, update=_on_post)
    cc_saturation: FloatProperty(name="Saturation", default=0.0, min=-1.0, max=1.0,
                                 update=_on_post)
    cc_tint: FloatVectorProperty(name="TintColor", size=3, subtype="COLOR", min=0.0, max=1.0,
                                 default=(1.0, 1.0, 1.0), update=_on_post)

    dof_enabled: BoolProperty(name="Depth of Field", default=False, update=_on_post,
                              description="DepthOfFieldEffect (uses the scene camera)")
    dof_focus_distance: FloatProperty(name="FocusDistance", default=0.05, min=0.0, max=200.0,
                                      update=_on_post, description="Studs from the camera")
    dof_in_focus_radius: FloatProperty(name="InFocusRadius", default=10.0, min=0.0, max=50.0,
                                       update=_on_post)
    dof_far_intensity: FloatProperty(name="FarIntensity", default=0.75, min=0.0, max=1.0,
                                     update=_on_post)
    dof_near_intensity: FloatProperty(name="NearIntensity", default=0.75, min=0.0, max=1.0,
                                      update=_on_post)

    sunrays_enabled: BoolProperty(name="Sun Rays", default=False, update=_on_post,
                                  description="SunRaysEffect: rays from the sun")
    sunrays_intensity: FloatProperty(name="Intensity", default=0.25, min=0.0, max=1.0,
                                     update=_on_post)
    sunrays_spread: FloatProperty(name="Spread", default=1.0, min=0.0, max=1.0, update=_on_post)

    viewport_preview: BoolProperty(
        name="Show in Viewport", default=False, update=_on_preview,
        description="Show the effects in Material Preview / Rendered viewport shading "
                    "(the compositor runs in the viewport)")


def any_post_effect(fx):
    return fx.bloom_enabled or fx.blur_enabled or fx.cc_enabled or fx.sunrays_enabled


def _compositor_tree(scene, create):
    """(node tree, new_api). Blender 5 uses a node group per scene, 4.x the
    scene's own tree. Returns (None, _) when the user has their own tree."""
    if hasattr(scene, "compositing_node_group"):
        ng = scene.compositing_node_group
        if ng is not None and not ng.get("rblx_effects"):
            return None, True
        if ng is None:
            if not create:
                return None, True
            ng = bpy.data.node_groups.get(COMP_NAME)
            if ng is None:
                ng = bpy.data.node_groups.new(COMP_NAME, "CompositorNodeTree")
                ng["rblx_effects"] = True
            scene.compositing_node_group = ng
        return ng, True
    if not create and not scene.use_nodes:
        return None, False
    if scene.use_nodes and scene.node_tree is not None and len(scene.node_tree.nodes) > 2 \
            and not scene.node_tree.get("rblx_effects"):
        return None, False
    scene.use_nodes = True
    scene.node_tree["rblx_effects"] = True
    return scene.node_tree, False


def _glare(nt, kind, threshold, strength, size, loc):
    g = nt.nodes.new("CompositorNodeGlare")
    g.location = loc
    if "Type" in g.inputs:  # Blender 4.4+: settings are sockets
        _set(g, "Type", kind)
        _set(g, "Quality", "High")
        _set(g, "Threshold", threshold)
        _set(g, "Strength", strength)
        _set(g, "Size", size)
    else:
        g.glare_type = {"Bloom": "BLOOM", "Sun Beams": "SUN_BEAMS"}.get(kind, "FOG_GLOW")
        g.quality = "HIGH"
        g.threshold = threshold
        g.mix = max(-1.0, min(1.0, strength - 1.0))
        g.size = max(6, min(9, int(6 + size * 3)))
    return g


def sun_screen_position(scene):
    """Where the sun is on the camera's image (0..1), or None if behind it."""
    from . import lighting
    cam = scene.camera
    if cam is None:
        return None
    props = scene.rblx_lighting
    to_sun = lighting.sun_direction_bl(props.clock_time, props.geographic_latitude)
    p = world_to_camera_view(scene, cam, cam.matrix_world.translation + to_sun * 1.0e4)
    if p.z <= 0:
        return None
    return p.x, p.y


def apply_post_effects(scene):
    fx = scene.rblx_effects
    _apply_dof(scene, fx)
    if not any_post_effect(fx):
        nt, new_api = _compositor_tree(scene, create=False)
        if nt is not None:
            if new_api:
                scene.compositing_node_group = None
            else:
                scene.use_nodes = False
        return True
    nt, new_api = _compositor_tree(scene, create=True)
    if nt is None:
        return False  # the user has their own compositor setup: leave it alone
    nt.nodes.clear()
    rl = nt.nodes.new("CompositorNodeRLayers")
    rl.location = (-800, 0)
    img = rl.outputs["Image"]
    x = -500
    if fx.bloom_enabled:
        g = _glare(nt, "Bloom", fx.bloom_threshold * 0.5, fx.bloom_intensity,
                   0.3 + 0.7 * fx.bloom_size / 56.0, (x, 0))
        g.name = "RBX Bloom"
        _link(nt, img, g.inputs["Image"])
        img = g.outputs["Image"]
        x += 250
    if fx.sunrays_enabled:
        pos = sun_screen_position(scene)
        g = _glare(nt, "Sun Beams", 0.6, fx.sunrays_intensity * 2.0 if pos else 0.0,
                   0.1 + 0.4 * fx.sunrays_spread, (x, 0))
        g.name = "RBX Sun Rays"
        if pos and "Sun Position" in g.inputs:
            _set(g, "Sun Position", pos)
        _link(nt, img, g.inputs["Image"])
        img = g.outputs["Image"]
        x += 250
    if fx.cc_enabled:
        bc = nt.nodes.new("CompositorNodeBrightContrast")
        bc.location = (x, 0)
        _set(bc, "Brightness", fx.cc_brightness * 100.0)
        _set(bc, "Contrast", fx.cc_contrast * 100.0)
        _link(nt, img, bc.inputs["Image"])
        hs = nt.nodes.new("CompositorNodeHueSat")
        hs.location = (x + 200, 0)
        _set(hs, "Saturation", 1.0 + fx.cc_saturation)
        _link(nt, bc.outputs["Image"], hs.inputs["Image"])
        tint = nt.nodes.new("ShaderNodeMix")
        tint.data_type = "RGBA"
        tint.blend_type = "MULTIPLY"
        tint.location = (x + 400, 0)
        _socket(tint.inputs, "Factor").default_value = 1.0
        _socket(tint.inputs, "B", 2).default_value = (*fx.cc_tint, 1.0)
        _link(nt, hs.outputs["Image"], _socket(tint.inputs, "A", 2))
        img = _socket(tint.outputs, "Result", 2)
        x += 650
    if fx.blur_enabled:
        b = nt.nodes.new("CompositorNodeBlur")
        b.location = (x, 0)
        px = fx.blur_size * scene.render.resolution_y * scene.render.resolution_percentage / 100.0 / 1080.0
        size = _socket(b.inputs, "Size") if "Size" in b.inputs else None
        if size is not None:
            size.default_value = (px, px)
        else:
            b.size_x = b.size_y = int(px)
        _link(nt, img, b.inputs["Image"])
        img = b.outputs["Image"]
        x += 250
    if new_api:
        if not any(i.in_out == "OUTPUT" and i.name == "Image" for i in nt.interface.items_tree):
            nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        out = nt.nodes.new("NodeGroupOutput")
        out.location = (x + 100, 0)
        _link(nt, img, out.inputs["Image"])
    else:
        out = nt.nodes.new("CompositorNodeComposite")
        out.location = (x + 100, 0)
        _link(nt, img, out.inputs["Image"])
    viewer = nt.nodes.new("CompositorNodeViewer")
    viewer.location = (x + 100, -200)
    _link(nt, img, viewer.inputs["Image"])
    return True


def _apply_dof(scene, fx):
    cam = scene.camera
    if cam is None or cam.type != "CAMERA":
        return
    dof = cam.data.dof
    if not fx.dof_enabled:
        if cam.data.get("rblx_dof"):
            dof.use_dof = False
            del cam.data["rblx_dof"]
        return
    scale = coords.stud_scale(scene)
    radius = max(fx.dof_in_focus_radius, 0.5)
    center = (fx.dof_focus_distance + radius * 0.5) * scale
    dof.use_dof = True
    dof.focus_object = None
    dof.focus_distance = max(center, 0.01)
    # f-stop so roughly `radius` studs around the focus stay sharp
    f_mm = cam.data.lens
    s_mm = center * 1000.0
    width_mm = radius * scale * 1000.0
    coc = 0.03 / max(0.05, (fx.dof_far_intensity + fx.dof_near_intensity) * 0.5)
    fstop = width_mm * f_mm * f_mm / max(2.0 * coc * s_mm * s_mm, 1e-6)
    dof.aperture_fstop = max(0.1, min(64.0, fstop))
    cam.data["rblx_dof"] = True


def values_from_instances(instances):
    """Post-effect settings from Roblox effect instances (Lighting / Camera
    children). Disabled effects are skipped."""
    v = {}
    for inst in instances:
        p = inst.props
        if p.get("Enabled") is False:
            continue
        cls = inst.class_name

        def num(name, key, default=None):
            val = p.get(name, default)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                v[key] = float(val)

        if cls == "BloomEffect":
            v["bloom_enabled"] = True
            num("Intensity", "bloom_intensity")
            num("Size", "bloom_size")
            num("Threshold", "bloom_threshold")
        elif cls == "BlurEffect":
            v["blur_enabled"] = True
            num("Size", "blur_size")
        elif cls == "ColorCorrectionEffect":
            v["cc_enabled"] = True
            num("Brightness", "cc_brightness")
            num("Contrast", "cc_contrast")
            num("Saturation", "cc_saturation")
            if isinstance(p.get("TintColor"), tuple):
                v["cc_tint"] = to_linear(p["TintColor"])
        elif cls == "DepthOfFieldEffect":
            v["dof_enabled"] = True
            num("FocusDistance", "dof_focus_distance")
            num("InFocusRadius", "dof_in_focus_radius")
            num("FarIntensity", "dof_far_intensity")
            num("NearIntensity", "dof_near_intensity")
        elif cls == "SunRaysEffect":
            v["sunrays_enabled"] = True
            num("Intensity", "sunrays_intensity")
            num("Spread", "sunrays_spread")
    return v


def set_post_values(scene, values):
    fx = scene.rblx_effects
    RBLX_PostEffectsProps._applying = True
    try:
        for k, val in values.items():
            if hasattr(fx, k):
                setattr(fx, k, val)
    finally:
        RBLX_PostEffectsProps._applying = False
    apply_post_effects(scene)


@bpy.app.handlers.persistent
def _frame_handler(scene, *_args):
    """Keep sun rays aimed at the sun while the camera moves."""
    try:
        fx = scene.rblx_effects
    except AttributeError:
        return
    if not fx.sunrays_enabled:
        return
    nt, _new = _compositor_tree(scene, create=False)
    node = nt.nodes.get("RBX Sun Rays") if nt is not None else None
    if node is None or "Sun Position" not in node.inputs:
        return
    pos = sun_screen_position(scene)
    if pos:
        _set(node, "Sun Position", pos)
    _set(node, "Strength", fx.sunrays_intensity * 2.0 if pos else 0.0)


# ---------------------------------------------------------------------------
# Particles (ParticleEmitter / Fire / Smoke / Sparkles)

PARTICLE_DEFAULTS = dict(
    rate=20.0, lifetime=(5.0, 10.0), speed=(5.0, 5.0), spread=(0.0, 0.0),
    acceleration=(0.0, 0.0, 0.0), drag=0.0, rotation=(0.0, 0.0), rot_speed=(0.0, 0.0),
    size=[(0.0, 1.0, 0.0), (1.0, 1.0, 0.0)], transparency=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
    color=[(0.0, 1.0, 1.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0, 0.0)], light_emission=0.0,
    texture=DEFAULT_PARTICLE_TEXTURE, direction="TOP", emit_size=(1.0, 1.0, 1.0),
    enabled=True, kind="ParticleEmitter", shape=0, surface=False, in_out=0,
    burst_count=0, burst_frame=-1000000, flipbook=(1, 0, 30.0, False))

FLIPBOOK_GRID = {0: 1, 1: 2, 2: 4, 3: 8}   # Enum.ParticleFlipbookLayout -> cells per side


def _rgb(c):
    return tuple(v / 255.0 for v in c)


def fire_params(color=_rgb((236, 139, 70)), secondary=_rgb((139, 80, 55)), heat=9.0, size=5.0):
    """Roblox's legacy Fire as an emitter."""
    return dict(PARTICLE_DEFAULTS, kind="Fire", rate=65.0, lifetime=(0.7, 1.2),
                speed=(heat * 0.25, heat * 0.4), spread=(15.0, 15.0),
                acceleration=(0.0, heat * 0.5, 0.0), rotation=(-180.0, 180.0),
                rot_speed=(-90.0, 90.0),
                size=[(0.0, size * 0.55, 0.0), (0.5, size * 0.45, 0.0), (1.0, size * 0.1, 0.0)],
                transparency=[(0.0, 0.6, 0.0), (0.15, 0.1, 0.0), (1.0, 1.0, 0.0)],
                color=[(0.0, *color, 0.0), (1.0, *secondary, 0.0)], light_emission=1.0,
                texture=TEXTURE_DIR + "fire_main.dds", emit_size=(size * 0.3,) * 3)


def smoke_params(color=_rgb((128, 128, 128)), opacity=0.5, rise=1.0, size=1.0):
    return dict(PARTICLE_DEFAULTS, kind="Smoke", rate=12.0, lifetime=(4.0, 6.0),
                speed=(rise, rise * 1.5), spread=(20.0, 20.0), rotation=(-180.0, 180.0),
                rot_speed=(-20.0, 20.0),
                size=[(0.0, size, 0.0), (1.0, size * 3.0, 0.0)],
                transparency=[(0.0, 1.0, 0.0), (0.1, 1.0 - opacity, 0.0), (1.0, 1.0, 0.0)],
                color=[(0.0, *color, 0.0), (1.0, *color, 0.0)],
                texture=TEXTURE_DIR + "smoke_main.dds", emit_size=(size,) * 3)


def sparkles_params(color=_rgb((144, 25, 255))):
    return dict(PARTICLE_DEFAULTS, kind="Sparkles", rate=25.0, lifetime=(0.8, 1.4),
                speed=(3.0, 6.0), spread=(180.0, 180.0), rotation=(-180.0, 180.0),
                size=[(0.0, 0.5, 0.0), (1.0, 0.1, 0.0)],
                transparency=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
                color=[(0.0, *color, 0.0), (1.0, *color, 0.0)], light_emission=1.0,
                texture=TEXTURE_DIR + "sparkles_main.dds", emit_size=(1.0, 1.0, 1.0))


def params_from_instance(inst):
    """Emitter parameters from a ParticleEmitter / Fire / Smoke / Sparkles."""
    p = inst.props
    cls = inst.class_name
    from .rbx import enums

    def col(name, default):
        c = p.get(name)
        return tuple(c) if isinstance(c, tuple) and len(c) == 3 else default

    def num(name, default):
        v = p.get(name)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    if cls == "Fire":
        params = fire_params(col("Color", _rgb((236, 139, 70))), col("SecondaryColor", _rgb((139, 80, 55))),
                             num("Heat", 9.0), num("Size", 5.0))
    elif cls == "Smoke":
        params = smoke_params(col("Color", _rgb((128, 128, 128))), num("Opacity", 0.5),
                              num("RiseVelocity", 1.0), num("Size", 1.0))
    elif cls == "Sparkles":
        params = sparkles_params(col("SparkleColor", _rgb((144, 25, 255))))
    else:
        d = PARTICLE_DEFAULTS
        spread = p.get("SpreadAngle")
        accel = p.get("Acceleration")
        params = dict(
            d, rate=num("Rate", d["rate"]),
            lifetime=number_range(p.get("Lifetime"), d["lifetime"]),
            speed=number_range(p.get("Speed"), d["speed"]),
            spread=tuple(spread[:2]) if isinstance(spread, tuple) and len(spread) >= 2 else d["spread"],
            acceleration=tuple(accel) if isinstance(accel, tuple) and len(accel) == 3 else d["acceleration"],
            drag=num("Drag", 0.0),
            rotation=number_range(p.get("Rotation"), d["rotation"]),
            rot_speed=number_range(p.get("RotSpeed"), d["rot_speed"]),
            size=number_sequence(p.get("Size"), d["size"]),
            transparency=number_sequence(p.get("Transparency"), d["transparency"]),
            color=color_sequence(p.get("Color"), d["color"]),
            light_emission=num("LightEmission", 0.0),
            direction=enums.NORMAL_IDS.get(p.get("EmissionDirection", 1), "TOP"),
            texture=p.get("Texture") if isinstance(p.get("Texture"), str) and p.get("Texture")
            else DEFAULT_PARTICLE_TEXTURE)

        def enum(name, default=0):
            v = p.get(name)
            return int(v) if isinstance(v, int) and not isinstance(v, bool) else default

        params["shape"] = enum("Shape")
        params["surface"] = enum("ShapeStyle") == 1
        params["in_out"] = enum("ShapeInOut")
        fr = number_range(p.get("FlipbookFramerate"), (1.0, 1.0))
        params["flipbook"] = (FLIPBOOK_GRID.get(enum("FlipbookLayout"), 1), enum("FlipbookMode"),
                              (fr[0] + fr[1]) / 2.0, bool(p.get("FlipbookStartRandom", False)))
    params["enabled"] = p.get("Enabled", True) is not False
    return params


def _direction_euler(face):
    """Euler that turns +Z (the part's Top in Blender) to face `face`."""
    n = coords.vec_to_bl(coords.FACE_NORMALS.get(face, (0.0, 1.0, 0.0)))
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(n)
    return tuple(q.to_euler())


def _particle_group(name, params, material):
    """Geometry Nodes particle simulation for one emitter."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng["rblx_particles"] = True
    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    specs = [
        ("Enabled", "NodeSocketBool"), ("Rate", "NodeSocketFloat"),
        ("Lifetime Min", "NodeSocketFloat"), ("Lifetime Max", "NodeSocketFloat"),
        ("Speed Min", "NodeSocketFloat"), ("Speed Max", "NodeSocketFloat"),
        ("Spread X", "NodeSocketFloat"), ("Spread Y", "NodeSocketFloat"),
        ("Acceleration", "NodeSocketVector"), ("Drag", "NodeSocketFloat"),
        ("Rotation Min", "NodeSocketFloat"), ("Rotation Max", "NodeSocketFloat"),
        ("RotSpeed Min", "NodeSocketFloat"), ("RotSpeed Max", "NodeSocketFloat"),
        ("Size", "NodeSocketFloat"), ("Emitter Size", "NodeSocketVector"),
        ("Direction", "NodeSocketVector"), ("Camera", "NodeSocketObject"),
        ("Seed", "NodeSocketInt"),
        ("Shape", "NodeSocketInt"), ("Surface", "NodeSocketBool"), ("In Out", "NodeSocketInt"),
        ("Burst Count", "NodeSocketInt"), ("Burst Frame", "NodeSocketInt"),
    ]
    for sname, stype in specs:
        iface.new_socket(sname, in_out="INPUT", socket_type=stype)
    N = ng.nodes
    gi = N.new("NodeGroupInput")
    gi.location = (-2400, 0)
    go = N.new("NodeGroupOutput")
    go.location = (1800, 0)
    I = gi.outputs

    # World transform of the emitter
    selfo = N.new("GeometryNodeSelfObject")
    selfo.location = (-2200, -600)
    info = N.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    info.location = (-2000, -600)
    _link(ng, selfo.outputs[0], info.inputs["Object"])
    xform = info.outputs["Transform"]

    time = N.new("GeometryNodeInputSceneTime")
    time.location = (-2200, -900)
    frame_seed = _math(ng, "ADD", time.outputs["Frame"], I["Seed"], loc=(-2000, -900))

    si = N.new("GeometryNodeSimulationInput")
    so = N.new("GeometryNodeSimulationOutput")
    si.location, so.location = (-1600, 300), (900, 300)
    si.pair_with_output(so)
    so.state_items.new("FLOAT", "Carry")
    dt = si.outputs["Delta Time"]

    # --- update existing particles -------------------------------------------
    def attr(name, dtype="FLOAT", loc=(0, 0)):
        n = N.new("GeometryNodeInputNamedAttribute")
        n.data_type = dtype
        n.inputs["Name"].default_value = name
        n.location = loc
        return _socket(n.outputs, "Attribute")

    def store(geo, name, value, dtype="FLOAT", loc=(0, 0), domain="POINT"):
        n = N.new("GeometryNodeStoreNamedAttribute")
        n.data_type = dtype
        n.domain = domain
        n.location = loc
        n.inputs["Name"].default_value = name
        _link(ng, geo, n.inputs["Geometry"])
        _link(ng, value, _socket(n.inputs, "Value"))
        return n.outputs["Geometry"]

    geo = si.outputs["Geometry"]
    age = _math(ng, "ADD", attr("age", loc=(-1400, 600)), dt, loc=(-1200, 600))
    geo = store(geo, "age", age, loc=(-1000, 400))
    vel = attr("vel", "FLOAT_VECTOR", loc=(-1400, 800))
    accel_dt = _vmath(ng, "SCALE", I["Acceleration"], loc=(-1200, 900), scale=dt)
    vel = _vmath(ng, "ADD", vel, accel_dt, loc=(-1000, 850))
    damp = _math(ng, "DIVIDE", 1.0, _math(ng, "ADD", 1.0, _math(ng, "MULTIPLY", I["Drag"], dt,
                                                              loc=(-1200, 1000)), loc=(-1100, 1000)),
                 loc=(-1000, 1000))
    vel = _vmath(ng, "SCALE", vel, loc=(-850, 900), scale=damp)
    geo = store(geo, "vel", vel, "FLOAT_VECTOR", loc=(-800, 400))
    rot = _math(ng, "ADD", attr("rot", loc=(-1000, 1200)),
                _math(ng, "MULTIPLY", attr("rotspeed", loc=(-1000, 1300)), dt, loc=(-850, 1300)),
                loc=(-700, 1200))
    geo = store(geo, "rot", rot, loc=(-600, 400))
    setpos = N.new("GeometryNodeSetPosition")
    setpos.location = (-400, 400)
    _link(ng, geo, setpos.inputs["Geometry"])
    _link(ng, _vmath(ng, "SCALE", vel, loc=(-600, 700), scale=dt), setpos.inputs["Offset"])
    dead = N.new("FunctionNodeCompare")
    dead.data_type = "FLOAT"
    dead.operation = "GREATER_THAN"
    dead.location = (-400, 650)
    _link(ng, attr("age", loc=(-600, 600)), _socket(dead.inputs, "A"))
    _link(ng, attr("life", loc=(-600, 550)), _socket(dead.inputs, "B"))
    delete = N.new("GeometryNodeDeleteGeometry")
    delete.location = (-200, 400)
    _link(ng, setpos.outputs["Geometry"], delete.inputs["Geometry"])
    _link(ng, dead.outputs["Result"], delete.inputs["Selection"])
    alive = delete.outputs["Geometry"]

    # --- emit new particles ------------------------------------------------------
    rate = N.new("GeometryNodeSwitch")
    rate.input_type = "FLOAT"
    rate.location = (-1400, -200)
    _link(ng, I["Enabled"], rate.inputs["Switch"])
    _socket(rate.inputs, "False").default_value = 0.0
    _link(ng, I["Rate"], _socket(rate.inputs, "True"))
    total = _math(ng, "ADD", si.outputs["Carry"],
                  _math(ng, "MULTIPLY", rate.outputs[0], dt, loc=(-1200, -250)), loc=(-1050, -200))
    count = _math(ng, "FLOOR", total, loc=(-900, -200))
    _link(ng, _math(ng, "SUBTRACT", total, count, loc=(-750, -100)), so.inputs["Carry"])

    def rand(dtype, lo, hi, seed_off, loc):
        n = N.new("FunctionNodeRandomValue")
        n.data_type = dtype
        n.location = loc
        for sock_name, v in (("Min", lo), ("Max", hi)):
            s = _socket(n.inputs, sock_name)
            if isinstance(v, (int, float, tuple)):
                s.default_value = v
            else:
                _link(ng, v, s)
        _link(ng, _math(ng, "ADD", frame_seed, float(seed_off), loc=(loc[0] - 150, loc[1] - 80)),
              n.inputs["Seed"])
        return _socket(n.outputs, "Value")

    def switch(dtype, index, values, loc):
        """Index Switch: values[index] (a socket or a constant per item)."""
        n = N.new("GeometryNodeIndexSwitch")
        n.data_type = dtype
        n.location = loc
        while len(n.index_switch_items) < len(values):
            n.index_switch_items.new()
        _link(ng, index, n.inputs["Index"])
        for i, v in enumerate(values):
            s = n.inputs[i + 1]
            if isinstance(v, (int, float, tuple)):
                s.default_value = v
            else:
                _link(ng, v, s)
        return n.outputs[0]

    def combine(x=None, y=None, z=None, loc=(0, 0)):
        n = N.new("ShaderNodeCombineXYZ")
        n.location = loc
        for name, v in (("X", x), ("Y", y), ("Z", z)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[name].default_value = v
            else:
                _link(ng, v, n.inputs[name])
        return n.outputs[0]

    def separate(v, loc):
        n = N.new("ShaderNodeSeparateXYZ")
        n.location = loc
        _link(ng, v, n.inputs[0])
        return n.outputs["X"], n.outputs["Y"], n.outputs["Z"]

    # Bursts (Explosion / ParticleEmitter:Emit): extra particles on one frame
    on_burst = _math(ng, "COMPARE", time.outputs["Frame"], I["Burst Frame"], loc=(-1050, -350))
    _socket(on_burst.node.inputs, "Value", 2).default_value = 0.5
    burst = _math(ng, "MULTIPLY", on_burst, I["Burst Count"], loc=(-900, -350))
    emit_count = _math(ng, "ADD", count, burst, loc=(-750, -300))

    # Emitter shape (Roblox Shape: Box, Sphere, Cylinder, Disc; ShapeStyle Volume/Surface)
    half = _vmath(ng, "SCALE", I["Emitter Size"], loc=(-1100, -450), scale=0.5)
    neg_half = _vmath(ng, "SCALE", I["Emitter Size"], loc=(-1100, -550), scale=-0.5)
    box_pos = rand("FLOAT_VECTOR", neg_half, half, 1, (-900, -500))
    hx, hy, hz = separate(half, (-1100, -650))
    rnd_dir = _vmath(ng, "NORMALIZE", rand("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), 10,
                                            (-1100, -750)), loc=(-950, -750))
    surface_r = rand("FLOAT", 0.0, 1.0, 11, (-1100, -850))
    sphere_r = N.new("GeometryNodeSwitch")
    sphere_r.input_type = "FLOAT"
    _link(ng, I["Surface"], sphere_r.inputs["Switch"])
    _link(ng, _math(ng, "POWER", surface_r, 1.0 / 3.0, loc=(-950, -850)), _socket(sphere_r.inputs, "False"))
    _socket(sphere_r.inputs, "True").default_value = 1.0
    sphere_pos = _vmath(ng, "MULTIPLY", _vmath(ng, "SCALE", rnd_dir, scale=sphere_r.outputs[0],
                                               loc=(-800, -800)), half, loc=(-650, -800))
    ang = _math(ng, "MULTIPLY", rand("FLOAT", 0.0, 1.0, 12, (-1100, -950)), 2.0 * math.pi, loc=(-950, -950))
    ring_r = N.new("GeometryNodeSwitch")
    ring_r.input_type = "FLOAT"
    _link(ng, I["Surface"], ring_r.inputs["Switch"])
    _link(ng, _math(ng, "SQRT", surface_r, loc=(-950, -1050)), _socket(ring_r.inputs, "False"))
    _socket(ring_r.inputs, "True").default_value = 1.0
    cx = _math(ng, "MULTIPLY", _math(ng, "MULTIPLY", _math(ng, "COSINE", ang, loc=(-850, -950)),
                                     ring_r.outputs[0], loc=(-750, -950)), hx, loc=(-650, -950))
    cy = _math(ng, "MULTIPLY", _math(ng, "MULTIPLY", _math(ng, "SINE", ang, loc=(-850, -1050)),
                                     ring_r.outputs[0], loc=(-750, -1050)), hy, loc=(-650, -1050))
    cz = _math(ng, "MULTIPLY", rand("FLOAT", -1.0, 1.0, 13, (-850, -1150)), hz, loc=(-650, -1150))
    cyl_pos = combine(cx, cy, cz, loc=(-500, -1000))
    disc_pos = combine(cx, cy, 0.0, loc=(-500, -1100))
    local_pos = switch("VECTOR", I["Shape"], [box_pos, sphere_pos, cyl_pos, disc_pos], (-350, -600))

    pts = N.new("GeometryNodePoints")
    pts.location = (-600, -300)
    _link(ng, emit_count, pts.inputs["Count"])
    tp = N.new("FunctionNodeTransformPoint")
    tp.location = (-700, -500)
    _link(ng, local_pos, tp.inputs["Vector"])
    _link(ng, xform, tp.inputs["Transform"])
    _link(ng, tp.outputs["Vector"], pts.inputs["Position"])
    new = pts.outputs["Points"]

    # direction: spread around the emission direction
    to_rad = math.pi / 180.0
    sx = _math(ng, "MULTIPLY", I["Spread X"], to_rad, loc=(-1100, -800))
    sy = _math(ng, "MULTIPLY", I["Spread Y"], to_rad, loc=(-1100, -900))
    ax = rand("FLOAT", _math(ng, "MULTIPLY", sx, -1.0, loc=(-1000, -750)), sx, 2, (-900, -750))
    ay = rand("FLOAT", _math(ng, "MULTIPLY", sy, -1.0, loc=(-1000, -950)), sy, 3, (-900, -950))
    euler = N.new("ShaderNodeCombineXYZ")
    euler.location = (-700, -850)
    _link(ng, ax, euler.inputs["X"])
    _link(ng, ay, euler.inputs["Y"])
    spread_rot = N.new("FunctionNodeEulerToRotation")
    spread_rot.location = (-550, -850)
    _link(ng, euler.outputs[0], spread_rot.inputs["Euler"])
    rv = N.new("FunctionNodeRotateVector")
    rv.location = (-400, -850)
    rv.inputs["Vector"].default_value = (0.0, 0.0, 1.0)
    _link(ng, spread_rot.outputs[0], rv.inputs["Rotation"])
    face_rot = N.new("FunctionNodeEulerToRotation")
    face_rot.location = (-400, -1000)
    _link(ng, I["Direction"], face_rot.inputs["Euler"])
    face_dir = N.new("FunctionNodeRotateVector")
    face_dir.location = (-250, -1100)
    face_dir.inputs["Vector"].default_value = (0.0, 0.0, 1.0)
    _link(ng, face_rot.outputs[0], face_dir.inputs["Rotation"])
    # Box and Disc emit along EmissionDirection; Sphere and Cylinder outward from the centre
    px, py, _pz = separate(local_pos, (-300, -1250))
    radial = _vmath(ng, "NORMALIZE", combine(px, py, 0.0, loc=(-150, -1250)), loc=(0, -1250))
    outward = switch("VECTOR", I["Shape"], [face_dir.outputs[0], _vmath(ng, "NORMALIZE", local_pos,
                                                                        loc=(-150, -1150)),
                                            radial, face_dir.outputs[0]], (100, -1150))
    # ShapeInOut: Outward, Inward, or both
    sign = switch("FLOAT", I["In Out"], [1.0, -1.0, _math(ng, "SIGN", rand("FLOAT", -1.0, 1.0, 14,
                                                                           (0, -1400)),
                                                          loc=(150, -1400))], (300, -1350))
    outward = _vmath(ng, "SCALE", outward, loc=(450, -1200), scale=sign)
    align = N.new("FunctionNodeAlignRotationToVector")
    align.axis = "Z"
    align.location = (-100, -1000)
    _link(ng, outward, align.inputs["Vector"])
    rv2 = N.new("FunctionNodeRotateVector")
    rv2.location = (-250, -900)
    _link(ng, rv.outputs[0], rv2.inputs["Vector"])
    _link(ng, align.outputs[0], rv2.inputs["Rotation"])
    td = N.new("FunctionNodeTransformDirection")
    td.location = (-100, -900)
    _link(ng, rv2.outputs[0], td.inputs["Direction"])
    _link(ng, xform, td.inputs["Transform"])
    wdir = _vmath(ng, "NORMALIZE", td.outputs[0], loc=(50, -900))
    speed = rand("FLOAT", I["Speed Min"], I["Speed Max"], 4, (-100, -1100))
    new = store(new, "vel", _vmath(ng, "SCALE", wdir, loc=(200, -950), scale=speed),
                "FLOAT_VECTOR", loc=(300, -300))
    new = store(new, "life", rand("FLOAT", I["Lifetime Min"], I["Lifetime Max"], 5, (100, -1200)),
                loc=(450, -300))
    new = store(new, "rot", _math(ng, "MULTIPLY", rand("FLOAT", I["Rotation Min"], I["Rotation Max"],
                                                        6, (100, -1350)), to_rad, loc=(300, -1350)),
                loc=(600, -300))
    new = store(new, "rotspeed", _math(ng, "MULTIPLY", rand("FLOAT", I["RotSpeed Min"],
                                                              I["RotSpeed Max"], 7, (100, -1500)),
                                       to_rad, loc=(300, -1500)), loc=(750, -300))
    new = store(new, "age", _math(ng, "MULTIPLY", 0.0, 0.0, loc=(600, -500)), loc=(850, -300))
    new = store(new, "rbx_rand", rand("FLOAT", 0.0, 1.0, 9, (600, -650)), loc=(950, -300))

    join = N.new("GeometryNodeJoinGeometry")
    join.location = (750, 300)
    _link(ng, new, join.inputs["Geometry"])
    _link(ng, alive, join.inputs["Geometry"])
    _link(ng, join.outputs["Geometry"], so.inputs["Geometry"])
    particles = so.outputs["Geometry"]

    # --- draw: camera-facing sprites ----------------------------------------------
    t = _math(ng, "DIVIDE", attr("age", loc=(900, -100)), attr("life", loc=(900, -200)), loc=(1050, -150))
    t = _math(ng, "MINIMUM", t, 1.0, loc=(1150, -150))
    particles = store(particles, "rbx_t", t, loc=(1100, 300))
    size_curve = N.new("ShaderNodeFloatCurve")
    size_curve.name = "RBX Size"
    size_curve.label = "Size over lifetime"
    size_curve.location = (1100, -300)
    _link(ng, t, size_curve.inputs["Value"])
    size = _math(ng, "MULTIPLY", size_curve.outputs[0], I["Size"], loc=(1300, -300))

    cam = N.new("GeometryNodeObjectInfo")
    cam.transform_space = "ORIGINAL"
    cam.location = (900, -500)
    _link(ng, I["Camera"], cam.inputs["Object"])
    posn = N.new("GeometryNodeInputPosition")
    posn.location = (900, -650)
    to_cam = _vmath(ng, "SUBTRACT", cam.outputs["Location"], posn.outputs[0], loc=(1100, -550))
    align = N.new("FunctionNodeAlignRotationToVector")
    align.axis = "Z"
    align.location = (1300, -550)
    _link(ng, to_cam, align.inputs["Vector"])

    grid = N.new("GeometryNodeMeshGrid")
    grid.location = (900, -800)
    _set(grid, "Size X", 1.0)
    _set(grid, "Size Y", 1.0)
    _set(grid, "Vertices X", 2)
    _set(grid, "Vertices Y", 2)
    quad = store(grid.outputs["Mesh"], "UVMap", grid.outputs["UV Map"], "FLOAT2",
                 loc=(1100, -800), domain="CORNER")
    setmat = N.new("GeometryNodeSetMaterial")
    setmat.location = (1300, -800)
    setmat.inputs["Material"].default_value = material
    _link(ng, quad, setmat.inputs["Geometry"])

    iop = N.new("GeometryNodeInstanceOnPoints")
    iop.location = (1500, 300)
    _link(ng, particles, iop.inputs["Points"])
    _link(ng, setmat.outputs["Geometry"], iop.inputs["Instance"])
    _link(ng, align.outputs[0], iop.inputs["Rotation"])
    _link(ng, size, iop.inputs["Scale"])
    roll_euler = N.new("ShaderNodeCombineXYZ")
    roll_euler.location = (1500, 0)
    _link(ng, attr("rot", loc=(1300, 0)), roll_euler.inputs["Z"])
    roll = N.new("GeometryNodeRotateInstances")
    roll.location = (1650, 300)
    _link(ng, iop.outputs["Instances"], roll.inputs["Instances"])
    _link(ng, roll_euler.outputs[0], roll.inputs["Rotation"])

    # back to the emitter's local space
    inv = N.new("FunctionNodeInvertMatrix")
    inv.location = (1500, -100)
    _link(ng, xform, inv.inputs["Matrix"])
    tr = N.new("GeometryNodeTransform")
    tr.location = (1700, 100)
    _set(tr, "Mode", "Matrix")
    _link(ng, roll.outputs["Instances"], tr.inputs["Geometry"])
    _link(ng, inv.outputs["Matrix"], tr.inputs["Transform"])
    out_join = N.new("GeometryNodeJoinGeometry")
    out_join.location = (1750, -100)
    _link(ng, tr.outputs["Geometry"], out_join.inputs["Geometry"])
    _link(ng, gi.outputs["Geometry"], out_join.inputs["Geometry"])
    go.location = (1950, 0)
    _link(ng, out_join.outputs["Geometry"], go.inputs["Geometry"])
    _sequence_curve(size_curve, params["size"], max(max(k[1] for k in params["size"]), 1e-6))
    return ng


def _flipbook_uv(nt, uv, flipbook):
    """UV inside one cell of a flipbook texture (Roblox FlipbookLayout grid).
    flipbook = (cells per side, mode 0 Loop / 1 OneShot / 2 PingPong / 3 Random,
    frames per second, start at a random frame)."""
    n, mode, fps, start_random = flipbook
    frames = n * n

    def attr(name):
        a = nt.nodes.new("ShaderNodeAttribute")
        a.attribute_type = "INSTANCER"
        a.attribute_name = name
        return a.outputs["Fac"]

    age, life_t, rnd = attr("age"), attr("rbx_t"), attr("rbx_rand")
    if mode == 1:  # OneShot: the whole sheet once over the particle's life
        f = _math(nt, "MINIMUM", _math(nt, "FLOOR", _math(nt, "MULTIPLY", life_t, float(frames))),
                  float(frames - 1))
    elif mode == 3:  # Random: one frame per particle
        f = _math(nt, "MINIMUM", _math(nt, "FLOOR", _math(nt, "MULTIPLY", rnd, float(frames))),
                  float(frames - 1))
    else:
        k = _math(nt, "FLOOR", _math(nt, "MULTIPLY", age, float(max(fps, 0.01))))
        if start_random:
            k = _math(nt, "ADD", k, _math(nt, "FLOOR", _math(nt, "MULTIPLY", rnd, float(frames))))
        if mode == 2 and frames > 1:  # PingPong
            period = float(2 * frames - 2)
            k = _math(nt, "FLOORED_MODULO", k, period)
            f = _math(nt, "SUBTRACT", float(frames - 1),
                      _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", k, float(frames - 1))))
        else:  # Loop
            f = _math(nt, "FLOORED_MODULO", k, float(frames))
    col = _math(nt, "FLOORED_MODULO", f, float(n))
    row = _math(nt, "FLOOR", _math(nt, "DIVIDE", f, float(n)))
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    _link(nt, uv, sep.inputs[0])
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    _link(nt, _math(nt, "DIVIDE", _math(nt, "ADD", sep.outputs["X"], col), float(n)), comb.inputs["X"])
    # rows count from the top of the image
    _link(nt, _math(nt, "DIVIDE", _math(nt, "ADD", sep.outputs["Y"],
                                        _math(nt, "SUBTRACT", float(n - 1), row)), float(n)),
          comb.inputs["Y"])
    return comb.outputs[0]


def sprite_material(name, image, colors, transparency, light_emission, instancer=True,
                    flipbook=None):
    """Unlit, camera-facing sprite material used by particles and beams. Color
    and Transparency follow the particle's life (or the beam's length)."""
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    mat.use_backface_culling = False
    nt = mat.node_tree
    nt.nodes.clear()
    N = nt.nodes
    out = N.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    t_attr = N.new("ShaderNodeAttribute")
    t_attr.attribute_type = "INSTANCER" if instancer else "GEOMETRY"
    t_attr.attribute_name = "rbx_t"
    t_attr.location = (-700, 200)
    ramp = N.new("ShaderNodeValToRGB")
    ramp.name = "RBX Color"
    ramp.label = "Color over lifetime"
    ramp.location = (-450, 300)
    _color_ramp(ramp, colors)
    _link(nt, t_attr.outputs["Fac"], ramp.inputs["Fac"])
    tcurve = N.new("ShaderNodeFloatCurve")
    tcurve.name = "RBX Transparency"
    tcurve.label = "Transparency over lifetime"
    tcurve.location = (-450, 0)
    _link(nt, t_attr.outputs["Fac"], tcurve.inputs["Value"])
    _sequence_curve(tcurve, transparency)
    uv = N.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    uv.location = (-700, -300)
    if image is not None:
        tex = N.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "CLIP" if instancer else "REPEAT"
        tex.location = (-450, -300)
        if flipbook and flipbook[0] > 1 and instancer:
            _link(nt, _flipbook_uv(nt, uv.outputs["UV"], flipbook), tex.inputs["Vector"])
        else:
            _link(nt, uv.outputs["UV"], tex.inputs["Vector"])
        tex_col, tex_alpha = tex.outputs["Color"], tex.outputs["Alpha"]
    else:  # soft round dot
        centered = _vmath(nt, "SUBTRACT", uv.outputs["UV"], (0.5, 0.5, 0.0), loc=(-500, -300))
        grad = N.new("ShaderNodeTexGradient")
        grad.gradient_type = "SPHERICAL"
        grad.location = (-350, -300)
        _link(nt, _vmath(nt, "SCALE", centered, loc=(-420, -300), scale=2.0), grad.inputs["Vector"])
        tex_col, tex_alpha = grad.outputs["Color"], grad.outputs["Fac"]
    col = N.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.blend_type = "MULTIPLY"
    col.location = (-150, 250)
    _socket(col.inputs, "Factor").default_value = 1.0
    _link(nt, tex_col, _socket(col.inputs, "A", 2))
    _link(nt, ramp.outputs["Color"], _socket(col.inputs, "B", 2))
    vis = _math(nt, "SUBTRACT", 1.0, tcurve.outputs[0], loc=(-200, 0))
    alpha = _math(nt, "MULTIPLY", tex_alpha, vis, loc=(0, -100))
    lp = N.new("ShaderNodeLightPath")
    lp.location = (0, -350)
    not_shadow = _math(nt, "SUBTRACT", 1.0, lp.outputs["Is Shadow Ray"], loc=(150, -300))
    alpha = _math(nt, "MULTIPLY", alpha, not_shadow, loc=(300, -150))
    em = N.new("ShaderNodeEmission")
    em.name = "RBX Emission"
    em.location = (300, 200)
    em.inputs["Strength"].default_value = 1.0 + 2.0 * light_emission
    _link(nt, _socket(col.outputs, "Result", 2), em.inputs["Color"])
    tr = N.new("ShaderNodeBsdfTransparent")
    tr.location = (300, 50)
    mix = N.new("ShaderNodeMixShader")
    mix.location = (600, 100)
    _link(nt, alpha, mix.inputs["Fac"])
    _link(nt, tr.outputs[0], mix.inputs[1])
    _link(nt, em.outputs[0], mix.inputs[2])
    _link(nt, mix.outputs[0], out.inputs["Surface"])
    mat["rblx_effect_material"] = True
    return mat


def _load_texture(content, resolver=None):
    from . import assets, materials
    if not content:
        return None
    resolver = resolver or assets.default_resolver("", True)
    try:
        path = resolver.resolve_image(content)
    except Exception:
        path = None
    return materials.load_image(path) if path else None


def _input_ids(mod):
    return {item.name: item.identifier for item in mod.node_group.interface.items_tree
            if item.item_type == "SOCKET" and item.in_out == "INPUT"}


def _input_holder(mod, ident):
    """(data, property) of a Geometry Nodes modifier input: Blender 5 keeps
    them in mod.properties.inputs.<id>.value, 4.x as ID properties mod[id]."""
    props = getattr(mod, "properties", None)
    holder = getattr(getattr(props, "inputs", None), ident, None) if props is not None else None
    if holder is not None:
        return holder, "value"
    return mod, '["%s"]' % ident


def get_input(mod, ident):
    holder, prop = _input_holder(mod, ident)
    return getattr(holder, prop) if prop == "value" else mod[ident]


def set_input(mod, ident, value):
    holder, prop = _input_holder(mod, ident)
    if prop == "value":
        holder.value = value
    else:
        mod[ident] = value


def draw_input(layout, mod, ident, text):
    holder, prop = _input_holder(mod, ident)
    layout.prop(holder, prop, text=text)


def set_emitter_inputs(obj, params, scene):
    mod = obj.modifiers.get("RBX Particles")
    if mod is None:
        return
    scale = coords.stud_scale(scene)
    ids = _input_ids(mod)
    accel = coords.vec_to_bl(params["acceleration"], scale)
    vals = {
        "Enabled": bool(params["enabled"]), "Rate": float(params["rate"]),
        "Lifetime Min": params["lifetime"][0], "Lifetime Max": params["lifetime"][1],
        "Speed Min": params["speed"][0] * scale, "Speed Max": params["speed"][1] * scale,
        "Spread X": float(params["spread"][0]), "Spread Y": float(params["spread"][1]),
        "Acceleration": tuple(accel), "Drag": float(params["drag"]),
        "Rotation Min": params["rotation"][0], "Rotation Max": params["rotation"][1],
        "RotSpeed Min": params["rot_speed"][0], "RotSpeed Max": params["rot_speed"][1],
        "Size": max(k[1] for k in params["size"]) * scale,
        "Emitter Size": tuple(coords.size_to_bl(params["emit_size"]) * scale),
        "Direction": _direction_euler(params["direction"]),
        "Camera": scene.camera, "Seed": abs(hash(obj.name)) % 10000,
        "Shape": int(params.get("shape", 0)), "Surface": bool(params.get("surface", False)),
        "In Out": int(params.get("in_out", 0)), "Burst Count": int(params.get("burst_count", 0)),
        "Burst Frame": int(params.get("burst_frame", -1000000)),
    }
    for k, v in vals.items():
        if k in ids:
            set_input(mod, ids[k], v)
    obj.update_tag()


def create_emitter(context, params, parent=None, world=None, name=None, collection=None,
                   resolver=None, parent_world=None):
    """An emitter object (child of the part) with the particle simulation.
    `parent_world`: the parent's world matrix when it isn't evaluated yet
    (during an import)."""
    scene = context.scene
    name = name or params.get("kind", "ParticleEmitter")
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    (collection or (parent.users_collection[0] if parent and parent.users_collection
                    else context.collection)).objects.link(obj)
    if parent is not None:
        pw = parent_world if parent_world is not None else parent.matrix_world
        obj.parent = parent
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = pw.inverted_safe() @ (world if world is not None else pw)
    else:
        obj.matrix_world = world if world is not None else Matrix.Translation(scene.cursor.location)
    obj.rblx.kind = "EFFECT"
    obj.rblx.class_name = params.get("kind", "ParticleEmitter")
    obj.rblx.texture_id = params.get("texture") or ""
    image = _load_texture(params.get("texture"), resolver)
    mat = sprite_material("RBX " + name, image, params["color"], params["transparency"],
                          params["light_emission"], flipbook=params.get("flipbook"))
    ng = _particle_group("RBX " + name, params, mat)
    mod = obj.modifiers.new("RBX Particles", "NODES")
    mod.node_group = ng
    set_emitter_inputs(obj, params, scene)
    obj.display_type = "WIRE"
    return obj


def emitter_parts(obj):
    """(node group, size curve node, material, color ramp, transparency curve)."""
    mod = obj.modifiers.get("RBX Particles")
    ng = mod.node_group if mod else None
    size_node = ng.nodes.get("RBX Size") if ng else None
    mat = None
    if ng:
        sm = next((n for n in ng.nodes if n.bl_idname == "GeometryNodeSetMaterial"), None)
        mat = sm.inputs["Material"].default_value if sm else None
    ramp = mat.node_tree.nodes.get("RBX Color") if mat else None
    tcurve = mat.node_tree.nodes.get("RBX Transparency") if mat else None
    return mod, ng, size_node, mat, ramp, tcurve


def effect_modifier(obj):
    for name in ("RBX Particles", "RBX Beam", "RBX Trail"):
        mod = obj.modifiers.get(name) if obj.type == "MESH" else None
        if mod is not None and mod.node_group is not None:
            return mod
    return None


def effect_material(obj):
    mod = effect_modifier(obj)
    if mod is not None:
        sm = next((n for n in mod.node_group.nodes if n.bl_idname == "GeometryNodeSetMaterial"), None)
        if sm is not None and sm.inputs["Material"].default_value is not None:
            return sm.inputs["Material"].default_value
    return obj.data.materials[0] if obj.type == "MESH" and obj.data.materials else None


def update_cameras(scene):
    for obj in scene.objects:
        mod = effect_modifier(obj)
        if mod is None:
            continue
        ids = _input_ids(mod)
        if "Camera" in ids and get_input(mod, ids["Camera"]) != scene.camera:
            set_input(mod, ids["Camera"], scene.camera)


# ---------------------------------------------------------------------------
# Beams

def beam_points(p0, p1, axis0, axis1, curve0, curve1, segments):
    c0 = p0 + axis0 * curve0
    c1 = p1 - axis1 * curve1
    pts = []
    for i in range(segments + 1):
        t = i / segments
        u = 1.0 - t
        pts.append(p0 * u ** 3 + c0 * 3 * u * u * t + c1 * 3 * u * t * t + p1 * t ** 3)
    return pts


def _object_info(ng, sock, loc):
    n = ng.nodes.new("GeometryNodeObjectInfo")
    n.transform_space = "ORIGINAL"
    n.location = loc
    _link(ng, sock, n.inputs["Object"])
    return n


def _store(ng, geo, name, value, dtype="FLOAT", domain="POINT", loc=(0, 0)):
    n = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    n.data_type = dtype
    n.domain = domain
    n.location = loc
    n.inputs["Name"].default_value = name
    _link(ng, geo, n.inputs["Geometry"])
    if isinstance(value, (int, float, tuple)):
        _socket(n.inputs, "Value").default_value = value
    else:
        _link(ng, value, _socket(n.inputs, "Value"))
    return n.outputs["Geometry"]


def _named(ng, name, dtype="FLOAT", loc=(0, 0)):
    n = ng.nodes.new("GeometryNodeInputNamedAttribute")
    n.data_type = dtype
    n.location = loc
    n.inputs["Name"].default_value = name
    return _socket(n.outputs, "Attribute")


def _to_local(ng, geo, loc):
    """Geometry built in world space -> the modifier object's space."""
    selfo = ng.nodes.new("GeometryNodeSelfObject")
    info = _object_info(ng, selfo.outputs[0], (loc[0] - 300, loc[1] - 200))
    inv = ng.nodes.new("FunctionNodeInvertMatrix")
    inv.location = (loc[0] - 150, loc[1] - 200)
    _link(ng, info.outputs["Transform"], inv.inputs["Matrix"])
    tr = ng.nodes.new("GeometryNodeTransform")
    tr.location = loc
    _set(tr, "Mode", "Matrix")
    _link(ng, geo, tr.inputs["Geometry"])
    _link(ng, inv.outputs["Matrix"], tr.inputs["Transform"])
    return tr.outputs["Geometry"]


def _beam_group(name, material):
    """Live Beam: a Bezier ribbon between two attachment objects (follows them)."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    I_ = ng.interface
    I_.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    I_.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for sname, stype in (("Attachment0", "NodeSocketObject"), ("Attachment1", "NodeSocketObject"),
                         ("Width0", "NodeSocketFloat"), ("Width1", "NodeSocketFloat"),
                         ("CurveSize0", "NodeSocketFloat"), ("CurveSize1", "NodeSocketFloat"),
                         ("Segments", "NodeSocketInt"), ("Face Camera", "NodeSocketBool"),
                         ("Camera", "NodeSocketObject"), ("Texture Length", "NodeSocketFloat"),
                         ("Wrap", "NodeSocketBool")):
        I_.new_socket(sname, in_out="INPUT", socket_type=stype)
    N = ng.nodes
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    gi.location, go.location = (-1600, 0), (1400, 0)
    I = gi.outputs
    a0 = _object_info(ng, I["Attachment0"], (-1300, 300))
    a1 = _object_info(ng, I["Attachment1"], (-1300, -100))

    def tdir(info, vec, loc):
        n = N.new("FunctionNodeTransformDirection")
        n.location = loc
        n.inputs["Direction"].default_value = vec
        _link(ng, info.outputs["Transform"], n.inputs["Transform"])
        return _vmath(ng, "NORMALIZE", n.outputs[0], loc=(loc[0] + 150, loc[1]))

    # Roblox: CurveSize bends along each attachment's Axis (+X = Blender local -X)
    ax0 = tdir(a0, (-1.0, 0.0, 0.0), (-1100, 300))
    ax1 = tdir(a1, (-1.0, 0.0, 0.0), (-1100, -100))
    up0 = tdir(a0, (0.0, 0.0, 1.0), (-1100, 500))
    bez = N.new("GeometryNodeCurvePrimitiveBezierSegment")
    bez.mode = "POSITION"
    bez.location = (-700, 100)
    _link(ng, I["Segments"], bez.inputs["Resolution"])
    _link(ng, a0.outputs["Location"], bez.inputs["Start"])
    _link(ng, a1.outputs["Location"], bez.inputs["End"])
    _link(ng, _vmath(ng, "ADD", a0.outputs["Location"],
                     _vmath(ng, "SCALE", ax0, scale=I["CurveSize0"], loc=(-900, 250)), loc=(-850, 200)),
          bez.inputs["Start Handle"])
    _link(ng, _vmath(ng, "SUBTRACT", a1.outputs["Location"],
                     _vmath(ng, "SCALE", ax1, scale=I["CurveSize1"], loc=(-900, -50)), loc=(-850, -50)),
          bez.inputs["End Handle"])
    curve = bez.outputs["Curve"]
    param = N.new("GeometryNodeSplineParameter")
    param.location = (-700, -300)
    t = param.outputs["Factor"]
    width = N.new("ShaderNodeMix")
    width.data_type = "FLOAT"
    width.location = (-500, -300)
    _link(ng, t, _socket(width.inputs, "Factor"))
    _link(ng, I["Width0"], _socket(width.inputs, "A"))
    _link(ng, I["Width1"], _socket(width.inputs, "B"))
    curve = _store(ng, curve, "rbx_t", t, loc=(-500, 100))
    curve = _store(ng, curve, "rbx_w", _socket(width.outputs, "Result"), loc=(-350, 100))
    # Width runs across the beam: facing the camera, or across the attachment's up
    tangent = N.new("GeometryNodeInputTangent")
    tangent.location = (-500, -500)
    posn = N.new("GeometryNodeInputPosition")
    posn.location = (-700, -600)
    cam = _object_info(ng, I["Camera"], (-700, -750))
    to_cam = _vmath(ng, "SUBTRACT", cam.outputs["Location"], posn.outputs[0], loc=(-500, -700))
    ref = N.new("GeometryNodeSwitch")
    ref.input_type = "VECTOR"
    ref.location = (-350, -650)
    _link(ng, I["Face Camera"], ref.inputs["Switch"])
    _link(ng, up0, _socket(ref.inputs, "False"))
    _link(ng, to_cam, _socket(ref.inputs, "True"))
    side = _vmath(ng, "NORMALIZE", _vmath(ng, "CROSS_PRODUCT", tangent.outputs[0], ref.outputs[0],
                                          loc=(-200, -600)), loc=(-50, -600))
    setn = N.new("GeometryNodeSetCurveNormal")
    setn.location = (-150, 100)
    _link(ng, curve, setn.inputs["Curve"])
    if "Normal" in setn.inputs:
        if "Mode" in setn.inputs:
            _set(setn, "Mode", "Free")
        else:
            setn.mode = "FREE"
        _link(ng, side, setn.inputs["Normal"])
    curve = setn.outputs["Curve"]
    line = N.new("GeometryNodeCurvePrimitiveLine")
    line.location = (-150, -150)
    line.inputs["Start"].default_value = (-0.5, 0.0, 0.0)
    line.inputs["End"].default_value = (0.5, 0.0, 0.0)
    pparam = N.new("GeometryNodeSplineParameter")
    pparam.location = (-150, -300)
    profile = _store(ng, line.outputs["Curve"], "rbx_v", pparam.outputs["Factor"], loc=(50, -150))
    c2m = N.new("GeometryNodeCurveToMesh")
    c2m.location = (200, 100)
    _link(ng, curve, c2m.inputs["Curve"])
    _link(ng, profile, c2m.inputs["Profile Curve"])
    if "Scale" in c2m.inputs:
        _link(ng, _named(ng, "rbx_w", loc=(50, 0)), c2m.inputs["Scale"])
    mesh = c2m.outputs["Mesh"]
    # UV: along the beam (Stretch: 0..TextureLength, Wrap: repeats every TextureLength studs)
    clen = N.new("GeometryNodeCurveLength")
    clen.location = (200, -300)
    _link(ng, bez.outputs["Curve"], clen.inputs["Curve"])
    u_wrap = _math(ng, "MULTIPLY", _named(ng, "rbx_t", loc=(200, -450)),
                   _math(ng, "DIVIDE", clen.outputs[0],
                         _math(ng, "MAXIMUM", I["Texture Length"], 0.001, loc=(350, -500)),
                         loc=(500, -450)), loc=(650, -400))
    u_str = _math(ng, "MULTIPLY", _named(ng, "rbx_t", loc=(450, -300)), I["Texture Length"],
                  loc=(650, -300))
    u = N.new("GeometryNodeSwitch")
    u.input_type = "FLOAT"
    u.location = (800, -300)
    _link(ng, I["Wrap"], u.inputs["Switch"])
    _link(ng, u_str, _socket(u.inputs, "False"))
    _link(ng, u_wrap, _socket(u.inputs, "True"))
    uv = N.new("ShaderNodeCombineXYZ")
    uv.location = (950, -300)
    _link(ng, u.outputs[0], uv.inputs["X"])
    _link(ng, _named(ng, "rbx_v", loc=(800, -450)), uv.inputs["Y"])
    mesh = _store(ng, mesh, "UVMap", uv.outputs[0], "FLOAT2", "CORNER", loc=(1000, 100))
    sm = N.new("GeometryNodeSetMaterial")
    sm.location = (1150, 100)
    sm.inputs["Material"].default_value = material
    _link(ng, mesh, sm.inputs["Geometry"])
    _link(ng, _to_local(ng, sm.outputs["Geometry"], (1300, 100)), go.inputs["Geometry"])
    return ng


def _trail_group(name, material):
    """Trail: every frame a new ribbon segment is added between the two
    attachments' previous and current positions; segments fade over Lifetime."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    I_ = ng.interface
    I_.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    I_.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for sname, stype in (("Attachment0", "NodeSocketObject"), ("Attachment1", "NodeSocketObject"),
                         ("Enabled", "NodeSocketBool"), ("Lifetime", "NodeSocketFloat"),
                         ("Min Length", "NodeSocketFloat"), ("Texture Length", "NodeSocketFloat")):
        I_.new_socket(sname, in_out="INPUT", socket_type=stype)
    N = ng.nodes
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    gi.location, go.location = (-1600, 0), (1500, 0)
    I = gi.outputs
    p0 = _object_info(ng, I["Attachment0"], (-1300, 400)).outputs["Location"]
    p1 = _object_info(ng, I["Attachment1"], (-1300, 100)).outputs["Location"]
    si = N.new("GeometryNodeSimulationInput")
    so = N.new("GeometryNodeSimulationOutput")
    si.location, so.location = (-1000, 0), (900, 0)
    si.pair_with_output(so)
    so.state_items.new("VECTOR", "Prev0")
    so.state_items.new("VECTOR", "Prev1")
    _link(ng, p0, si.inputs["Prev0"])
    _link(ng, p1, si.inputs["Prev1"])
    dt = si.outputs["Delta Time"]
    # age existing segments, drop the old ones
    geo = _store(ng, si.outputs["Geometry"], "age",
                 _math(ng, "ADD", _named(ng, "age", loc=(-800, 300)), dt, loc=(-650, 300)), loc=(-500, 0))
    old = N.new("FunctionNodeCompare")
    old.data_type = "FLOAT"
    old.operation = "GREATER_THAN"
    old.location = (-500, 300)
    _link(ng, _named(ng, "age", loc=(-650, 400)), _socket(old.inputs, "A"))
    _link(ng, I["Lifetime"], _socket(old.inputs, "B"))
    dele = N.new("GeometryNodeDeleteGeometry")
    dele.location = (-300, 0)
    _link(ng, geo, dele.inputs["Geometry"])
    _link(ng, old.outputs["Result"], dele.inputs["Selection"])
    # the new segment: a quad prev0 -> prev1 -> now0 -> now1
    grid = N.new("GeometryNodeMeshGrid")
    grid.location = (-800, -300)
    _set(grid, "Vertices X", 2)
    _set(grid, "Vertices Y", 2)
    index = N.new("GeometryNodeInputIndex")
    index.location = (-800, -500)

    def by_index(dtype, values, loc):
        n = N.new("GeometryNodeIndexSwitch")
        n.data_type = dtype
        n.location = loc
        while len(n.index_switch_items) < len(values):
            n.index_switch_items.new()
        _link(ng, index.outputs[0], n.inputs["Index"])
        for i, v in enumerate(values):
            if isinstance(v, (int, float)):
                n.inputs[i + 1].default_value = v
            else:
                _link(ng, v, n.inputs[i + 1])
        return n.outputs[0]

    setp = N.new("GeometryNodeSetPosition")
    setp.location = (-500, -300)
    _link(ng, grid.outputs["Mesh"], setp.inputs["Geometry"])
    _link(ng, by_index("VECTOR", [si.outputs["Prev0"], si.outputs["Prev1"], p0, p1], (-650, -450)),
          setp.inputs["Position"])
    quad = _store(ng, setp.outputs["Geometry"], "age", by_index("FLOAT", [dt, dt, 0.0, 0.0], (-500, -550)),
                  loc=(-350, -300))
    quad = _store(ng, quad, "rbx_side", by_index("FLOAT", [0.0, 1.0, 0.0, 1.0], (-350, -550)),
                  loc=(-200, -300))
    moved = _math(ng, "MAXIMUM", _vmath(ng, "DISTANCE", p0, si.outputs["Prev0"], loc=(-650, -700)),
                  _vmath(ng, "DISTANCE", p1, si.outputs["Prev1"], loc=(-650, -800)), loc=(-500, -750))
    far = _math(ng, "GREATER_THAN", moved, _math(ng, "MAXIMUM", I["Min Length"], 0.0001, loc=(-500, -850)),
                loc=(-350, -750))
    emit = _math(ng, "MULTIPLY", far, I["Enabled"], loc=(-200, -750))
    pick = N.new("GeometryNodeSwitch")
    pick.input_type = "GEOMETRY"
    pick.location = (0, -300)
    _link(ng, emit, pick.inputs["Switch"])
    _link(ng, quad, _socket(pick.inputs, "True"))
    join = N.new("GeometryNodeJoinGeometry")
    join.location = (200, 0)
    _link(ng, pick.outputs[0], join.inputs["Geometry"])
    _link(ng, dele.outputs["Geometry"], join.inputs["Geometry"])
    _link(ng, join.outputs["Geometry"], so.inputs["Geometry"])
    for k, cur in (("Prev0", p0), ("Prev1", p1)):
        keep = N.new("GeometryNodeSwitch")
        keep.input_type = "VECTOR"
        _link(ng, emit, keep.inputs["Switch"])
        _link(ng, si.outputs[k], _socket(keep.inputs, "False"))
        _link(ng, cur, _socket(keep.inputs, "True"))
        _link(ng, keep.outputs[0], so.inputs[k])
    trail = N.new("GeometryNodeMergeByDistance")
    trail.location = (1000, 0)
    _set(trail, "Distance", 0.0001)
    _link(ng, so.outputs["Geometry"], trail.inputs["Geometry"])
    # colour / transparency over the trail's life, UVs along it
    t = _math(ng, "MINIMUM", _math(ng, "DIVIDE", _named(ng, "age", loc=(1000, -300)),
                                   _math(ng, "MAXIMUM", I["Lifetime"], 0.001, loc=(1000, -400)),
                                   loc=(1150, -300)), 1.0, loc=(1250, -300))
    out = _store(ng, trail.outputs["Geometry"], "rbx_t", t, loc=(1150, 0))
    uv = N.new("ShaderNodeCombineXYZ")
    uv.location = (1250, -450)
    _link(ng, t, uv.inputs["X"])
    _link(ng, _named(ng, "rbx_side", loc=(1100, -500)), uv.inputs["Y"])
    out = _store(ng, out, "UVMap", uv.outputs[0], "FLOAT2", "CORNER", loc=(1300, 0))
    sm = N.new("GeometryNodeSetMaterial")
    sm.location = (1400, 0)
    sm.inputs["Material"].default_value = material
    _link(ng, out, sm.inputs["Geometry"])
    _link(ng, _to_local(ng, sm.outputs["Geometry"], (1500, 0)), go.inputs["Geometry"])
    return ng


def _set_inputs(obj, modname, values):
    mod = obj.modifiers.get(modname)
    ids = _input_ids(mod)
    for k, v in values.items():
        if k in ids:
            set_input(mod, ids[k], v)


def create_live_beam(context, params, a0, a1, name="Beam", collection=None, resolver=None):
    """Beam between two attachment objects that follows them as they move."""
    scene = context.scene
    scale = coords.stud_scale(scene)
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    (collection or context.collection).objects.link(obj)
    obj.rblx.kind = "EFFECT"
    obj.rblx.class_name = "Beam"
    obj.rblx.texture_id = params.get("texture") or ""
    image = _load_texture(params.get("texture"), resolver)
    mat = sprite_material("RBX " + name, image, params["color"], params["transparency"],
                          params.get("light_emission", 0.0), instancer=False)
    mod = obj.modifiers.new("RBX Beam", "NODES")
    mod.node_group = _beam_group("RBX " + name, mat)
    _set_inputs(obj, "RBX Beam", {
        "Attachment0": a0, "Attachment1": a1,
        "Width0": params["width0"] * scale, "Width1": params["width1"] * scale,
        "CurveSize0": params["curve0"] * scale, "CurveSize1": params["curve1"] * scale,
        "Segments": max(1, int(params.get("segments", 10))),
        "Face Camera": bool(params.get("face_camera")), "Camera": scene.camera,
        "Texture Length": params.get("texture_length", 1.0) * (scale if params.get("texture_mode", 0) else 1.0),
        "Wrap": params.get("texture_mode", 0) != 0})
    obj.visible_shadow = False
    obj.hide_render = obj.hide_viewport = not params.get("enabled", True)
    return obj


def create_trail(context, params, a0, a1, name="Trail", collection=None, resolver=None):
    scene = context.scene
    scale = coords.stud_scale(scene)
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    (collection or context.collection).objects.link(obj)
    obj.rblx.kind = "EFFECT"
    obj.rblx.class_name = "Trail"
    obj.rblx.texture_id = params.get("texture") or ""
    image = _load_texture(params.get("texture"), resolver)
    mat = sprite_material("RBX " + name, image, params["color"], params["transparency"],
                          params.get("light_emission", 0.0), instancer=False)
    mod = obj.modifiers.new("RBX Trail", "NODES")
    mod.node_group = _trail_group("RBX " + name, mat)
    _set_inputs(obj, "RBX Trail", {
        "Attachment0": a0, "Attachment1": a1, "Enabled": bool(params.get("enabled", True)),
        "Lifetime": float(params.get("lifetime", 2.0)),
        "Min Length": float(params.get("min_length", 0.1)) * scale,
        "Texture Length": float(params.get("texture_length", 1.0))})
    obj.visible_shadow = False
    return obj


def trail_params_from_instance(inst):
    p = inst.props

    def num(name, default):
        v = p.get(name)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    return dict(lifetime=num("Lifetime", 2.0), min_length=num("MinLength", 0.1),
                light_emission=num("LightEmission", 0.0), texture=p.get("Texture") or None,
                texture_length=num("TextureLength", 1.0),
                color=color_sequence(p.get("Color"), [(0, 1, 1, 1, 0), (1, 1, 1, 1, 0)]),
                transparency=number_sequence(p.get("Transparency"), [(0, 0.5, 0), (1, 0.5, 0)]),
                enabled=p.get("Enabled", True) is not False)


def explosion_emitters(context, location, radius=4.0, frame=None, collection=None):
    """Roblox Explosion look: a burst of fire and a puff of smoke on one frame."""
    scene = context.scene
    frame = scene.frame_current if frame is None else frame
    world = Matrix.Translation(location)
    r = max(radius, 0.5)
    core = dict(PARTICLE_DEFAULTS, kind="Explosion", rate=0.0, burst_count=45, burst_frame=frame,
                lifetime=(0.35, 0.7), speed=(r * 2.0, r * 4.0), drag=4.0, shape=1, surface=True,
                emit_size=(r * 0.4,) * 3, rotation=(-180.0, 180.0), rot_speed=(-120.0, 120.0),
                size=[(0.0, r * 0.5, 0.0), (1.0, r * 1.1, 0.0)],
                transparency=[(0.0, 0.0, 0.0), (0.6, 0.3, 0.0), (1.0, 1.0, 0.0)],
                color=[(0.0, 1.0, 0.9, 0.5, 0.0), (0.5, 1.0, 0.45, 0.1, 0.0), (1.0, 0.4, 0.1, 0.05, 0.0)],
                light_emission=1.0, texture=TEXTURE_DIR + "fire_main.dds")
    smoke = dict(PARTICLE_DEFAULTS, kind="Explosion", rate=0.0, burst_count=25, burst_frame=frame,
                 lifetime=(1.5, 2.5), speed=(r * 1.0, r * 2.0), drag=2.0, shape=1, surface=True,
                 emit_size=(r * 0.5,) * 3, acceleration=(0.0, 3.0, 0.0), rotation=(-180.0, 180.0),
                 rot_speed=(-30.0, 30.0), size=[(0.0, r * 0.6, 0.0), (1.0, r * 1.6, 0.0)],
                 transparency=[(0.0, 0.4, 0.0), (1.0, 1.0, 0.0)],
                 color=[(0.0, 0.35, 0.33, 0.32, 0.0), (1.0, 0.55, 0.55, 0.55, 0.0)],
                 texture=TEXTURE_DIR + "smoke_main.dds")
    made = []
    for params, nm in ((smoke, "Explosion Smoke"), (core, "Explosion")):
        made.append(create_emitter(context, params, world=world, name=nm, collection=collection))
    return made


def create_beam(context, params, name="Beam", collection=None, resolver=None):
    """Fixed textured ribbon between two attachment positions (world matrices),
    for beams whose attachments aren't objects in the scene."""
    scene = context.scene
    scale = coords.stud_scale(scene)
    m0, m1 = params["world0"], params["world1"]
    p0, p1 = m0.translation, m1.translation
    # CurveSize bends the beam along each attachment's Axis (Roblox +X = Blender -X locally);
    # the ribbon's width lies across the attachment's up (Roblox +Y = Blender +Z)
    ax0 = (m0.to_3x3() @ Vector((-1.0, 0.0, 0.0))).normalized()
    ax1 = (m1.to_3x3() @ Vector((-1.0, 0.0, 0.0))).normalized()
    segs = max(1, int(params.get("segments", 10)))
    pts = beam_points(p0, p1, ax0, ax1, params["curve0"] * scale, params["curve1"] * scale, segs)
    up0 = (m0.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    cam = scene.camera
    verts, faces, uvs, ts = [], [], [], []
    length = sum((pts[i + 1] - pts[i]).length for i in range(segs)) or 1.0
    run = 0.0
    for i, p in enumerate(pts):
        t = i / segs
        tangent = (pts[min(i + 1, segs)] - pts[max(i - 1, 0)]).normalized()
        if params.get("face_camera") and cam is not None:
            ref = (cam.matrix_world.translation - p).normalized()
        else:
            ref = up0
        side = tangent.cross(ref)
        if side.length < 1e-6:
            side = tangent.orthogonal()
        side.normalize()
        w = (params["width0"] * (1 - t) + params["width1"] * t) * scale * 0.5
        verts += [p - side * w, p + side * w]
        if i:
            run += (pts[i] - pts[i - 1]).length
        mode = params.get("texture_mode", 0)
        if mode == 1:  # Wrap: repeats every TextureLength studs
            u = run / max(params.get("texture_length", 1.0) * scale, 1e-6)
        elif mode == 2:  # Static
            u = run / max(params.get("texture_length", 1.0) * scale, 1e-6)
        else:  # Stretch
            u = t * params.get("texture_length", 1.0)
        uvs.append((u, 0.0))
        uvs.append((u, 1.0))
        ts += [t, t]
    for i in range(segs):
        a = i * 2
        faces.append((a, a + 2, a + 3, a + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    uv_layer = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            uv_layer.data[li].uv = uvs[vi]
    attr = me.attributes.new("rbx_t", "FLOAT", "POINT")
    attr.data.foreach_set("value", ts)
    obj = bpy.data.objects.new(name, me)
    (collection or context.collection).objects.link(obj)
    obj.rblx.kind = "EFFECT"
    obj.rblx.class_name = "Beam"
    image = _load_texture(params.get("texture"), resolver)
    mat = sprite_material("RBX " + name, image, params["color"], params["transparency"],
                          params.get("light_emission", 0.0), instancer=False)
    me.materials.append(mat)
    obj.visible_shadow = False
    return obj


def beam_params_from_instance(inst, attachment_world):
    p = inst.props
    a0, a1 = p.get("Attachment0"), p.get("Attachment1")
    w0, w1 = attachment_world(a0), attachment_world(a1)
    if w0 is None or w1 is None:
        return None

    def num(name, default):
        v = p.get(name)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    return dict(
        world0=w0, world1=w1, width0=num("Width0", 1.0), width1=num("Width1", 1.0),
        curve0=num("CurveSize0", 0.0), curve1=num("CurveSize1", 0.0),
        segments=int(num("Segments", 10)), texture=p.get("Texture") or None,
        texture_length=num("TextureLength", 1.0), texture_mode=int(num("TextureMode", 0)),
        light_emission=num("LightEmission", 0.0), face_camera=bool(p.get("FaceCamera", False)),
        color=color_sequence(p.get("Color"), [(0, 1, 1, 1, 0), (1, 1, 1, 1, 0)]),
        transparency=number_sequence(p.get("Transparency"), [(0, 0.5, 0), (1, 0.5, 0)]),
        enabled=p.get("Enabled", True) is not False)


# ---------------------------------------------------------------------------
# Highlight

OUTLINE_MOD = "RBX Highlight Outline"


def _outline_material(color, transparency):
    name = "RBX Highlight Outline"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    mat.use_backface_culling = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    col = nt.nodes.new("ShaderNodeAttribute")
    col.attribute_type = "OBJECT"
    col.attribute_name = "rblx.highlight_outline"
    alpha = nt.nodes.new("ShaderNodeAttribute")
    alpha.attribute_type = "OBJECT"
    alpha.attribute_name = "rblx.highlight_outline_alpha"
    em = nt.nodes.new("ShaderNodeEmission")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    _link(nt, col.outputs["Color"], em.inputs["Color"])
    _link(nt, alpha.outputs["Fac"], mix.inputs["Fac"])
    _link(nt, tr.outputs[0], mix.inputs[1])
    _link(nt, em.outputs[0], mix.inputs[2])
    _link(nt, mix.outputs[0], out.inputs["Surface"])
    return mat


def apply_highlight(obj, scene=None):
    """Show / hide the Highlight on one part from its rblx.highlight_* settings."""
    from . import materials
    r = obj.rblx
    if obj.type != "MESH":
        return
    on = r.highlight_enabled
    r.highlight_fill_alpha = (1.0 - r.highlight_fill_transparency) if on else 0.0
    r.highlight_outline_alpha = 1.0 - r.highlight_outline_transparency
    mod = obj.modifiers.get(OUTLINE_MOD)
    if on and r.highlight_outline_transparency < 0.999:
        mat = _outline_material(r.highlight_outline, r.highlight_outline_transparency)
        mats = obj.data.materials
        if mat.name not in [m.name for m in mats if m]:
            mats.append(mat)
        idx = [m.name if m else "" for m in mats].index(mat.name)
        if mod is None:
            mod = obj.modifiers.new(OUTLINE_MOD, "SOLIDIFY")
        scale = coords.stud_scale(scene or bpy.context.scene)
        mod.thickness = 0.08 * scale
        mod.offset = 1.0
        mod.use_flip_normals = True
        mod.use_rim = False
        mod.material_offset = idx
        mod.show_in_editmode = False
    elif mod is not None:
        obj.modifiers.remove(mod)
    if r.kind == "PART":
        materials.refresh(obj)
    obj.update_tag()


def highlight_targets(obj):
    """Parts a Highlight on `obj` affects (the part, or every part in a model)."""
    return [o for o in (obj, *obj.children_recursive) if o.type == "MESH" and o.rblx.kind == "PART"]


# ---------------------------------------------------------------------------
# Operators

EFFECT_KINDS = [
    ("PARTICLES", "ParticleEmitter", "Roblox ParticleEmitter (sparkle texture)", "PARTICLES", 0),
    ("FIRE", "Fire", "Roblox Fire", "LIGHT_SUN", 1),
    ("SMOKE", "Smoke", "Roblox Smoke", "OUTLINER_DATA_VOLUME", 2),
    ("SPARKLES", "Sparkles", "Roblox Sparkles", "SHADERFX", 3),
]


class RBLX_OT_add_effect(bpy.types.Operator):
    """Add a Roblox particle effect to the selected parts"""
    bl_idname = "rblx.add_effect"
    bl_label = "Add Effect"
    bl_options = {"REGISTER", "UNDO"}

    kind: bpy.props.EnumProperty(name="Effect", items=EFFECT_KINDS, default="PARTICLES")

    def execute(self, context):
        parts = [o for o in context.selected_objects if o.rblx.kind == "PART"]
        made = []
        for part in parts or [None]:
            params = {"PARTICLES": dict(PARTICLE_DEFAULTS), "FIRE": fire_params(),
                      "SMOKE": smoke_params(), "SPARKLES": sparkles_params()}[self.kind]
            if part is not None:
                size = tuple(part.rblx.size)
                params["emit_size"] = tuple(min(s, 2.0) for s in size) \
                    if self.kind in ("FIRE", "SMOKE") else size
                loc, rot, _ = part.matrix_world.decompose()
                world = Matrix.LocRotScale(loc, rot, None)
            else:
                world = None
            made.append(create_emitter(context, params, parent=part, world=world))
        for o in context.selected_objects:
            o.select_set(False)
        for o in made:
            o.select_set(True)
        context.view_layer.objects.active = made[-1]
        self.report({"INFO"}, "Play from the first frame to see the particles (or Bake them)")
        return {"FINISHED"}


def make_attachment_empty(context, part, local_offset, name="Attachment"):
    """An Attachment (empty) on `part`, offset in the part's own Blender axes."""
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "SPHERE"
    e.empty_display_size = 0.15 * coords.stud_scale(context.scene)
    (part.users_collection[0] if part.users_collection else context.collection).objects.link(e)
    e.parent = part
    e.matrix_parent_inverse = Matrix.Identity(4)
    loc, rot, _s = part.matrix_world.decompose()
    world = Matrix.LocRotScale(loc, rot, None) @ Matrix.Translation(local_offset)
    e.matrix_basis = part.matrix_world.inverted_safe() @ world
    e.rblx.kind = "ATTACHMENT"
    e.rblx.class_name = "Attachment"
    return e


DEFAULT_RIBBON = dict(width0=1.0, width1=1.0, curve0=0.0, curve1=0.0, segments=10, texture=None,
                      texture_length=1.0, texture_mode=0, light_emission=0.5, face_camera=True,
                      color=[(0, 1, 1, 1, 0), (1, 1, 1, 1, 0)],
                      transparency=[(0, 0.0, 0), (1, 1.0, 0)], enabled=True, lifetime=1.0,
                      min_length=0.1)


class RBLX_OT_add_trail(bpy.types.Operator):
    """Add a Roblox Trail to the selected part: it leaves a fading ribbon behind as the part
    moves (between two attachments at the part's top and bottom)"""
    bl_idname = "rblx.add_trail"
    bl_label = "Add Trail"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == "MESH"

    def execute(self, context):
        part = context.active_object
        h = (part.rblx.size[1] / 2.0 if part.rblx.kind == "PART" else part.dimensions.z / 2.0) \
            * coords.stud_scale(context.scene)
        a0 = make_attachment_empty(context, part, (0.0, 0.0, h), "TrailTop")
        a1 = make_attachment_empty(context, part, (0.0, 0.0, -h), "TrailBottom")
        obj = create_trail(context, dict(DEFAULT_RIBBON), a0, a1)
        self.report({"INFO"}, "Animate the part and play from the first frame to see the trail")
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class RBLX_OT_add_beam(bpy.types.Operator):
    """Add a Roblox Beam between the two selected parts (it follows them when they move)"""
    bl_idname = "rblx.add_beam"
    bl_label = "Add Beam"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) == 2

    def execute(self, context):
        a, b = context.selected_objects
        a0 = a if a.rblx.kind == "ATTACHMENT" else make_attachment_empty(context, a, (0, 0, 0), "Attachment0")
        a1 = b if b.rblx.kind == "ATTACHMENT" else make_attachment_empty(context, b, (0, 0, 0), "Attachment1")
        obj = create_live_beam(context, dict(DEFAULT_RIBBON, transparency=[(0, 0.0, 0), (1, 0.0, 0)]),
                               a0, a1)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class RBLX_OT_add_explosion(bpy.types.Operator):
    """Add a Roblox Explosion at the selected part (or the 3D cursor) on the current frame"""
    bl_idname = "rblx.add_explosion"
    bl_label = "Explosion"
    bl_options = {"REGISTER", "UNDO"}

    blast_radius: FloatProperty(name="BlastRadius", default=4.0, min=0.5, soft_max=30.0)

    def execute(self, context):
        o = context.active_object
        loc = o.matrix_world.translation.copy() if o is not None and o.select_get() \
            else context.scene.cursor.location.copy()
        explosion_emitters(context, loc, self.blast_radius * coords.stud_scale(context.scene))
        self.report({"INFO"}, "Explosion on frame %d (play from the first frame, or Bake)"
                    % context.scene.frame_current)
        return {"FINISHED"}


class RBLX_OT_add_highlight(bpy.types.Operator):
    """Add a Roblox Highlight (fill tint and outline) to the selected parts or models"""
    bl_idname = "rblx.add_highlight"
    bl_label = "Highlight"
    bl_options = {"REGISTER", "UNDO"}

    remove: BoolProperty(name="Remove", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        from .props import no_propagation
        parts = set()
        for o in context.selected_objects:
            parts.update(highlight_targets(o))
        with no_propagation():
            for p in parts:
                p.rblx.highlight_enabled = not self.remove
        return {"FINISHED"}


class RBLX_OT_bake_particles(bpy.types.Operator):
    """Bake the particle simulations so any frame renders correctly (and scrubbing works)"""
    bl_idname = "rblx.bake_particles"
    bl_label = "Bake Particles"

    free: BoolProperty(name="Free", default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        emitters = [o for o in context.scene.objects
                    if o.modifiers.get("RBX Particles") or o.modifiers.get("RBX Trail")]
        if not emitters:
            self.report({"INFO"}, "No particle effects in this scene")
            return {"CANCELLED"}
        selected = list(context.selected_objects)
        active = context.view_layer.objects.active
        for o in context.selected_objects:
            o.select_set(False)
        for o in emitters:
            o.select_set(True)
        context.view_layer.objects.active = emitters[0]
        try:
            if self.free:
                bpy.ops.object.simulation_nodes_cache_delete(selected=True)
            else:
                bpy.ops.object.simulation_nodes_cache_bake(selected=True)
        finally:
            for o in emitters:
                o.select_set(False)
            for o in selected:
                o.select_set(True)
            context.view_layer.objects.active = active
        return {"FINISHED"}


class RBLX_OT_effect_texture(bpy.types.Operator):
    """Change the effect's texture (asset id, rbxasset:// path or image file)"""
    bl_idname = "rblx.effect_texture"
    bl_label = "Set Texture"
    bl_options = {"REGISTER", "UNDO"}

    content: bpy.props.StringProperty(name="Texture", default="",
                                      description="Asset id, rbxassetid://, rbxasset:// or a file path")

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.rblx.kind == "EFFECT"

    def invoke(self, context, event):
        self.content = context.active_object.rblx.texture_id
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import os
        from . import materials
        obj = context.active_object
        img = materials.load_image(self.content) if os.path.isfile(self.content) else \
            _load_texture(self.content.strip())
        if img is None:
            self.report({"WARNING"}, "Couldn't load that texture")
            return {"CANCELLED"}
        mat = effect_material(obj)
        tex = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"), None) \
            if mat else None
        if tex is None:
            self.report({"WARNING"}, "This effect has no image texture slot")
            return {"CANCELLED"}
        tex.image = img
        obj.rblx.texture_id = self.content
        return {"FINISHED"}


class RBLX_OT_apply_post_effects(bpy.types.Operator):
    """Rebuild the post-processing effects (compositor and camera depth of field)"""
    bl_idname = "rblx.apply_post_effects"
    bl_label = "Apply Effects"

    def execute(self, context):
        if not apply_post_effects(context.scene):
            self.report({"WARNING"}, "The scene already has its own compositor nodes: left untouched")
            return {"CANCELLED"}
        update_cameras(context.scene)
        return {"FINISHED"}


# ---------------------------------------------------------------------------

CLASSES = (RBLX_PostEffectsProps, RBLX_OT_add_effect, RBLX_OT_add_trail, RBLX_OT_add_beam,
           RBLX_OT_add_explosion, RBLX_OT_add_highlight, RBLX_OT_bake_particles,
           RBLX_OT_effect_texture, RBLX_OT_apply_post_effects)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.rblx_effects = PointerProperty(type=RBLX_PostEffectsProps)
    if _frame_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_frame_handler)


def unregister():
    if _frame_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_frame_handler)
    del bpy.types.Scene.rblx_effects
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
