"""Imports Roblox models/places (.rbxm, .rbxmx, .rbxl, .rbxlx) into Blender."""

import math
import os

import bpy
from mathutils import Matrix, Vector

from . import assets, character, coords, effects, geometry, lighting, materials, unions
from .props import suspend_updates
from .rbx import CFrame, enums, load_file
from .rbx import mesh as rbxmesh
from .rbx.color import to_linear

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
    "CornerWedge": "CORNER_WEDGE", "Torso": "BLOCK", "Head": "HEAD",
}
CLASSIC_HEAD_MESH = "rbxasset://avatar/heads/head.mesh"

# Properties holding asset references, for prefetching downloads
_ASSET_PROPS = ("MeshId", "MeshID", "TextureID", "TextureId", "Texture", "ShirtTemplate",
                "PantsTemplate", "Graphic", "ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap",
                "AssetId")


class ImportOptions:
    def __init__(self, stud_scale=1.0, import_lighting=True, import_lights=True,
                 import_attachments=False, import_storage=False, asset_folder="",
                 hide_invisible=True, build_rigs=True, allow_download=True):
        self.stud_scale = stud_scale
        self.import_lighting = import_lighting
        self.import_lights = import_lights
        self.import_attachments = import_attachments
        self.import_storage = import_storage
        self.asset_folder = asset_folder
        self.hide_invisible = hide_invisible
        self.build_rigs = build_rigs
        self.allow_download = allow_download


class ImportReport:
    def __init__(self):
        self.counts = {}
        self.missing = {}   # asset content -> [object names]
        self.reasons = {}   # asset content -> why it's missing
        self.warnings = []
        self.download_note = None
        self.downloaded = 0

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def miss(self, content, who, reason=None):
        self.missing.setdefault(content, []).append(who)
        if reason:
            self.reasons[content] = reason

    def summary(self):
        parts = ", ".join("%d %s" % (v, k) for k, v in sorted(self.counts.items()))
        s = "Imported " + (parts or "nothing")
        if self.downloaded:
            s += "; downloaded %d asset(s)" % self.downloaded
        if self.missing:
            s += "; %d asset(s) missing" % len(self.missing)
        return s

    def write_text(self, title):
        lines = ["Roblox import report: " + title, "", self.summary(), ""]
        if self.missing:
            lines.append("Missing assets:")
            if self.download_note:
                lines.append("  (Not downloaded: %s)" % self.download_note)
            for content, who in sorted(self.missing.items()):
                why = self.reasons.get(content)
                lines.append("  %s  (used by %d: %s)%s" % (
                    content, len(who), ", ".join(who[:5]), ("  -- " + why) if why else ""))
            lines.append("")
            lines.append("Fix: set an Open Cloud API key in the add-on preferences, or put files")
            lines.append("named by asset id in your Asset Folder, then click Reload Missing Assets.")
            lines.append("")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend("  " + w for w in self.warnings[:500])
        txt = bpy.data.texts.get("RBX Import Report") or bpy.data.texts.new("RBX Import Report")
        txt.clear()
        txt.write("\n".join(lines))
        return txt


class Importer:
    def __init__(self, context, options, resolver=None):
        self.context = context
        self.scene = context.scene
        self.opts = options
        self.scale = options.stud_scale
        self.resolver = resolver or assets.default_resolver(options.asset_folder,
                                                            options.allow_download)
        self.report = ImportReport()
        self.report.download_note = self.resolver.download_note
        self.world = {}           # object -> world matrix we assigned
        self.objects = {}         # id(instance) -> object
        self.mesh_cache = {}
        self.mesh_data_cache = {}
        self._has_parts = {}
        self.collection = None
        self.roots = []
        self.characters = []
        self.beams = []
        self.trails = []
        self.explosions = []
        self.attachment_objs = {}
        self.highlights = []

    # ------------------------------------------------------------------
    def run(self, path):
        doc = load_file(path, self.report.warnings)
        return self.run_document(doc, os.path.splitext(os.path.basename(path))[0])

    def run_document(self, doc, title):
        self.scene.rblx.stud_scale = self.scale
        self.collection = bpy.data.collections.new(title)
        self.scene.collection.children.link(self.collection)

        self.prefetch(doc)

        # R6 body packages (CharacterMesh) turn body blocks into package meshes
        for inst in list(doc.all_instances()):
            if character.is_character(inst):
                n = character.apply_character_meshes(inst, self.resolver)
                if n:
                    self.report.count("body package meshes", n)
                if self.opts.build_rigs:
                    n = character.weld_loose_accessories(inst)
                    if n:
                        self.report.count("accessories attached", n)

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

            for inst, obj in self.characters:
                try:
                    character.setup(self, inst, obj) if self.opts.build_rigs else (
                        character.apply_body_colors(self, inst), character.apply_clothing(self, inst))
                except Exception as ex:  # keep the import even if rigging fails
                    self.report.warnings.append("%s: rig not built (%s)" % (inst.name, ex))

        # MaterialService: Use2022Materials, MaterialVariants and overrides (places only;
        # models keep the scene's settings)
        ms = doc.find_service("MaterialService") if is_place else None
        if ms is not None:
            from . import materialservice
            materialservice.import_material_service(self.scene, ms, self.resolver, self.report)

        # Materials once everything (layers, colours) is in place
        for obj in self.objects.values():
            if obj.rblx.kind == "PART" and obj.rblx.material_mode != "SURFACE":
                materials.refresh(obj)

        self.make_beams()
        self.make_highlights()

        # Post-processing effects: Lighting children and the Workspace camera's
        post = [c for c in (lighting_inst.children if lighting_inst is not None else [])
                if c.class_name in effects.POST_CLASSES]
        ws = doc.find_service("Workspace") if is_place else None
        for cam in (ws.children if ws is not None else []):
            if cam.class_name == "Camera":
                post += [c for c in cam.children if c.class_name in effects.POST_CLASSES]
        if post and self.opts.import_lighting:
            effects.set_post_values(self.scene, effects.values_from_instances(post))
            self.report.count("post effects", len(post))
        effects.update_cameras(self.scene)

        if lighting_inst is not None and self.opts.import_lighting:
            lighting.set_props(self.scene, lighting.values_from_instance(lighting_inst))
            self.report.count("lighting settings")

        if self.resolver.downloader is not None:
            self.report.downloaded = self.resolver.downloader.downloaded
        self.report.write_text(title)
        return self.report

    def prefetch(self, doc):
        if self.resolver.downloader is None:
            return
        contents = []
        for inst in doc.all_instances():
            for k in _ASSET_PROPS:
                v = inst.props.get(k)
                if isinstance(v, str) and v.strip():
                    contents.append(v)
        if not contents:
            return
        wm = self.context.window_manager
        try:
            wm.progress_begin(0, 100)
        except Exception:
            wm = None

        def progress(done, total):
            if wm is not None:
                wm.progress_update(int(100 * done / max(total, 1)))

        try:
            self.resolver.prefetch(contents, progress)
        finally:
            if wm is not None:
                wm.progress_end()

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
            self.roots.append(obj)
        self.world[obj] = world

    def build(self, inst, parent_obj):
        cls = inst.class_name
        if cls == "Terrain":
            self.make_terrain(inst)
            return
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
            if character.is_character(inst):
                self.characters.append((inst, obj))
        elif cls in ("Decal", "Texture"):
            if parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_decal(inst, parent_obj)
        elif cls in ("PointLight", "SpotLight", "SurfaceLight"):
            if self.opts.import_lights and parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_light(inst, parent_obj)
        elif cls in effects.EFFECT_CLASSES:
            if parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_effect(inst, parent_obj)
        elif cls == "Beam":
            self.beams.append(inst)
        elif cls == "Trail":
            self.trails.append(inst)
        elif cls == "Explosion":
            self.explosions.append(inst)
        elif cls == "Highlight":
            self.highlights.append((inst, parent_obj))
        elif cls == "Attachment":
            if self.opts.import_attachments and parent_obj is not None and parent_obj.rblx.kind == "PART":
                self.make_attachment(inst, parent_obj)
            if parent_obj is not None and parent_obj.rblx.kind == "PART":
                world = None
                for c in inst.children:
                    if c.class_name in effects.EFFECT_CLASSES:  # emitters in attachments
                        if world is None:
                            world = self.attachment_world(inst)
                        self.make_effect(c, parent_obj, world)
                    elif c.class_name == "Beam":
                        self.beams.append(c)
                    elif c.class_name == "Trail":
                        self.trails.append(c)
        elif cls in PART_MODIFIERS:
            pass  # consumed by make_part
        elif self.has_parts(inst):
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
        if not isinstance(pivot, CFrame) and inst.class_name in ("Accessory", "Accoutrement", "Hat"):
            handle = inst.find_first_child("Handle")
            if handle is not None and isinstance(handle.get("CFrame"), CFrame):
                pivot = handle.props["CFrame"]
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
        obj = self.make_empty(inst.name, parent_obj, world, "MODEL", inst.class_name)
        self.objects[id(inst)] = obj
        return obj

    # ------------------------------------------------------------------
    def load_mesh(self, content, who):
        if not content:
            return None
        if content in self.mesh_data_cache:
            return self.mesh_data_cache[content]
        md = None
        path = self.resolver.resolve_mesh(content)
        if path is None:
            self.report.miss(content, who, self.resolver.error_for(content))
        else:
            try:
                with open(path, "rb") as f:
                    md = rbxmesh.read_mesh(f.read())
            except (OSError, rbxmesh.MeshFormatError) as ex:
                self.report.warnings.append("%s: %s (%s)" % (who, ex, path))
                self.report.miss(content, who, str(ex))
        self.mesh_data_cache[content] = md
        return md

    def mesh_datablock(self, md, mesh_id, name, fit, initial_size, mesh_scale, mesh_offset):
        return mesh_datablock_for(md, mesh_id, name, self.scale, fit, initial_size,
                                  mesh_scale, mesh_offset, self.mesh_cache)

    def add_layer_from_content(self, obj, content, mapping, name, kind, color=(1.0, 1.0, 1.0),
                               transparency=0.0, face="FRONT", region="TORSO",
                               tiling=(2.0, 2.0, 0.0, 0.0)):
        layer = materials.add_layer(obj, None, mapping, name, kind, content, face, color,
                                    transparency, region, tiling, rebuild=False)
        if not materials.resolve_layer_image(layer, self.resolver):
            self.report.miss(content, obj.name, self.resolver.error_for(content))
            obj.rblx.asset_missing = True
        self.report.count("textures")
        return layer

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
        color = to_linear(color)
        transparency = float(inst.get("Transparency", default=0.0) or 0.0)
        reflectance = float(inst.get("Reflectance", default=0.0) or 0.0)
        material_name = enums.MATERIALS.get(inst.get("Material", default=256), "Plastic")

        shape = "BLOCK"
        initial_size = size
        geom_size = size
        me = None
        mesh_id = ""
        texture_id = ""
        texture_tint = (1.0, 1.0, 1.0)
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
            initial_size = tuple(inst.get("InitialSize", default=size))
            try:
                me = unions.build_union_mesh(inst, self.scale, self.resolver, self.scene, name)
            except Exception as ex:
                me = None
                self.report.warnings.append("%s: union not rebuilt (%s); imported as a box" % (name, ex))
            if me is None:
                placeholder = True
                asset = inst.get("AssetId", default="")
                if isinstance(asset, str) and asset:
                    self.report.miss(asset, name, self.resolver.error_for(asset))
            else:
                self.report.count("unions")
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
                vc = special.get("VertexColor")
                if isinstance(vc, tuple) and len(vc) == 3:
                    texture_tint = to_linear(vc)
                if special.class_name in ("SpecialMesh", "FileMesh"):
                    mtype = enums.MESH_TYPES.get(special.get("MeshType", default=5), "FileMesh")
                    if special.class_name == "FileMesh":
                        mtype = "FileMesh"
                else:
                    mtype = "Brick" if special.class_name == "BlockMesh" else "Cylinder"
                texture_id = special.get("TextureId", "TextureID", default="") or ""

                if mtype == "FileMesh":
                    mesh_id = special.get("MeshId", "MeshID", default="") or ""
                    md = self.load_mesh(mesh_id, name)
                    shape = "MESH"
                    initial_size = size
                    mesh_fit = False
                    if md is not None and md.positions:
                        me = self.mesh_datablock(md, mesh_id, name, False, initial_size,
                                                 mscale, moffset)
                    else:
                        placeholder = True
                elif mtype == "Head":
                    m = min(size)
                    head_dims = (m * mscale[0], m * mscale[1], m * mscale[2])
                    md = self.load_studio_mesh(CLASSIC_HEAD_MESH)
                    if md is not None:
                        shape = "MESH"
                        initial_size = size
                        mesh_id = CLASSIC_HEAD_MESH
                        me = mesh_datablock_for(md, "head", "Head", self.scale, True, head_dims,
                                                None, None, self.mesh_cache)
                        mesh_fit = False
                        mscale = head_dims
                    else:
                        shape = "HEAD"
                        geom_size = (head_dims[0], head_dims[1], head_dims[2])
                else:
                    shape = MESH_TYPE_SHAPES.get(mtype, "BLOCK")
                    geom_size = tuple(s * m for s, m in zip(size, mscale))

        # Object and geometry
        obj = bpy.data.objects.new(name, me if me is not None else bpy.data.meshes.new(name))
        self.collection.objects.link(obj)
        self.objects[id(inst)] = obj
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
        variant = inst.get("MaterialVariantSerialized", "MaterialVariant", default="")
        r.material_variant = variant if isinstance(variant, str) else ""
        r.cast_shadow = bool(inst.get("CastShadow", default=True))
        r.anchored = bool(inst.get("Anchored", default=True))
        r.can_collide = bool(inst.get("CanCollide", default=True))
        r.can_touch = bool(inst.get("CanTouch", default=True))
        r.can_query = bool(inst.get("CanQuery", default=True))
        r.locked = bool(inst.get("Locked", default=False))
        r.massless = bool(inst.get("Massless", default=False))
        r.mesh_id = mesh_id if isinstance(mesh_id, str) else ""
        r.texture_id = texture_id if isinstance(texture_id, str) else ""
        r.mesh_fit = mesh_fit
        r.mesh_scale = mscale
        r.mesh_offset = moffset
        r.asset_missing = placeholder and bool(mesh_id)

        obj.color = (*color, 1.0 - r.transparency)
        from .props import casts_shadow
        obj.visible_shadow = casts_shadow(r)
        if self.opts.hide_invisible and r.transparency >= 0.999:
            obj.display_type = "WIRE"
        materials.ensure_slot(obj)

        if surface is not None:
            self.apply_surface_appearance(obj, surface)
        if r.texture_id:
            self.add_layer_from_content(obj, r.texture_id, "UV", "TextureID", "TextureID",
                                        color=texture_tint)

        self.report.count("parts")
        return obj

    def load_studio_mesh(self, content):
        if content in self.mesh_data_cache:
            return self.mesh_data_cache[content]
        md = None
        path = self.resolver.resolve(content)
        if path:
            try:
                with open(path, "rb") as f:
                    md = rbxmesh.read_mesh(f.read())
            except (OSError, rbxmesh.MeshFormatError):
                md = None
        self.mesh_data_cache[content] = md
        return md

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
            path = self.resolver.resolve_image(content)
            img = materials.load_image(path, non_color=(role != "color")) if path else None
            if img:
                maps[role] = img
            else:
                self.report.miss(content, obj.name, self.resolver.error_for(content))
        if not maps:
            return
        alpha_mode = sa.get("AlphaMode", default=0)
        tint = sa.get("Color", default=(1.0, 1.0, 1.0))
        tint = to_linear(tint) if isinstance(tint, tuple) else (1.0, 1.0, 1.0)
        key = "%s %08x" % (sa.name, abs(hash(tuple(ids))) & 0xFFFFFFFF)
        obj.rblx.material_mode = "SURFACE"
        materials.assign(obj, materials.surface_appearance_material(
            key, maps, alpha_mode if isinstance(alpha_mode, int) else 0, tint))

    # ------------------------------------------------------------------
    def make_decal(self, inst, part_obj):
        tex = inst.get("Texture", "TextureContent", "ColorMap", default="")
        if not isinstance(tex, str):
            tex = ""
        face = enums.NORMAL_IDS.get(inst.get("Face", default=5), "FRONT")
        color = inst.get("Color3", "Color")
        color = color if isinstance(color, tuple) and len(color) == 3 else (1.0, 1.0, 1.0)
        color = to_linear(color)
        transparency = min(max(float(inst.get("Transparency", default=0.0) or 0.0), 0.0), 1.0)
        if inst.class_name == "Texture":
            tiling = (float(inst.get("StudsPerTileU", default=2.0)),
                      float(inst.get("StudsPerTileV", default=2.0)),
                      float(inst.get("OffsetStudsU", default=0.0)),
                      float(inst.get("OffsetStudsV", default=0.0)))
            mapping = "TILED"
        else:
            tiling = (2.0, 2.0, 0.0, 0.0)
            mapping = "FACE"
        self.add_layer_from_content(part_obj, tex, mapping, inst.name, inst.class_name,
                                    color=color, transparency=transparency, face=face,
                                    tiling=tiling)
        self.report.count("decals")

    def make_light(self, inst, part_obj):
        cls = inst.class_name
        brightness = float(inst.get("Brightness", default=1.0))
        rng = float(inst.get("Range", default=8.0))
        color = inst.get("Color", default=(1.0, 1.0, 1.0))
        color = to_linear(color if isinstance(color, tuple) else (1.0, 1.0, 1.0))
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

    def make_terrain(self, inst):
        from . import terrain
        grid = inst.props.get("SmoothGrid")
        if isinstance(grid, str):  # blobs that happen to be valid UTF-8 are read as text
            grid = grid.encode("utf-8", "surrogateescape")
        if not grid or len(grid) <= 2:
            return
        colors = inst.props.get("MaterialColors")
        if isinstance(colors, str):
            colors = colors.encode("utf-8", "surrogateescape")
        water = inst.props.get("WaterColor")

        def num_of(i, key, default):
            v = i.props.get(key)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

        def num(key, default):
            return num_of(inst, key, default)

        try:
            terrain.build(self.context, self.collection, grid, colors or b"",
                          water if isinstance(water, tuple) else None,
                          num("WaterTransparency", 0.3), self.scale, self.report,
                          water_wave_size=num("WaterWaveSize", 0.15),
                          water_wave_speed=num("WaterWaveSpeed", 10.0),
                          water_reflectance=num("WaterReflectance", 1.0),
                          decoration=bool(inst.props.get("Decoration", False)),
                          grass_length=num("GrassLength", 0.7))
        except Exception as ex:
            self.report.warnings.append("Terrain not imported (%s)" % ex)
        for child in getattr(inst, "children", []):
            if child.class_name == "Clouds":
                from . import decoration
                col = child.props.get("Color")
                decoration.build_clouds(self.collection, num_of(child, "Cover", 0.5),
                                        num_of(child, "Density", 0.7),
                                        col if isinstance(col, tuple) else (1.0, 1.0, 1.0),
                                        bool(child.props.get("Enabled", True)),
                                        child.props.get("Name") or "Clouds")
                self.report.count("clouds")

    def attachment_world(self, att):
        """World matrix of an Attachment instance (its part's CFrame * its CFrame)."""
        if att is None or isinstance(att, (str, bytes)) or getattr(att, "class_name", "") != "Attachment":
            return None
        part = att.parent
        cf = att.get("CFrame")
        if not isinstance(cf, CFrame):
            cf = CFrame()
        part_obj = self.objects.get(id(part)) if part is not None else None
        if part_obj is not None and part_obj in self.world:
            loc, rot, _ = self.world[part_obj].decompose()
            base = Matrix.LocRotScale(loc, rot, None)
        elif part is not None and isinstance(part.get("CFrame"), CFrame):
            base = coords.cframe_to_matrix(part.props["CFrame"], self.scale)
        else:
            return None
        return base @ coords.cframe_to_matrix(cf, self.scale)

    def make_effect(self, inst, part_obj, world=None):
        params = effects.params_from_instance(inst)
        if world is None:
            loc, rot, _ = self.world[part_obj].decompose()
            world = Matrix.LocRotScale(loc, rot, None)
            params["emit_size"] = tuple(geometry.part_box_size(part_obj)) \
                if part_obj.rblx.shape not in ("MESH", "UNION") else tuple(part_obj.rblx.size)
        else:
            params["emit_size"] = (0.0, 0.0, 0.0)  # attachments emit from a point
        if params["kind"] in ("Fire", "Smoke"):  # these rise from the part, not all of it
            params["emit_size"] = tuple(min(e, 2.0) for e in params["emit_size"])
        try:
            part_world = self.world[part_obj] @ Matrix.Diagonal((*part_obj.scale, 1.0))
            obj = effects.create_emitter(self.context, params, parent=part_obj, world=world,
                                         name=inst.name, collection=self.collection,
                                         resolver=self.resolver, parent_world=part_world)
        except Exception as ex:
            self.report.warnings.append("%s: %s not created (%s)" % (inst.name, inst.class_name, ex))
            return None
        self.report.count("particle effects")
        return obj

    def attachment_object(self, att):
        """An empty for an Attachment instance (made on demand for Beams and Trails)."""
        if att is None or isinstance(att, (str, bytes)) or getattr(att, "class_name", "") != "Attachment":
            return None
        obj = self.attachment_objs.get(id(att))
        if obj is None:
            part_obj = self.objects.get(id(att.parent)) if att.parent is not None else None
            if part_obj is None or part_obj not in self.world:
                return None
            obj = self.make_attachment(att, part_obj)
        return obj

    def make_beams(self):
        for inst in self.beams:
            params = effects.beam_params_from_instance(inst, self.attachment_world)
            if params is None:
                self.report.warnings.append("%s: Beam needs two attachments" % inst.name)
                continue
            p = inst.props
            a0, a1 = self.attachment_object(p.get("Attachment0")), self.attachment_object(p.get("Attachment1"))
            if a0 is not None and a1 is not None:
                effects.create_live_beam(self.context, params, a0, a1, name=inst.name,
                                         collection=self.collection, resolver=self.resolver)
            else:
                obj = effects.create_beam(self.context, params, name=inst.name,
                                          collection=self.collection, resolver=self.resolver)
                obj.hide_render = obj.hide_viewport = not params["enabled"]
            self.report.count("beams")
        for inst in self.trails:
            p = inst.props
            a0, a1 = self.attachment_object(p.get("Attachment0")), self.attachment_object(p.get("Attachment1"))
            if a0 is None or a1 is None:
                self.report.warnings.append("%s: Trail needs two attachments" % inst.name)
                continue
            effects.create_trail(self.context, effects.trail_params_from_instance(inst), a0, a1,
                                 name=inst.name, collection=self.collection, resolver=self.resolver)
            self.report.count("trails")
        for inst in self.explosions:
            p = inst.props
            if p.get("Visible") is False:
                continue
            pos = p.get("Position") if isinstance(p.get("Position"), tuple) else (0.0, 0.0, 0.0)
            radius = float(p.get("BlastRadius", 4.0) or 4.0)
            effects.explosion_emitters(self.context, coords.vec_to_bl(pos, self.scale), radius * self.scale,
                                       frame=self.scene.frame_start, collection=self.collection)
            self.report.count("explosions")

    def make_highlights(self):
        for inst, parent_obj in self.highlights:
            p = inst.props
            if p.get("Enabled") is False:
                continue
            adornee = p.get("Adornee")
            target = self.objects.get(id(adornee)) if adornee is not None and \
                not isinstance(adornee, (str, bytes)) else None
            target = target or parent_obj
            if target is None:
                continue
            fill = p.get("FillColor") if isinstance(p.get("FillColor"), tuple) else (1.0, 0.0, 0.0)
            outline = p.get("OutlineColor") if isinstance(p.get("OutlineColor"), tuple) else (1.0, 1.0, 1.0)
            for part in effects.highlight_targets(target):
                with suspend_updates():
                    r = part.rblx
                    r.highlight_fill = to_linear(fill)
                    r.highlight_outline = to_linear(outline)
                    r.highlight_fill_transparency = float(p.get("FillTransparency", 0.5))
                    r.highlight_outline_transparency = float(p.get("OutlineTransparency", 0.0))
                    r.highlight_enabled = True
                effects.apply_highlight(part, self.scene)
            self.report.count("highlights")

    def make_attachment(self, inst, part_obj):
        cf = inst.get("CFrame")
        if not isinstance(cf, CFrame):
            cf = CFrame()
        loc, rot, _ = self.world[part_obj].decompose()
        world = Matrix.LocRotScale(loc, rot, None) @ coords.cframe_to_matrix(cf, self.scale)
        obj = self.make_empty(inst.name, part_obj, world, "ATTACHMENT", "Attachment")
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.15 * self.scale
        self.attachment_objs[id(inst)] = obj
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
    path = resolver.resolve_mesh(r.mesh_id)
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
    materials.refresh(obj)
    return True


def import_file(context, path, options):
    return Importer(context, options).run(path)
