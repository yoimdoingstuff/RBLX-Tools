"""Export Roblox objects from Blender back to a Roblox model file (.rbxmx).

Parts (Part / WedgePart / CornerWedgePart / TrussPart / MeshPart with its
MeshId), Models and Folders, Decals and Textures with asset ids, lights,
particle emitters and character joints (Motor6D from the rig's C0/C1) are
written so Studio can insert the file (File > Insert from file, or drag it
in). Geometry that only exists in Blender (your own meshes, rebuilt unions)
can't be uploaded through a model file: those are written as blocks of the
same size and listed in the report; export them as .fbx/.obj and import them
with Studio's 3D Importer instead."""

import math

from mathutils import Matrix

from . import animio, coords, effects
from .rbx import enums
from .rbx.color import to_srgb
from .rbx.writer import Item, write_file

MATERIAL_IDS = {v: k for k, v in enums.MATERIALS.items()}
SHAPE_IDS = {"BALL": 0, "BLOCK": 1, "CYLINDER": 2}
FACE_IDS = {v: k for k, v in enums.NORMAL_IDS.items()}
PART_CLASS = {"WEDGE": "WedgePart", "CORNER_WEDGE": "CornerWedgePart", "TRUSS": "TrussPart"}


def _asset(source):
    s = (source or "").strip()
    if not s:
        return ""
    if s.isdigit():
        return "rbxassetid://" + s
    if s.startswith(("rbxassetid://", "rbxasset://", "http://", "https://")):
        return s
    return ""  # a file on disk: Roblox can't use it until it's uploaded


def _cframe(mw, scale):
    pos, rot = coords.matrix_to_rbx(mw, scale)
    return pos, [rot[i][j] for i in range(3) for j in range(3)]


class Exporter:
    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.scale = coords.stud_scale(self.scene)
        self.notes = []
        self.items = {}   # object -> Item
        self.count = 0

    # -------------------------------------------------------------------
    def part(self, obj):
        r = obj.rblx
        shape = r.shape
        notes = self.notes
        if shape == "MESH" and r.mesh_id and _asset(r.mesh_id):
            it = Item("MeshPart", obj.name)
            it.prop("Content", "MeshId", _asset(r.mesh_id))
            it.prop("Vector3", "InitialSize", tuple(r.initial_size))
            uv = next((l for l in r.layers if l.mapping == "UV" and l.kind == "TextureID"), None)
            if uv is not None and _asset(uv.source):
                it.prop("Content", "TextureID", _asset(uv.source))
        elif shape in ("MESH", "UNION") or (r.kind == "NONE"):
            it = Item("Part", obj.name)
            it.prop("token", "shape", 1)
            notes.append("%s: geometry made in Blender can't go in a model file; written as a block "
                         "(export it as .fbx and use Studio's 3D Importer)" % obj.name)
        else:
            it = Item(PART_CLASS.get(shape, "Part"), obj.name)
            if it.class_name == "Part":
                it.prop("token", "shape", SHAPE_IDS.get(shape, 1))
        size = tuple(r.size) if r.kind == "PART" else coords.size_to_rbx(obj.dimensions / self.scale)
        it.prop("CoordinateFrame", "CFrame", _cframe(obj.matrix_world, self.scale))
        it.prop("Vector3", "size", size)
        it.prop("Color3uint8", "Color3uint8", to_srgb(tuple(r.color)))
        it.prop("token", "Material", MATERIAL_IDS.get(r.material, 256))
        if r.material_variant:
            it.prop("string", "MaterialVariantSerialized", r.material_variant)
        it.prop("float", "Transparency", r.transparency)
        it.prop("float", "Reflectance", r.reflectance)
        for name, attr in (("Anchored", "anchored"), ("CanCollide", "can_collide"),
                           ("CanTouch", "can_touch"), ("CanQuery", "can_query"),
                           ("Locked", "locked"), ("Massless", "massless"),
                           ("CastShadow", "cast_shadow")):
            it.prop("bool", name, getattr(r, attr))
        for layer in r.layers:
            self.layer(it, layer)
        return it

    def layer(self, part_item, layer):
        content = _asset(layer.source)
        if not content:
            if layer.image is not None and layer.mapping in ("FACE", "TILED"):
                self.notes.append("%s: texture '%s' isn't a Roblox asset yet; upload it and set the "
                                  "id to export it" % (part_item.props[0][2], layer.name))
            return
        if layer.mapping == "FACE":
            d = part_item.add(Item("Decal", layer.name))
            d.prop("Content", "Texture", content)
            d.prop("token", "Face", FACE_IDS.get(layer.face, 5))
            d.prop("Color3", "Color3", to_srgb(tuple(layer.color)))
            d.prop("float", "Transparency", layer.transparency)
        elif layer.mapping == "TILED":
            t = part_item.add(Item("Texture", layer.name))
            t.prop("Content", "Texture", content)
            t.prop("token", "Face", FACE_IDS.get(layer.face, 5))
            t.prop("Color3", "Color3", to_srgb(tuple(layer.color)))
            t.prop("float", "Transparency", layer.transparency)
            t.prop("float", "StudsPerTileU", layer.studs_per_tile_u)
            t.prop("float", "StudsPerTileV", layer.studs_per_tile_v)
            t.prop("float", "OffsetStudsU", layer.offset_studs_u)
            t.prop("float", "OffsetStudsV", layer.offset_studs_v)

    def light(self, obj):
        cls = {"POINT": "PointLight", "SPOT": "SpotLight", "AREA": "SurfaceLight"}.get(
            obj.data.type, "PointLight")
        it = Item(cls, obj.name)
        it.prop("Color3", "Color", to_srgb(tuple(obj.data.color)))
        it.prop("float", "Brightness", obj.rblx.light_brightness)
        it.prop("float", "Range", obj.rblx.light_range)
        it.prop("bool", "Shadows", obj.data.use_shadow)
        if obj.data.type == "SPOT":
            it.prop("float", "Angle", math.degrees(obj.data.spot_size))
        return it

    def emitter(self, obj):
        mod, _ng, size_node, mat, ramp, tcurve = effects.emitter_parts(obj)
        if mod is None:
            return None
        ids = effects._input_ids(mod)

        def g(name, default=0.0):
            return effects.get_input(mod, ids[name]) if name in ids else default

        it = Item("ParticleEmitter", obj.name)
        it.prop("bool", "Enabled", bool(g("Enabled", True)))
        it.prop("float", "Rate", g("Rate", 20.0))
        it.prop("NumberRange", "Lifetime", (g("Lifetime Min"), g("Lifetime Max")))
        it.prop("NumberRange", "Speed", (g("Speed Min") / self.scale, g("Speed Max") / self.scale))
        it.prop("NumberRange", "Rotation", (g("Rotation Min"), g("Rotation Max")))
        it.prop("NumberRange", "RotSpeed", (g("RotSpeed Min"), g("RotSpeed Max")))
        it.prop("float", "Drag", g("Drag"))
        acc = g("Acceleration", (0.0, 0.0, 0.0))
        it.prop("Vector3", "Acceleration", coords.vec_to_rbx(acc, self.scale))
        it.prop("Vector2", "SpreadAngle", (g("Spread X"), g("Spread Y")))
        size_max = g("Size", 1.0) / self.scale
        if size_node is not None:
            pts = size_node.mapping.curves[0].points
            it.prop("NumberSequence", "Size", [(p.location[0], p.location[1] * size_max, 0.0) for p in pts])
        if tcurve is not None:
            pts = tcurve.mapping.curves[0].points
            it.prop("NumberSequence", "Transparency", [(p.location[0], p.location[1], 0.0) for p in pts])
        if ramp is not None:
            els = ramp.color_ramp.elements
            it.prop("ColorSequence", "Color",
                    [(e.position, *to_srgb(tuple(e.color[:3])), 0.0) for e in els][:20])
        tex = _asset(obj.rblx.texture_id)
        if tex:
            it.prop("Content", "Texture", tex)
        em = mat.node_tree.nodes.get("RBX Emission") if mat else None
        if em is not None:
            it.prop("float", "LightEmission", max(0.0, (em.inputs["Strength"].default_value - 1.0) / 2.0))
        return it

    def container(self, obj):
        cls = obj.rblx.class_name if obj.rblx.class_name in ("Model", "Folder", "Accessory", "Tool") \
            else "Model"
        return Item(cls, obj.name)

    # -------------------------------------------------------------------
    def build(self, obj, parent_item, out):
        r = obj.rblx
        it = None
        if r.class_name in ("Terrain", "Clouds"):
            return  # voxel terrain, its water and the cloud layer aren't parts
        if r.kind == "PART" or (obj.type == "MESH" and r.kind == "NONE"):
            it = self.part(obj)
        elif r.kind == "RIG":
            # the rig's joints are written as Motor6Ds on the parts; the model gets a Humanoid
            if parent_item is not None and not any(c.class_name == "Humanoid"
                                                   for c in parent_item.children):
                hum = parent_item.add(Item("Humanoid", "Humanoid"))
                hum.prop("token", "RigType", 1 if len(obj.data.bones) > 10 else 0)
        elif r.kind == "MODEL" or (obj.type == "EMPTY" and r.kind == "NONE"):
            it = self.container(obj)
        elif r.kind == "LIGHT" and obj.type == "LIGHT":
            it = self.light(obj)
        elif r.kind == "EFFECT" and obj.modifiers.get("RBX Particles"):
            it = self.emitter(obj)
        if it is not None:
            self.items[obj] = it
            self.count += 1
            (parent_item.add(it) if parent_item is not None else out.append(it))
        # lights and emitters belong inside their part in Roblox
        target = it if it is not None and it.class_name not in ("PointLight", "SpotLight",
                                                                "SurfaceLight", "ParticleEmitter") \
            else parent_item
        for c in obj.children:
            self.build(c, target, out)

    def joints(self):
        """Motor6D joints for exported rigs, from the C0/C1 stored on the bones."""
        for obj, it in list(self.items.items()):
            if obj.parent is None or obj.parent.type != "ARMATURE" or obj.parent_type != "BONE":
                continue
            rig = obj.parent
            bone = rig.data.bones.get(obj.parent_bone)
            if bone is None or "rbx_c0" not in bone:
                continue
            part0 = next((o for o, i in self.items.items() if o.name == bone.get("rbx_part0") or
                          (o.parent == rig and o.parent_bone == bone.get("rbx_part0"))), None)
            if part0 is None:
                continue
            c0, c1 = list(bone["rbx_c0"]), list(bone["rbx_c1"])
            m = it.add(Item("Motor6D", bone.get("rbx_joint", obj.name)))
            m.prop("CoordinateFrame", "C0", (c0[:3], c0[3:12]))
            m.prop("CoordinateFrame", "C1", (c1[:3], c1[3:12]))
            m.prop("Ref", "Part0", self.items[part0])
            m.prop("Ref", "Part1", it)


def export_objects(context, objects, path, include_animation=True):
    exp = Exporter(context)
    roots = []
    sel = set(objects)
    for o in objects:
        p = o.parent
        while p is not None and p not in sel:
            p = p.parent
        if p is None:
            roots.append(o)
    out = []
    for o in roots:
        exp.build(o, None, out)
    exp.joints()
    if include_animation:
        for o in sel:
            if o.type == "ARMATURE" and o.animation_data and o.animation_data.action:
                seq = animio.sequence_items(context, o)
                if seq is not None:
                    holder = out[0] if out else None
                    (holder.add(seq) if holder is not None else out.append(seq))
    write_file(path, out)
    return exp.count, exp.notes
