"""Roblox unions (CSG): UnionOperation / NegateOperation / IntersectOperation.

A union keeps the parts it was made from in ChildData (a small binary
Roblox model; modern unions keep it in the asset their AssetId points to,
a PartOperationAsset). Child CFrames are relative to the union as it was when
it was made (at InitialSize). We rebuild the shape with Blender's exact
boolean solver: positive parts are joined, NegateOperations are cut out,
IntersectOperation keeps only the overlap. Nested unions recurse.

When UsePartColor is off each child keeps its own colour, stored as a face
attribute (rbx_color / rbx_use_color) that the part materials read."""

import bpy
from mathutils import Matrix

from . import coords, geometry
from .rbx import CFrame, enums
from .rbx.binary import read_binary
from .rbx.color import to_linear

MAX_DEPTH = 8
POSITIVE_CLASSES = {"Part", "WedgePart", "CornerWedgePart", "TrussPart", "SpawnLocation", "Seat",
                    "UnionOperation", "IntersectOperation", "PartOperation"}
SHAPES_BY_MESHTYPE = {"Wedge": "WEDGE", "Sphere": "BALL", "Cylinder": "CYLINDER", "Brick": "BLOCK",
                      "CornerWedge": "CORNER_WEDGE", "Torso": "BLOCK", "Head": "HEAD"}


class UnionError(Exception):
    pass


def _bytes(v):
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return v.encode("utf-8", "surrogateescape")  # the reader keeps UTF-8-valid blobs as text
    return b""


def child_instances(inst, resolver=None):
    """The parts a union was made from (top-level instances of its ChildData)."""
    for key in ("ChildData2", "ChildData"):
        data = _bytes(inst.props.get(key))
        if data.startswith(b"<roblox!"):
            return read_binary(data).roots
    asset = inst.props.get("AssetId")
    if isinstance(asset, str) and asset.strip() and resolver is not None:
        path = resolver.resolve(asset)
        if path:
            from .rbx import load_file
            doc = load_file(path)
            for a in doc.all_instances():
                if a.class_name == "PartOperationAsset":
                    for key in ("ChildData2", "ChildData"):
                        data = _bytes(a.props.get(key))
                        if data.startswith(b"<roblox!"):
                            return read_binary(data).roots
        raise UnionError("union asset %s couldn't be loaded (%s)" % (
            asset, resolver.error_for(asset) if hasattr(resolver, "error_for") else "not found"))
    return None


def _primitive(inst):
    """(shape, size) for a basic part, honouring Sphere/Cylinder/... SpecialMeshes."""
    cls = inst.class_name
    size = tuple(inst.get("size", "Size", default=(4.0, 1.0, 2.0)))
    if cls == "WedgePart":
        shape = "WEDGE"
    elif cls == "CornerWedgePart":
        shape = "CORNER_WEDGE"
    else:
        shape = enums.PART_SHAPES.get(inst.get("shape", "Shape", default=1), "BLOCK")
        if shape not in ("BLOCK", "BALL", "CYLINDER", "WEDGE", "CORNER_WEDGE"):
            shape = "BLOCK"
    special = inst.find_first_child_of_class("SpecialMesh", "BlockMesh", "CylinderMesh")
    if special is not None:
        if special.class_name == "SpecialMesh":
            mtype = enums.MESH_TYPES.get(special.get("MeshType", default=5), "FileMesh")
            shape = SHAPES_BY_MESHTYPE.get(mtype, shape)
        elif special.class_name == "CylinderMesh":
            shape = "CYLINDER"
        scale = special.get("Scale", default=(1.0, 1.0, 1.0))
        if isinstance(scale, tuple) and len(scale) == 3:
            size = tuple(s * m for s, m in zip(size, scale))
    if shape == "HEAD":
        shape = "CYLINDER"
    return shape, size


def _color(inst):
    c = inst.get("Color3uint8", "Color")
    if not (isinstance(c, tuple) and len(c) == 3):
        bc = inst.get("BrickColor", "brickColor", default=194)
        c = enums.brick_color(bc if isinstance(bc, int) else 194)
    return to_linear(c)


def _tag_color(me, color):
    attr = me.attributes.get("rbx_color") or me.attributes.new("rbx_color", "FLOAT_COLOR", "FACE")
    attr.data.foreach_set("color", [*color, 1.0] * len(me.polygons))
    use = me.attributes.get("rbx_use_color") or me.attributes.new("rbx_use_color", "FLOAT", "FACE")
    use.data.foreach_set("value", [1.0] * len(me.polygons))


class _Builder:
    def __init__(self, scale, resolver, scene):
        self.scale = scale
        self.resolver = resolver
        self.scene = scene
        self.temp = bpy.data.collections.new("RBX CSG temp")
        scene.collection.children.link(self.temp)
        self.trash_objects = []
        self.trash_meshes = []
        self.trash_collections = [self.temp]

    def cleanup(self):
        for o in self.trash_objects:
            if o.name in bpy.data.objects:
                bpy.data.objects.remove(o)
        for me in self.trash_meshes:
            if me.name in bpy.data.meshes and me.users == 0:
                bpy.data.meshes.remove(me)
        for c in self.trash_collections:
            if c.name in bpy.data.collections:
                bpy.data.collections.remove(c)

    def _object(self, me, matrix, coll):
        o = bpy.data.objects.new("rbx_csg", me)
        coll.objects.link(o)
        o.matrix_world = matrix
        self.trash_objects.append(o)
        return o

    def _sub_collection(self):
        c = bpy.data.collections.new("RBX CSG ops")
        self.temp.children.link(c)
        self.trash_collections.append(c)
        return c

    def child_mesh(self, inst, keep_colors, depth):
        """Mesh for one child, in its own local space (Blender units)."""
        if inst.class_name in ("UnionOperation", "NegateOperation", "IntersectOperation",
                               "PartOperation"):
            me = self.union_mesh(inst, depth + 1)
            if me is None:
                return None
            init = inst.get("InitialSize")
            size = inst.get("size", "Size")
            if isinstance(init, tuple) and isinstance(size, tuple):
                ratio = [(s / i) if i > 1e-6 else 1.0 for s, i in zip(size, init)]
                me.transform(Matrix.Diagonal((*coords.size_to_bl(ratio), 1.0)))
            # a nested union with one colour (UsePartColor) still shows that colour here
            if keep_colors and me.attributes.get("rbx_use_color") is None:
                _tag_color(me, _color(inst))
            return me
        shape, size = _primitive(inst)
        me = bpy.data.meshes.new("rbx_csg")
        geometry.build_primitive(me, shape, tuple(s * self.scale for s in size))
        self.trash_meshes.append(me)
        if keep_colors:
            _tag_color(me, _color(inst))
        return me

    def union_mesh(self, inst, depth=0):
        if depth > MAX_DEPTH:
            raise UnionError("unions nested too deeply")
        children = child_instances(inst, self.resolver)
        if not children:
            return None
        keep_colors = inst.get("UsePartColor", default=False) is not True
        intersect = inst.class_name == "IntersectOperation"
        pos, neg = [], []
        for c in children:
            if c.class_name not in POSITIVE_CLASSES and c.class_name != "NegateOperation":
                continue
            me = self.child_mesh(c, keep_colors, depth)
            if me is None:
                continue
            cf = c.get("CFrame")
            m = coords.cframe_to_matrix(cf if isinstance(cf, CFrame) else CFrame(), self.scale)
            (neg if c.class_name == "NegateOperation" else pos).append((me, m))
        if not pos:
            if inst.class_name == "NegateOperation" and neg:
                pos, neg = neg, []  # a negate's own geometry is its (single) part
            else:
                return None
        base = self._object(pos[0][0].copy(), pos[0][1], self.temp)
        self.trash_meshes.append(base.data)
        if len(pos) > 1:
            coll = self._sub_collection()
            for me, m in pos[1:]:
                self._object(me, m, coll)
            mod = base.modifiers.new("U", "BOOLEAN")
            mod.operation = "INTERSECT" if intersect else "UNION"
            mod.operand_type = "COLLECTION"
            mod.collection = coll
            mod.solver = "EXACT"
        if neg:
            coll = self._sub_collection()
            for me, m in neg:
                self._object(me, m, coll)
            mod = base.modifiers.new("D", "BOOLEAN")
            mod.operation = "DIFFERENCE"
            mod.operand_type = "COLLECTION"
            mod.collection = coll
            mod.solver = "EXACT"
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        result = bpy.data.meshes.new_from_object(base.evaluated_get(dg))
        result.transform(base.matrix_world)
        self.trash_meshes.append(result)
        return result


def build_union_mesh(inst, scale, resolver=None, scene=None, name="Union"):
    """Mesh for a union instance in its own local space at InitialSize, or None."""
    scene = scene or bpy.context.scene
    b = _Builder(scale, resolver, scene)
    try:
        me = b.union_mesh(inst)
        if me is None:
            return None
        final = me.copy()
        final.name = name
        return final
    finally:
        b.cleanup()
