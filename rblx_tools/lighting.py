"""Roblox Lighting service settings mapped onto a Blender sun, moon and
world. The mapping is an approximation: Roblox's renderer is not Blender's,
but the controls behave the same way (ClockTime moves the sun, Brightness
scales it, OutdoorAmbient fills shadows, Fog fades distance, ...)."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from mathutils import Vector

from . import coords
from .rbx.color import to_linear

COLLECTION_NAME = "Roblox Lighting"
SUN_NAME = "RBX Sun"
MOON_NAME = "RBX Moon"
WORLD_NAME = "RBX World"

_applying = False


def _on_change(self, context):
    if _applying or not self.live_update:
        return
    apply_lighting(context.scene)


def _color(name, default, desc=""):
    """Colour property; `default` is given as a Roblox (sRGB) value and stored
    linear, like every colour in Blender."""
    return FloatVectorProperty(name=name, size=3, subtype="COLOR", min=0.0, max=1.0,
                               default=to_linear(default), update=_on_change, description=desc)


SKY_ITEMS = [
    ("GRADIENT", "Roblox-style Sky", "Simple sky gradient with a sun disc that follows ClockTime"),
    ("PHYSICAL", "Physical Sky", "Blender's physical sky texture"),
    ("IMAGE", "Sky Image", "Equirectangular image / HDRI"),
    ("NONE", "Solid Color", "Plain background (uses Fog Color)"),
]


class RBLX_LightingProps(bpy.types.PropertyGroup):
    live_update: BoolProperty(name="Live Update", default=True,
                              description="Apply changes to the scene immediately")

    clock_time: FloatProperty(name="ClockTime", min=0.0, max=24.0, default=14.5,
                              update=_on_change, description="Time of day in hours")
    geographic_latitude: FloatProperty(name="GeographicLatitude", min=-90.0, max=90.0,
                                       default=41.733, update=_on_change)
    brightness: FloatProperty(name="Brightness", min=0.0, soft_max=10.0, default=3.0,
                              update=_on_change, description="Sun/moon intensity")
    ambient: _color("Ambient", (0.0, 0.0, 0.0), "Light in areas the sky can't reach")
    outdoor_ambient: _color("OutdoorAmbient", (0.5, 0.5, 0.5), "Light from the sky outdoors")
    color_shift_top: _color("ColorShift_Top", (0.0, 0.0, 0.0), "Tint of sun-facing surfaces")
    color_shift_bottom: _color("ColorShift_Bottom", (0.0, 0.0, 0.0), "Tint of surfaces facing away")
    environment_diffuse_scale: FloatProperty(name="EnvironmentDiffuseScale", min=0.0, max=1.0,
                                             default=1.0, update=_on_change)
    environment_specular_scale: FloatProperty(name="EnvironmentSpecularScale", min=0.0, max=1.0,
                                              default=1.0, update=_on_change)
    exposure_compensation: FloatProperty(name="ExposureCompensation", min=-3.0, max=3.0,
                                         default=0.0, update=_on_change)
    global_shadows: BoolProperty(name="GlobalShadows", default=True, update=_on_change)
    shadow_softness: FloatProperty(name="ShadowSoftness", min=0.0, max=1.0, default=0.2,
                                   update=_on_change)

    fog_color: _color("FogColor", (0.753, 0.753, 0.753))
    fog_start: FloatProperty(name="FogStart", min=0.0, default=0.0, update=_on_change)
    fog_end: FloatProperty(name="FogEnd", min=0.0, default=100000.0, update=_on_change,
                           description="Fog is off at Roblox's default of 100000")

    atmosphere_density: FloatProperty(name="Density", min=0.0, max=1.0, default=0.0,
                                      update=_on_change, description="Atmosphere.Density")
    atmosphere_color: _color("Color", (0.78, 0.67, 0.42))
    atmosphere_haze: FloatProperty(name="Haze", min=0.0, max=10.0, default=0.0, update=_on_change)

    sky_mode: EnumProperty(name="Sky", items=SKY_ITEMS, default="GRADIENT", update=_on_change)
    sky_image: StringProperty(name="Sky Image", subtype="FILE_PATH", default="", update=_on_change)
    sky_strength: FloatProperty(name="Sky Strength", min=0.0, soft_max=5.0, default=1.0,
                                update=_on_change)
    celestial_bodies_shown: BoolProperty(name="CelestialBodiesShown", default=True,
                                         update=_on_change)
    sun_angular_size: FloatProperty(name="SunAngularSize", min=0.0, max=60.0, default=21.0,
                                    update=_on_change, description="Visual size of the sun disc")
    sun_strength_multiplier: FloatProperty(name="Sun Multiplier", min=0.0, soft_max=10.0,
                                           default=1.0, update=_on_change,
                                           description="Extra artistic control on top of Brightness")


# ---------------------------------------------------------------------------
# Helpers

def _smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def sun_direction_rbx(clock_time, latitude):
    """Unit vector toward the sun in Roblox space (approximation of
    Lighting:GetSunDirection())."""
    a = (clock_time - 6.0) / 24.0 * 2.0 * math.pi  # 0 at sunrise, pi/2 at noon
    v = Vector((math.cos(a), math.sin(a), 0.0))
    lat = math.radians(latitude)
    # Tilt the sun's path toward -Z by the latitude.
    y = v.y * math.cos(lat)
    z = -v.y * math.sin(lat)
    return Vector((v.x, y, z)).normalized()


def sun_direction_bl(clock_time, latitude):
    d = sun_direction_rbx(clock_time, latitude)
    return coords.vec_to_bl(d).normalized()


def _collection(scene):
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION_NAME)
    if coll.name not in scene.collection.children:
        try:
            scene.collection.children.link(coll)
        except RuntimeError:
            pass
    return coll


def _light_object(scene, name):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "LIGHT":
        light = bpy.data.lights.new(name, "SUN")
        obj = bpy.data.objects.new(name, light)
        _collection(scene).objects.link(obj)
    elif obj.name not in scene.objects:
        _collection(scene).objects.link(obj)
    if obj.data.type != "SUN":
        obj.data.type = "SUN"
    return obj


def _aim(obj, to_light):
    """Point a sun lamp so its light travels opposite to `to_light`."""
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(to_light)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = q
    obj.location = to_light * 20.0 * coords.stud_scale()


def _sky_colors(elev, props):
    day = _smoothstep(-0.02, 0.35, elev)
    dusk = max(0.0, 1.0 - abs(elev) / 0.25)
    night_z, night_h = (0.005, 0.008, 0.025), (0.02, 0.03, 0.06)
    day_z, day_h = (0.22, 0.45, 0.95), (0.68, 0.82, 1.0)
    zenith = _lerp(night_z, day_z, day)
    horizon = _lerp(night_h, day_h, day)
    horizon = _lerp(horizon, (1.0, 0.5, 0.25), dusk * 0.7)
    if props.atmosphere_density > 0.0:
        horizon = _lerp(horizon, tuple(props.atmosphere_color), min(1.0, props.atmosphere_density))
        zenith = _lerp(zenith, tuple(props.atmosphere_color),
                       min(1.0, props.atmosphere_density * 0.4 + props.atmosphere_haze * 0.03))
    return zenith, horizon


# ---------------------------------------------------------------------------
# World node tree

def _world(scene):
    world = bpy.data.worlds.get(WORLD_NAME)
    if world is None:
        world = bpy.data.worlds.new(WORLD_NAME)
    scene.world = world
    try:
        world.use_nodes = True
    except (AttributeError, TypeError):
        pass
    return world


def _structure_key(props, fog_on):
    return "%s|%s|%d" % (props.sky_mode, props.sky_image if props.sky_mode == "IMAGE" else "",
                         int(fog_on))


def _build_world(world, props, fog_on):
    nt = world.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links

    out = N.new("ShaderNodeOutputWorld")
    out.location = (900, 0)
    mix = N.new("ShaderNodeMixShader")
    mix.name = "RBX_Mix"
    mix.location = (650, 0)
    L.new(mix.outputs[0], out.inputs["Surface"])

    # Camera and reflection rays see the sky; diffuse lighting uses the
    # ambient colours.
    lp = N.new("ShaderNodeLightPath")
    lp.location = (150, 300)
    mx = N.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    mx.location = (400, 300)
    L.new(lp.outputs["Is Camera Ray"], mx.inputs[0])
    L.new(lp.outputs["Is Glossy Ray"], mx.inputs[1])
    L.new(mx.outputs[0], mix.inputs["Fac"])

    amb = N.new("ShaderNodeBackground")
    amb.name = "RBX_Ambient"
    amb.location = (400, 100)
    L.new(amb.outputs[0], mix.inputs[1])

    sky_bg = N.new("ShaderNodeBackground")
    sky_bg.name = "RBX_SkyBG"
    sky_bg.location = (400, -100)
    L.new(sky_bg.outputs[0], mix.inputs[2])

    if props.sky_mode == "GRADIENT":
        tc = N.new("ShaderNodeTexCoord")
        tc.location = (-900, 0)
        sep = N.new("ShaderNodeSeparateXYZ")
        sep.location = (-700, 100)
        L.new(tc.outputs["Generated"], sep.inputs[0])
        ramp = N.new("ShaderNodeValToRGB")
        ramp.name = "RBX_SkyRamp"
        ramp.location = (-500, 150)
        L.new(sep.outputs["Z"], ramp.inputs["Fac"])
        el = ramp.color_ramp.elements
        el[0].position = 0.0
        el[1].position = 0.6
        el.new(0.08)
        # Sun disc: dot(view, sun_dir) remapped to a soft disc
        dot = N.new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        dot.name = "RBX_SunDot"
        dot.location = (-500, -150)
        L.new(tc.outputs["Generated"], dot.inputs[0])
        rng = N.new("ShaderNodeMapRange")
        rng.name = "RBX_SunDisc"
        rng.location = (-300, -150)
        L.new(dot.outputs["Value"], rng.inputs["Value"])
        add = N.new("ShaderNodeMix")
        add.data_type = "RGBA"
        add.blend_type = "ADD"
        add.name = "RBX_SunAdd"
        add.location = (-50, 0)
        L.new(rng.outputs["Result"], add.inputs["Factor"])
        L.new(ramp.outputs["Color"], add.inputs["A"])
        L.new(add.outputs["Result"], sky_bg.inputs["Color"])
    elif props.sky_mode == "PHYSICAL":
        sky = N.new("ShaderNodeTexSky")
        sky.name = "RBX_PhysSky"
        sky.location = (-200, -100)
        L.new(sky.outputs["Color"], sky_bg.inputs["Color"])
    elif props.sky_mode == "IMAGE":
        env = N.new("ShaderNodeTexEnvironment")
        env.name = "RBX_SkyImage"
        env.location = (-200, -100)
        path = bpy.path.abspath(props.sky_image)
        if path:
            try:
                env.image = bpy.data.images.load(path, check_existing=True)
            except RuntimeError:
                pass
        L.new(env.outputs["Color"], sky_bg.inputs["Color"])
    # Fog/atmosphere are a volume box object (see _update_fog_volume), not a
    # world volume: an infinite world volume blocks all sunlight in Cycles.


def _update_world(world, props, scene, sun_dir_bl, fog_on, fog_density):
    nt = world.node_tree
    N = nt.nodes
    elev = sun_dir_bl.z
    day = _smoothstep(-0.05, 0.3, elev)

    amb = N.get("RBX_Ambient")
    if amb:
        # colours are linear now; x2 keeps Roblox's ambient brightness
        oa = Vector(props.outdoor_ambient) * (0.25 + 0.75 * day) * 2.0
        col = oa + Vector(props.ambient) * 0.5 + Vector(props.color_shift_bottom) * 0.3
        amb.inputs["Color"].default_value = (min(col.x, 1.0), min(col.y, 1.0), min(col.z, 1.0), 1.0)
        amb.inputs["Strength"].default_value = 0.4 + 0.6 * props.environment_diffuse_scale

    sky_bg = N.get("RBX_SkyBG")
    if sky_bg:
        sky_bg.inputs["Strength"].default_value = props.sky_strength * (
            0.3 + 0.7 * props.environment_specular_scale)
        if props.sky_mode == "NONE":
            sky_bg.inputs["Color"].default_value = (*props.fog_color, 1.0)

    ramp = N.get("RBX_SkyRamp")
    if ramp:
        zenith, horizon = _sky_colors(elev, props)
        ground = tuple(c * 0.35 for c in horizon)
        el = ramp.color_ramp.elements
        el[0].color = (*ground, 1.0)
        el[1].color = (*horizon, 1.0)
        el[2].color = (*zenith, 1.0)
        # elements are kept sorted: 0.0 ground, 0.08 horizon, 0.6 zenith
        el[0].position, el[1].position, el[2].position = 0.0, 0.08, 0.6
        el[1].color, el[2].color = (*horizon, 1.0), (*zenith, 1.0)
        if fog_on:
            # Distant sky blends into fog colour like in Roblox
            fog_mix = min(1.0, 300.0 / max(props.fog_end, 1.0))
            for e in el:
                e.color = (*_lerp(tuple(e.color)[:3], tuple(props.fog_color), fog_mix), 1.0)

    dot = N.get("RBX_SunDot")
    disc = N.get("RBX_SunDisc")
    if dot and disc:
        dot.inputs[1].default_value = sun_dir_bl
        half = math.radians(max(props.sun_angular_size, 0.5) / 2.0 * 0.25)
        disc.inputs["From Min"].default_value = math.cos(half * 2.0)
        disc.inputs["From Max"].default_value = math.cos(half)
        disc.inputs["To Max"].default_value = 3.0 if (props.celestial_bodies_shown and elev > -0.05) else 0.0
        add = N.get("RBX_SunAdd")
        if add:
            add.inputs["B"].default_value = (1.0, 0.95, 0.85, 1.0)

    phys = N.get("RBX_PhysSky")
    if phys:
        _configure_physical_sky(phys, sun_dir_bl, props)

FOG_NAME = "RBX Fog Volume"


def _update_fog_volume(scene, props, scale):
    """Roblox Fog and Atmosphere haze as a volume box around the scene. It is
    hidden from shadow and bounce rays, so (like Roblox) it fades distant
    things without darkening the sunlight on nearby ones."""
    density = 0.0
    half = 0.0
    if props.fog_end < 10000.0:
        dist = max(props.fog_end - props.fog_start * 0.5, 1.0) * scale
        density += 3.0 / dist  # ~95% fogged at FogEnd
        half = max(half, props.fog_end * 1.5)
    if props.atmosphere_density > 0.05:
        density += props.atmosphere_density * 0.002 / scale
        half = max(half, 1500.0)
    obj = bpy.data.objects.get(FOG_NAME)
    if density <= 0.0:
        if obj is not None:
            obj.hide_render = obj.hide_viewport = True
        return
    if obj is None:
        import bmesh
        me = bpy.data.meshes.new(FOG_NAME)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(FOG_NAME, me)
        _collection(scene).objects.link(obj)
        mat = bpy.data.materials.new(FOG_NAME)
        try:
            mat.use_nodes = True
        except (AttributeError, TypeError):
            pass
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        vol = nt.nodes.new("ShaderNodeVolumeScatter")
        vol.name = "RBX_Fog"
        vol.location = (-300, 0)
        nt.links.new(vol.outputs[0], out.inputs["Volume"])
        me.materials.append(mat)
        obj.display_type = "BOUNDS"
        obj.hide_select = True
        for attr in ("visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission"):
            if hasattr(obj, attr):
                setattr(obj, attr, False)
    elif obj.name not in scene.objects:
        _collection(scene).objects.link(obj)
    obj.hide_render = obj.hide_viewport = False
    obj.scale = (half * scale,) * 3
    mat = obj.data.materials[0] if obj.data.materials else None
    node = mat.node_tree.nodes.get("RBX_Fog") if mat else None
    if node is not None:
        node.inputs["Color"].default_value = (*props.fog_color, 1.0)
        node.inputs["Density"].default_value = density


def _configure_physical_sky(node, sun_dir_bl, props):
    for sky_type in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            node.sky_type = sky_type
            break
        except TypeError:
            continue
    elev = math.asin(max(-1.0, min(1.0, sun_dir_bl.z)))
    rot = math.atan2(sun_dir_bl.x, sun_dir_bl.y)
    for attr, val in (("sun_elevation", elev), ("sun_rotation", rot),
                      ("sun_disc", props.celestial_bodies_shown),
                      ("sun_size", math.radians(max(props.sun_angular_size, 0.5) * 0.05))):
        if hasattr(node, attr):
            try:
                setattr(node, attr, val)
            except (TypeError, ValueError):
                pass
    if hasattr(node, "sun_direction"):
        node.sun_direction = sun_dir_bl
    if hasattr(node, "air_density"):
        node.air_density = 1.0 + props.atmosphere_density * 4.0
    if hasattr(node, "dust_density"):
        node.dust_density = props.atmosphere_haze


# ---------------------------------------------------------------------------

def apply_lighting(scene):
    props = scene.rblx_lighting
    scale = coords.stud_scale(scene)
    to_sun = sun_direction_bl(props.clock_time, props.geographic_latitude)
    elev = to_sun.z

    # Sun
    sun = _light_object(scene, SUN_NAME)
    _aim(sun, to_sun)
    sun_vis = _smoothstep(-0.03, 0.12, elev)
    warm = _smoothstep(0.0, 0.4, elev)
    sun_col = Vector(_lerp((1.0, 0.55, 0.3), (1.0, 0.96, 0.9), warm)) + Vector(props.color_shift_top) * 0.5
    sun.data.color = tuple(min(c, 1.0) for c in sun_col)
    sun.data.energy = props.brightness * 1.6 * sun_vis * props.sun_strength_multiplier
    sun.data.angle = math.radians(0.5 + props.shadow_softness * 15.0)
    sun.data.use_shadow = props.global_shadows
    sun.hide_render = sun.hide_viewport = sun_vis <= 0.0

    # Moon (opposite the sun, takes over at night)
    moon = _light_object(scene, MOON_NAME)
    _aim(moon, -to_sun)
    moon_vis = _smoothstep(-0.03, 0.12, -elev)
    moon.data.color = (0.62, 0.72, 1.0)
    moon.data.energy = props.brightness * 0.12 * moon_vis * props.sun_strength_multiplier
    moon.data.angle = math.radians(0.5 + props.shadow_softness * 15.0)
    moon.data.use_shadow = props.global_shadows
    moon.hide_render = moon.hide_viewport = moon_vis <= 0.0

    # World
    fog_on = props.fog_end < 10000.0 or props.atmosphere_density > 0.05
    fog_density = 0.0
    if props.fog_end < 10000.0:
        dist = max(props.fog_end - props.fog_start * 0.5, 1.0) * scale
        fog_density += 2.5 / dist
    if props.atmosphere_density > 0.05:
        fog_density += props.atmosphere_density * 0.004 / scale

    world = _world(scene)
    key = "v2|" + _structure_key(props, fog_on)
    if world.get("rblx_key") != key or world.node_tree.nodes.get("RBX_Mix") is None:
        _build_world(world, props, fog_on)
        world["rblx_key"] = key
    _update_world(world, props, scene, to_sun, fog_on, fog_density)
    _update_fog_volume(scene, props, scale)

    scene.view_settings.exposure = props.exposure_compensation


# ---------------------------------------------------------------------------
# Presets and loading from Roblox files

PRESETS = {
    "DEFAULT": dict(clock_time=14.5, geographic_latitude=41.733, brightness=3.0,
                    ambient=(0.27, 0.27, 0.27), outdoor_ambient=(0.27, 0.27, 0.27),
                    shadow_softness=0.2, environment_diffuse_scale=1.0,
                    environment_specular_scale=1.0, fog_end=100000.0, atmosphere_density=0.3,
                    atmosphere_color=(0.78, 0.67, 0.42), atmosphere_haze=0.0,
                    exposure_compensation=0.0, color_shift_top=(0, 0, 0)),
    "CLASSIC": dict(clock_time=14.0, geographic_latitude=41.733, brightness=2.0,
                    ambient=(0.0, 0.0, 0.0), outdoor_ambient=(0.5, 0.5, 0.5),
                    shadow_softness=0.5, environment_diffuse_scale=0.0,
                    environment_specular_scale=0.0, fog_end=100000.0, atmosphere_density=0.0,
                    exposure_compensation=0.0, color_shift_top=(0, 0, 0)),
    "SUNSET": dict(clock_time=17.8, geographic_latitude=30.0, brightness=3.0,
                   ambient=(0.2, 0.12, 0.1), outdoor_ambient=(0.45, 0.32, 0.3),
                   shadow_softness=0.3, fog_end=100000.0, atmosphere_density=0.4,
                   atmosphere_color=(1.0, 0.6, 0.35), atmosphere_haze=1.5,
                   color_shift_top=(0.4, 0.2, 0.05), exposure_compensation=0.2),
    "NIGHT": dict(clock_time=0.0, geographic_latitude=41.733, brightness=2.0,
                  ambient=(0.05, 0.05, 0.1), outdoor_ambient=(0.12, 0.13, 0.22),
                  shadow_softness=0.3, fog_end=100000.0, atmosphere_density=0.0,
                  color_shift_top=(0, 0, 0), exposure_compensation=0.5),
    "FOGGY": dict(clock_time=12.0, brightness=1.5, ambient=(0.4, 0.4, 0.42),
                  outdoor_ambient=(0.6, 0.6, 0.62), shadow_softness=0.8,
                  fog_color=(0.75, 0.76, 0.78), fog_start=0.0, fog_end=250.0,
                  atmosphere_density=0.0, color_shift_top=(0, 0, 0)),
}

PRESET_ITEMS = [
    ("DEFAULT", "Baseplate Default", "Roughly Studio's default place lighting"),
    ("CLASSIC", "Classic", "Older Roblox look: no atmosphere, flat ambient"),
    ("SUNSET", "Sunset", ""),
    ("NIGHT", "Night", ""),
    ("FOGGY", "Foggy", ""),
]


# Preset colours above are written as Roblox (sRGB) values; store them linear.
_COLOR_KEYS = ("ambient", "outdoor_ambient", "color_shift_top", "color_shift_bottom", "fog_color",
               "atmosphere_color")
for _preset in PRESETS.values():
    for _k in _COLOR_KEYS:
        if _k in _preset:
            _preset[_k] = to_linear(_preset[_k])


def set_props(scene, values):
    global _applying
    props = scene.rblx_lighting
    _applying = True
    try:
        for k, v in values.items():
            if hasattr(props, k):
                setattr(props, k, v)
    finally:
        _applying = False
    apply_lighting(scene)


def _time_of_day(value):
    try:
        parts = [float(p) for p in str(value).split(":")]
        while len(parts) < 3:
            parts.append(0.0)
        return (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0) % 24.0
    except ValueError:
        return None


def values_from_instance(lighting):
    """Read a Roblox Lighting instance (rbx.Instance) into property values."""
    v = {}
    p = lighting.props

    def col(name, key):
        if name in p and isinstance(p[name], tuple) and len(p[name]) == 3:
            v[key] = to_linear(p[name])

    def num(name, key):
        if name in p and isinstance(p[name], (int, float)) and not isinstance(p[name], bool):
            v[key] = float(p[name])

    col("Ambient", "ambient")
    col("OutdoorAmbient", "outdoor_ambient")
    col("ColorShift_Top", "color_shift_top")
    col("ColorShift_Bottom", "color_shift_bottom")
    col("FogColor", "fog_color")
    num("Brightness", "brightness")
    num("GeographicLatitude", "geographic_latitude")
    num("EnvironmentDiffuseScale", "environment_diffuse_scale")
    num("EnvironmentSpecularScale", "environment_specular_scale")
    num("ExposureCompensation", "exposure_compensation")
    num("FogStart", "fog_start")
    num("FogEnd", "fog_end")
    num("ShadowSoftness", "shadow_softness")
    num("ClockTime", "clock_time")
    if "TimeOfDay" in p:
        t = _time_of_day(p["TimeOfDay"])
        if t is not None:
            v["clock_time"] = t
    if isinstance(p.get("GlobalShadows"), bool):
        v["global_shadows"] = p["GlobalShadows"]

    v["atmosphere_density"] = 0.0
    for child in lighting.children:
        cp = child.props
        if child.class_name == "Atmosphere":
            if isinstance(cp.get("Density"), float):
                v["atmosphere_density"] = cp["Density"]
            if isinstance(cp.get("Haze"), float):
                v["atmosphere_haze"] = cp["Haze"]
            if isinstance(cp.get("Color"), tuple):
                v["atmosphere_color"] = to_linear(cp["Color"])
        elif child.class_name == "Sky":
            if isinstance(cp.get("CelestialBodiesShown"), bool):
                v["celestial_bodies_shown"] = cp["CelestialBodiesShown"]
            if isinstance(cp.get("SunAngularSize"), float):
                v["sun_angular_size"] = cp["SunAngularSize"]
    return v


CLASSES = (RBLX_LightingProps,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.rblx_lighting = bpy.props.PointerProperty(type=RBLX_LightingProps)


def unregister():
    del bpy.types.Scene.rblx_lighting
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
