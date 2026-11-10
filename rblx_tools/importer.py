"""Imports Roblox models/places (.rbxm, .rbxmx, .rbxl, .rbxlx) into Blender."""

import math
import os

import bpy
from mathutils import Matrix, Vector

from . import assets, coords, geometry, lighting, materials
from .props import suspend_updates
from .rbx import CFrame, enums, load_file
from .rbx import mesh as rbxmesh

PART_CLASSES = {
    "Part", "MeshPart", "WedgePart", "CornerWedgePart", "TrussPart", "SpawnLocation", "Seat",
    "VehicleSeat", "SkateboardPlatform", "UnionOperation", "IntersectOperation",
    "PartOperation", "FlagStand", "Platform",
}
UNION_CLASSES = {"UnionOperation", "IntersectOperation", "PartOperation"}
CONTAINER_CLASSES = {
    "Model", "Folder", "Workspace", "Accessory", "Accoutrement", "Hat", "Tool", "HopperBin",
    "WorldModel", "Configuration", "Actor",
}
PART_MODIFIERS = {"SpecialMesh", "FileMesh", "BlockMesh", "CylinderMesh", "SurfaceAppearance"}
SKIP_CLASSES = {"Terrain", "Camera", "NegateOperation"}
SERVICE_CLASSES = {
    "Workspace", "Lighting", "ReplicatedStorage", "ServerStorage", "ServerScriptService",
    "StarterGui", "StarterPack", "StarterPlayer", "Players", "SoundService", "Teams", "Chat",
    "ReplicatedFirst", "MaterialService", "TextChatService",
}
STORAGE_SERVICES = ("ReplicatedStorage", "ServerStorage", "StarterPack")

MESH_TYPE_SHAPES = {
    "Wedge": "WEDGE", "Sphere": "BALL", "Cylinder": "CYLINDER", "Brick": "BLOCK",
    "CornerWedge": "CORNER_WEDGE", "Torso": "BLOCK", "Head": "BLOCK",
}


class ImportOptions:
    def __init__(self, stud_scale=1.0, import_lighting=True, import_lights=True,
                 import_attachments=False, import_storage=False, asset_folder="",
                 hide_invisible=True):
        self.stud_scale = stud_scale
        self.import_lighting = import_lighting
        self.import_lights = import_lights
        self.import_attachments = import_attachments
        self.import_storage = import_storage
        self.asset_folder = asset_folder
        self.hide_invisible = hide_invisible


class ImportReport:
    def __init__(self):
        self.counts = {}
        self.missing = {}   # asset content -> [object names]
        self.warnings = []

    def count(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1

    def miss(self, content, who):
        self.missing.setdefault(content, []).append(who)

    def summary(self):
        parts = ", ".join("%d %s" % (v, k) for k, v in sorted(self.counts.items()))
        s = "Imported " + (parts or "nothing")
        if self.missing:
            s += "; %d asset(s) not found locally" % len(self.missing)
        return s

    def write_text(self, title):
        lines = ["Roblox import report: " + title, "", self.summary(), ""]
        if self.missing:
            lines.append("Missing assets (put files named by their id in your Asset Folder,")
            lines.append("then use Roblox > Assets > Reload Missing Assets):")
            for content, who in sorted(self.missing.items()):
                lines.append("  %s  (used by %d: %s)" % (content, len(who), ", ".join(who[:5])))
            lines.append("")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend("  " + w for w in self.warnings[:500])
        txt = bpy.data.texts.get("RBX Import Report") or bpy.data.texts.new("RBX Import Report")
        txt.clear()
        txt.write("\n".join(lines))
        return txt


class Importer:
    def __init__(self, context, options):
        self.context = context
        self.scene = context.scene
        self.opts = options
        self.scale = options.stud_scale
        self.resolver = assets.default_resolver(options.asset_folder)
        self.report = ImportReport()
        self.world = {}           # object -> world matrix we assigned
        self.mesh_cache = {}
        self.mesh_data_cache = {}
        self._has_parts = {}
        self.collection = None

    # ------------------------------------------------------------------
    def run(self, path):
        doc = load_file(path, self.report.warnings)
        title = os.path.splitext(os.path.basename(path))[0]

        self.scene.rblx.stud_scale = self.scale
        self.collection = bpy.data.collections.new(title)
        self.scene.collection.children.link(self.collection)

        is_place = any(r.class_name in SERVICE_CLASSES for r in doc.roots)
        lighting_inst = None
        with suspend_updates():
            if is_place:
                ws = doc.find_service("Workspace")
                if ws is not None:
                    for child in ws.children:
                        self.build(child, None)
                if self.opts.import_storage:
                    for svc in STORAGE_SERVICES:
                        inst = doc.find_service(svc)
                        if inst is not None and self.has_parts(inst):
                            holder = self.make_empty(inst.name, None, Matrix.Identity(4),
                                                     "MODEL", inst.class_name)
                            for child in inst.children:
                                self.build(child, holder)
                lighting_inst = doc.find_service("Lighting")
            else:
                for root in doc.roots:
                    if root.class_name == "Lighting":
                        lighting_inst = root
                    else:
                        self.build(root, None)

        if lighting_inst is not None and self.opts.import_lighting:
            lighting.set_props(self.scene, lighting.values_from_instance(lighting_inst))
            self.report.count("lighting settings")

        self.report.write_text(title)
        return self.report

    # ------------------------------------------------------------------
    def has_parts(self, inst):
        key = id(inst)
        if key not in self._has_parts:
            self._has_parts[key] = inst.class_name in PART_CLASSES or any(
                self.has_parts(c) for c in inst.children)
        return self._has_parts[key]

    def place(self, obj, parent, world):
        obj.parent = parent
        if parent is not None:
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = self.world[parent].inverted_safe() @ world
        else:
            obj.matrix_basis = world
        self.world[obj] = world

    def build(self, inst, parent_obj):
        cls = inst.class_name
        if cls in SKIP_CLASSES:
            return
        if cls in PART_CLASSES:
            obj = self.make_part(inst, parent_obj)
            for c in inst.children:
                self.build(c, obj)
        elif cls in CONTAINER_CLASSES:
            if not self.has_parts(inst):
                return
            obj = self.make_model(inst, parent_obj)
            for c in inst.children:
                self.build(c, obj)
        elif cls in ("Decal", "Texture"):
            if parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_decal(inst, parent_obj)
        elif cls in ("PointLight", "SpotLight", "SurfaceLight"):
            if self.opts.import_lights and parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_light(inst, parent_obj)
        elif cls == "Attachment":
            if self.opts.import_attachments and parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_attachment(inst, parent_obj)
        elif cls in PART_MODIFIERS:
            pass  # consumed by make_part
        elif self.has_parts(inst):
            # Unknown container (e.g. parts inside a script or value): keep going
            for c in inst.children:
                self.build(c, parent_obj)

    # ------------------------------------------------------------------
    def make_empty(self, name, parent, world, kind="MODEL", class_name="Model"):
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = self.scale
        self.collection.objects.link(obj)
        self.place(obj, parent, world)
        obj.rblx.kind = kind
        obj.rblx.class_name = class_name
        return obj

    def make_model(self, inst, parent_obj):
        pivot = inst.get("WorldPivotData")
        if not isinstance(pivot, CFrame):
            primary = inst.get("PrimaryPart")
            if primary is not None and not isinstance(primary, (str, bytes)) and \
                    isinstance(primary.get("CFrame"), CFrame):
                pivot = primary.props["CFrame"]
        if isinstance(pivot, CFrame):
            world = coords.cframe_to_matrix(pivot, self.scale)
        else:
            pts = [d.props["CFrame"].pos for d in inst.descendants()
                   if d.class_name in PART_CLASSES and isinstance(d.props.get("CFrame"), CFrame)]
            world = Matrix.Identity(4)
            if pts:
                c = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
                world.translation = coords.vec_to_bl(c, self.scale)
        self.report.count("models")
        return self.make_empty(inst.name, parent_obj, world, "MODEL", inst.class_name)

    # ------------------------------------------------------------------
    def load_mesh(self, content, who):
        if not content:
            return None
        if content in self.mesh_data_cache:
            return self.mesh_data_cache[content]
        md = None
        path = self.resolver.resolve(content)
        if path is None:
            self.report.miss(content, who)
        else:
            try:
                with open(path, "rb") as f:
                    md = rbxmesh.read_mesh(f.read())
            except (OSError, rbxmesh.MeshFormatError) as ex:
                self.report.warnings.append("%s: %s (%s)" % (who, ex, path))
                self.report.miss(content, who)
        self.mesh_data_cache[content] = md
        return md

    def mesh_datablock(self, md, mesh_id, name, fit, initial_size, mesh_scale, mesh_offset):
        return mesh_datablock_for(md, mesh_id, name, self.scale, fit, initial_size,
                                  mesh_scale, mesh_offset, self.mesh_cache)

    def make_part(self, inst, parent_obj):
        cls = inst.class_name
        name = inst.name
        size = tuple(inst.get("size", "Size", default=(4.0, 1.0, 2.0)))
        cf = inst.get("CFrame")
        if not isinstance(cf, CFrame):
            cf = CFrame()

        color = inst.get("Color3uint8", "Color")
        if not (isinstance(color, tuple) and len(color) == 3):
            bc = inst.get("BrickColor", "brickColor", default=194)
            color = enums.brick_color(bc if isinstance(bc, int) else 194)
        transparency = float(inst.get("Transparency", default=0.0) or 0.0)
        reflectance = float(inst.get("Reflectance", default=0.0) or 0.0)
        mat_token = inst.get("Material", default=256)
        material_name = enums.MATERIALS.get(mat_token, "Plastic")

        shape = "BLOCK"
        initial_size = size
        geom_size = size
        me = None
        mesh_id = ""
        texture_id = ""
        placeholder = False
        mesh_fit = True
        mscale = (1.0, 1.0, 1.0)
        moffset = (0.0, 0.0, 0.0)

        special = inst.find_first_child_of_class("SpecialMesh", "FileMesh", "BlockMesh", "CylinderMesh")
        surface = inst.find_first_child_of_class("SurfaceAppearance")

        if cls == "MeshPart":
            mesh_id = inst.get("MeshId", "MeshID", "MeshContent", default="") or ""
            texture_id = inst.get("TextureID", "TextureId", "TextureContent", default="") or ""
            initial_size = tuple(inst.get("InitialSize", default=size))
            shape = "MESH"
            md = self.load_mesh(mesh_id, name)
            if md is not None and md.positions:
                me = self.mesh_datablock(md, mesh_id, name, True, initial_size, None, None)
            else:
                placeholder = True
        elif cls in UNION_CLASSES:
            shape = "UNION"
            placeholder = True
            self.report.warnings.append("%s: unions can't be decoded yet; imported as a box" % name)
        else:
            if cls == "WedgePart":
                shape = "WEDGE"
            elif cls == "CornerWedgePart":
                shape = "CORNER_WEDGE"
            elif cls == "TrussPart":
                shape = "TRUSS"
            else:
                shape = enums.PART_SHAPES.get(inst.get("shape", "Shape", default=1), "BLOCK")

            if special is not None:
                mscale = tuple(special.get("Scale", default=(1.0, 1.0, 1.0)))
                moffset = tuple(special.get("Offset", default=(0.0, 0.0, 0.0)))
                if special.class_name in ("SpecialMesh", "FileMesh"):
                    mtype = enums.MESH_TYPES.get(special.get("MeshType", default=5), "FileMesh")
                    if special.class_name == "FileMesh":
                        mtype = "FileMesh"
                else:
                    mtype = "Brick" if special.class_name == "BlockMesh" else "Cylinder"

                if mtype == "FileMesh":
                    mesh_id = special.get("MeshId", "MeshID", default="") or ""
                    texture_id = special.get("TextureId", "TextureID", default="") or ""
                    md = self.load_mesh(mesh_id, name)
                    shape = "MESH"
                    initial_size = size
                    mesh_fit = False
                    if md is not None and md.positions:
                        me = self.mesh_datablock(md, mesh_id, name, False, initial_size,
                                                 mscale, moffset)
                    else:
                        placeholder = True
                else:
                    shape = MESH_TYPE_SHAPES.get(mtype, "BLOCK")
                    geom_size = tuple(s * m for s, m in zip(size, mscale))

        # Object and geometry
        obj = bpy.data.objects.new(name, me if me is not None else bpy.data.meshes.new(name))
        self.collection.objects.link(obj)
        if me is None:
            build_size = initial_size if placeholder else geom_size
            geometry.build_primitive(obj.data, "BLOCK" if placeholder else shape,
                                     tuple(s * self.scale for s in build_size))

        world = coords.cframe_to_matrix(cf, self.scale)
        if shape in ("MESH", "UNION"):
            ratio = [(s / i) if i > 1e-6 else 1.0 for s, i in zip(size, initial_size)]
            world = world @ Matrix.Diagonal((*coords.size_to_bl(ratio), 1.0))
        self.place(obj, parent_obj, world)

        r = obj.rblx
        r.kind = "PART"
        r.class_name = cls
        r.shape = shape
        r.size = geom_size
        r.initial_size = initial_size
        r.color = color
        r.transparency = min(max(transparency, 0.0), 1.0)
        r.reflectance = min(max(reflectance, 0.0), 1.0)
        r.material = material_name
        r.cast_shadow = bool(inst.get("CastShadow", default=True))
        r.anchored = bool(inst.get("Anchored", default=True))
        r.can_collide = bool(inst.get("CanCollide", default=True))
        r.can_touch = bool(inst.get("CanTouch", default=True))
        r.can_query = bool(inst.get("CanQuery", default=True))
        r.locked = bool(inst.get("Locked", default=False))
        r.massless = bool(inst.get("Massless", default=False))
        r.mesh_id = mesh_id if isinstance(mesh_id, str) else ""
        r.mesh_fit = mesh_fit
        r.mesh_scale = mscale
        r.mesh_offset = moffset
        r.texture_id = texture_id if isinstance(texture_id, str) else ""
        r.asset_missing = placeholder and bool(mesh_id)

        obj.color = (*color, 1.0 - r.transparency)
        obj.visible_shadow = r.cast_shadow
        if self.opts.hide_invisible and r.transparency >= 0.999:
            obj.display_type = "WIRE"

        # Material
        if surface is not None:
            self.apply_surface_appearance(obj, surface)
        elif r.texture_id:
            if not materials.refresh_texture(obj, self.resolver):
                self.report.miss(r.texture_id, name)
        else:
            materials.assign(obj, materials.part_material(material_name))

        self.report.count("parts")
        return obj

    def apply_surface_appearance(self, obj, sa):
        roles = {"color": "ColorMap", "normal": "NormalMap", "roughness": "RoughnessMap",
                 "metalness": "MetalnessMap"}
        maps = {}
        ids = []
        for role, prop in roles.items():
            content = sa.get(prop, prop.replace("Map", "MapContent"), default="") or ""
            if not isinstance(content, str) or not content:
                continue
            ids.append(content)
            path = self.resolver.resolve(content)
            img = materials.load_image(path, non_color=(role != "color")) if path else None
            if img:
                maps[role] = img
            else:
                self.report.miss(content, obj.name)
        if not maps:
            materials.assign(obj, materials.part_material(obj.rblx.material))
            return
        alpha_mode = sa.get("AlphaMode", default=0)
        tint = sa.get("Color", default=(1.0, 1.0, 1.0))
        if not isinstance(tint, tuple):
            tint = (1.0, 1.0, 1.0)
        key = "%s %08x" % (sa.name, abs(hash(tuple(ids))) & 0xFFFFFFFF)
        obj.rblx.material_mode = "SURFACE"
        materials.assign(obj, materials.surface_appearance_material(
            key, maps, alpha_mode if isinstance(alpha_mode, int) else 0, tint))

    # ------------------------------------------------------------------
    def make_decal(self, inst, part_obj):
        kind = "TEXTURE" if inst.class_name == "Texture" else "DECAL"
        obj = bpy.data.objects.new(inst.name, bpy.data.meshes.new(inst.name))
        self.collection.objects.link(obj)
        self.place(obj, part_obj, self.world[part_obj])
        r = obj.rblx
        r.kind = kind
        r.class_name = inst.class_name
        r.face = enums.NORMAL_IDS.get(inst.get("Face", default=5), "FRONT")
        color = inst.get("Color3", "Color")
        r.color = color if isinstance(color, tuple) and len(color) == 3 else (1.0, 1.0, 1.0)
        r.transparency = min(max(float(inst.get("Transparency", default=0.0) or 0.0), 0.0), 1.0)
        if kind == "TEXTURE":
            r.studs_per_tile_u = float(inst.get("StudsPerTileU", default=2.0))
            r.studs_per_tile_v = float(inst.get("StudsPerTileV", default=2.0))
            r.offset_studs_u = float(inst.get("OffsetStudsU", default=0.0))
            r.offset_studs_v = float(inst.get("OffsetStudsV", default=0.0))
        tex = inst.get("Texture", "TextureContent", "ColorMap", default="")
        r.texture_id = tex if isinstance(tex, str) else ""
        obj.color = (*r.color, 1.0 - r.transparency)
        obj.visible_shadow = False
        geometry.rebuild_decal(obj)
        if not materials.refresh_texture(obj, self.resolver):
            self.report.miss(r.texture_id, inst.name)
        self.report.count("decals")
        return obj

    def make_light(self, inst, part_obj):
        cls = inst.class_name
        brightness = float(inst.get("Brightness", default=1.0))
        rng = float(inst.get("Range", default=8.0))
        color = inst.get("Color", default=(1.0, 1.0, 1.0))
        color = color if isinstance(color, tuple) else (1.0, 1.0, 1.0)
        face = enums.NORMAL_IDS.get(inst.get("Face", default=5), "FRONT")
        angle = float(inst.get("Angle", default=90.0))

        if cls == "PointLight":
            light = bpy.data.lights.new(inst.name, "POINT")
        elif cls == "SpotLight":
            light = bpy.data.lights.new(inst.name, "SPOT")
            light.spot_size = max(0.01, min(3.1, math.radians(angle)))
            light.spot_blend = 0.3
        else:
            light = bpy.data.lights.new(inst.name, "AREA")
            light.shape = "RECTANGLE"
            box = geometry.part_box_size(part_obj)
            n = coords.FACE_NORMALS[face]
            dims = [b * self.scale for b, a in zip(box, n) if abs(a) < 0.5]
            light.size, light.size_y = (dims + [1.0, 1.0])[:2]
            if hasattr(light, "spread"):
                light.spread = max(0.02, min(3.14, math.radians(angle)))
        light.color = color
        light.energy = brightness * (rng * self.scale) ** 2 * 4.0
        light.use_shadow = bool(inst.get("Shadows", default=False))
        for attr, val in (("use_custom_distance", True), ("cutoff_distance", rng * self.scale)):
            if hasattr(light, attr):
                setattr(light, attr, val)

        obj = bpy.data.objects.new(inst.name, light)
        self.collection.objects.link(obj)
        part_world = self.world[part_obj]
        loc, rot, _ = part_world.decompose()
        base = Matrix.LocRotScale(loc, rot, None)
        if cls != "PointLight":
            n_bl = coords.vec_to_bl(coords.FACE_NORMALS[face])
            q = Vector((0.0, 0.0, -1.0)).rotation_difference(n_bl)
            base = base @ q.to_matrix().to_4x4()
        self.place(obj, part_obj, base)
        obj.rblx.kind = "LIGHT"
        obj.rblx.class_name = cls
        obj.rblx.light_range = min(rng, 60.0)
        obj.rblx.light_brightness = brightness
        obj.hide_render = obj.hide_viewport = not inst.get("Enabled", default=True)
        self.report.count("lights")
        return obj

    def make_attachment(self, inst, part_obj):
        cf = inst.get("CFrame")
        if not isinstance(cf, CFrame):
            cf = CFrame()
        loc, rot, _ = self.world[part_obj].decompose()
        world = Matrix.LocRotScale(loc, rot, None) @ coords.cframe_to_matrix(cf, self.scale)
        obj = self.make_empty(inst.name, part_obj, world, "ATTACHMENT", "Attachment")
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.15 * self.scale
        self.report.count("attachments")
        return obj


def mesh_datablock_for(md, mesh_id, name, scale, fit, initial_size, mesh_scale, mesh_offset,
                       cache=None):
    """Mesh datablock for a parsed .mesh. `fit` (MeshPart) centres the mesh
    and fits it to InitialSize; otherwise (SpecialMesh) Scale/Offset apply."""
    if fit:
        lo, hi = md.bounds()
        ext = [h - l for l, h in zip(lo, hi)]
        center = [(l + h) / 2.0 for l, h in zip(lo, hi)]
        factor = [(i / e) if e > 1e-6 else 1.0 for i, e in zip(initial_size, ext)]
        offset = [-c * f for c, f in zip(center, factor)]
        key = ("mp", mesh_id, tuple(round(v, 4) for v in initial_size), scale)
    else:
        factor = tuple(mesh_scale)
        offset = tuple(mesh_offset)
        key = ("sm", mesh_id, tuple(round(v, 4) for v in factor),
               tuple(round(v, 4) for v in offset), scale)
    if cache is not None and key in cache:
        return cache[key]
    me = bpy.data.meshes.new("RBX Mesh " + name)
    geometry.build_mesh_from_rbx(me, md, scale, factor, offset)
    if cache is not None:
        cache[key] = me
    return me


def reload_part_mesh(obj, resolver, cache=None):
    """Try again to load a missing mesh for a MESH part. Returns True on success."""
    r = obj.rblx
    if r.kind != "PART" or r.shape != "MESH" or not r.mesh_id:
        return False
    path = resolver.resolve(r.mesh_id)
    if not path:
        return False
    try:
        with open(path, "rb") as f:
            md = rbxmesh.read_mesh(f.read())
    except (OSError, rbxmesh.MeshFormatError):
        return False
    if not md.positions:
        return False
    old = obj.data
    obj.data = mesh_datablock_for(md, r.mesh_id, obj.name, coords.stud_scale(), r.mesh_fit,
                                  tuple(r.initial_size), tuple(r.mesh_scale),
                                  tuple(r.mesh_offset), cache)
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    materials.ensure_slot(obj)
    r.asset_missing = False
    return True


def import_file(context, path, options):
    return Importer(context, options).run(path)
