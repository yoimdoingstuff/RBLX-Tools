"""Roblox characters: rigs (armatures from Motor6D joints), BodyColors,
clothing (Shirt / Pants / T-Shirt), accessories, and building R6/R15
characters and user avatars as Roblox documents before import."""

import os

import bpy
from mathutils import Matrix

from . import assets, coords, materials
from .rbx import CFrame, Document, Instance, load_file
from .rbx.color import to_linear

R6_PARTS = ("Head", "Torso", "Left Arm", "Right Arm", "Left Leg", "Right Leg")

# Standard R6 Motor6Ds: (name, part0, part1, C0, C1)
_R6_ROT = {
    "root": (-1, 0, 0, 0, 0, 1, 0, 1, 0),
    "right": (0, 0, 1, 0, 1, 0, -1, 0, 0),
    "left": (0, 0, -1, 0, 1, 0, 1, 0, 0),
}
R6_JOINTS = (
    ("RootJoint", "HumanoidRootPart", "Torso", (0, 0, 0), (0, 0, 0), "root"),
    ("Neck", "Torso", "Head", (0, 1, 0), (0, -0.5, 0), "root"),
    ("Right Shoulder", "Torso", "Right Arm", (1, 0.5, 0), (-0.5, 0.5, 0), "right"),
    ("Left Shoulder", "Torso", "Left Arm", (-1, 0.5, 0), (0.5, 0.5, 0), "left"),
    ("Right Hip", "Torso", "Right Leg", (1, -1, 0), (0.5, 1, 0), "right"),
    ("Left Hip", "Torso", "Left Leg", (-1, -1, 0), (-0.5, 1, 0), "left"),
)

# Body part -> BodyColors property group
BODY_COLOR_GROUPS = {
    "Head": ("Head",),
    "Torso": ("Torso", "UpperTorso", "LowerTorso"),
    "LeftArm": ("Left Arm", "LeftUpperArm", "LeftLowerArm", "LeftHand"),
    "RightArm": ("Right Arm", "RightUpperArm", "RightLowerArm", "RightHand"),
    "LeftLeg": ("Left Leg", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot"),
    "RightLeg": ("Right Leg", "RightUpperLeg", "RightLowerLeg", "RightFoot"),
}

# Which parts get the shirt / pants, and which template area (R6 boxes)
SHIRT_PARTS = {
    "Torso": "TORSO", "Left Arm": "LEFT_LIMB", "Right Arm": "RIGHT_LIMB",
    "UpperTorso": "TORSO", "LowerTorso": "TORSO",
    "LeftUpperArm": "LEFT_LIMB", "LeftLowerArm": "LEFT_LIMB", "LeftHand": "LEFT_LIMB",
    "RightUpperArm": "RIGHT_LIMB", "RightLowerArm": "RIGHT_LIMB", "RightHand": "RIGHT_LIMB",
}
PANTS_PARTS = {
    "Torso": "TORSO", "Left Leg": "LEFT_LIMB", "Right Leg": "RIGHT_LIMB",
    "UpperTorso": "TORSO", "LowerTorso": "TORSO",
    "LeftUpperLeg": "LEFT_LIMB", "LeftLowerLeg": "LEFT_LIMB", "LeftFoot": "LEFT_LIMB",
    "RightUpperLeg": "RIGHT_LIMB", "RightLowerLeg": "RIGHT_LIMB", "RightFoot": "RIGHT_LIMB",
}

WELD_CLASSES = {"Weld", "ManualWeld", "WeldConstraint", "Snap", "Glue", "RigidConstraint"}


def is_character(inst):
    return inst.class_name == "Model" and inst.find_first_child_of_class("Humanoid") is not None


def _r6_cf(pos, rot_key):
    return CFrame(pos, _R6_ROT[rot_key])


# ---------------------------------------------------------------------------
# Joints

class Joint:
    __slots__ = ("name", "part0", "part1", "c0", "c1")

    def __init__(self, name, part0, part1, c0, c1):
        self.name, self.part0, self.part1, self.c0, self.c1 = name, part0, part1, c0, c1


def _parts_by_name(model):
    out = {}
    for d in model.descendants():
        if d.class_name in ("Part", "MeshPart") and d.name not in out:
            out[d.name] = d
    return out


def find_joints(model):
    joints = []
    for d in model.descendants():
        if d.class_name in ("Motor6D", "Motor"):
            p0, p1 = d.props.get("Part0"), d.props.get("Part1")
            if isinstance(p0, Instance) and isinstance(p1, Instance):
                c0 = d.props.get("C0") if isinstance(d.props.get("C0"), CFrame) else CFrame()
                c1 = d.props.get("C1") if isinstance(d.props.get("C1"), CFrame) else CFrame()
                joints.append(Joint(d.name, p0, p1, c0, c1))
    if joints:
        return joints
    joints = joints_from_attachments(model)
    if joints:
        return joints
    parts = _parts_by_name(model)
    if all(n in parts for n in R6_PARTS):
        for name, p0, p1, c0, c1, rot in R6_JOINTS:
            if p0 in parts and p1 in parts:
                joints.append(Joint(name, parts[p0], parts[p1], _r6_cf(c0, rot), _r6_cf(c1, rot)))
    return joints


def joints_from_attachments(model):
    """Like Humanoid:BuildRigFromAttachments(): parts that share an
    '<Name>RigAttachment' are joined, starting from HumanoidRootPart."""
    parts = _parts_by_name(model)
    root = parts.get("HumanoidRootPart")
    if root is None:
        return []
    rig_atts = {}
    for p in parts.values():
        for c in p.children:
            if c.class_name == "Attachment" and c.name.endswith("RigAttachment"):
                rig_atts.setdefault(c.name, []).append((p, c))
    joints = []
    seen = {id(root)}
    queue = [root]
    while queue:
        part = queue.pop(0)
        for att in part.children:
            if att.class_name != "Attachment" or not att.name.endswith("RigAttachment"):
                continue
            for other, oatt in rig_atts.get(att.name, []):
                if id(other) in seen:
                    continue
                seen.add(id(other))
                c0 = att.props.get("CFrame") if isinstance(att.props.get("CFrame"), CFrame) else CFrame()
                c1 = oatt.props.get("CFrame") if isinstance(oatt.props.get("CFrame"), CFrame) else CFrame()
                joints.append(Joint(att.name[:-len("RigAttachment")] or "Root", part, other, c0, c1))
                queue.append(other)
    return joints


def pose_from_joints(model, joints=None):
    """Place every jointed part from the root outward
    (Part1.CFrame = Part0.CFrame * C0 * C1:Inverse())."""
    joints = joints if joints is not None else find_joints(model)
    children = {}
    for j in joints:
        children.setdefault(id(j.part0), []).append(j)
    targets = {id(j.part1) for j in joints}
    roots = [j.part0 for j in joints if id(j.part0) not in targets]
    seen = set()
    stack = list(dict((id(r), r) for r in roots).values())
    while stack:
        p = stack.pop()
        if id(p) in seen:
            continue
        seen.add(id(p))
        base = p.props.get("CFrame") if isinstance(p.props.get("CFrame"), CFrame) else CFrame()
        for j in children.get(id(p), []):
            j.part1.props["CFrame"] = base * j.c0 * j.c1.inverse()
            stack.append(j.part1)


# ---------------------------------------------------------------------------
# Blender side: called by the importer after a character model is built

def _bone_parent(imp, obj, arm, bone_name):
    world = imp.world[obj]
    bone = arm.data.bones[bone_name]
    parent_world = imp.world[arm] @ bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = parent_world.inverted_safe() @ world


def _flat(cf):
    return list(cf.pos) + list(cf.rot)


def build_rig(imp, model_inst, model_obj):
    joints = find_joints(model_inst)
    objs = imp.objects
    joints = [j for j in joints if id(j.part0) in objs and id(j.part1) in objs]
    if not joints:
        return None
    scale = imp.scale
    targets = {id(j.part1) for j in joints}
    roots = []
    for j in joints:
        if id(j.part0) not in targets and all(r is not j.part0 for r in roots):
            roots.append(j.part0)

    view_layer = bpy.context.view_layer
    arm_data = bpy.data.armatures.new(model_inst.name + " Rig")
    arm = bpy.data.objects.new(model_inst.name + " Rig", arm_data)
    imp.collection.objects.link(arm)
    imp.place(arm, model_obj, imp.world[model_obj])
    arm.rblx.kind = "RIG"
    arm.rblx.class_name = "Humanoid"
    arm.show_in_front = True
    arm_data.display_type = "STICK"
    arm_world_inv = imp.world[arm].inverted_safe()

    prev_active = view_layer.objects.active
    view_layer.update()
    view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        ebs = arm_data.edit_bones
        names = {}
        for root in roots:
            eb = ebs.new(root.name)
            eb.matrix = arm_world_inv @ coords.cframe_to_matrix(root.props.get("CFrame", CFrame()), scale)
            eb.length = 1.0 * scale
            names[id(root)] = eb.name
        pending = list(joints)
        for _ in range(len(joints) + 1):
            rest = []
            for j in pending:
                if id(j.part0) not in names:
                    rest.append(j)
                    continue
                if id(j.part1) in names:
                    continue
                p0cf = j.part0.props.get("CFrame") if isinstance(j.part0.props.get("CFrame"), CFrame) else CFrame()
                eb = ebs.new(j.part1.name)
                eb.matrix = arm_world_inv @ coords.cframe_to_matrix(p0cf * j.c0, scale)
                eb.length = 0.5 * scale
                eb.parent = ebs[names[id(j.part0)]]
                eb.use_connect = False
                names[id(j.part1)] = eb.name
            if not rest or len(rest) == len(pending):
                break
            pending = rest
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        arm.select_set(False)
        view_layer.objects.active = prev_active

    for j in joints:
        bn = names.get(id(j.part1))
        if bn and bn in arm_data.bones:
            b = arm_data.bones[bn]
            b["rbx_joint"] = j.name
            b["rbx_part0"] = j.part0.name
            b["rbx_c0"] = _flat(j.c0)
            b["rbx_c1"] = _flat(j.c1)

    rigged = {}
    for key, bn in names.items():
        obj = objs.get(key)
        if obj is not None:
            _bone_parent(imp, obj, arm, bn)
            rigged[key] = bn

    # Welded extras (accessories, attached parts) follow the part they're welded to
    welds = [d for d in model_inst.descendants() if d.class_name in WELD_CLASSES]
    for _ in range(4):
        changed = False
        for w in welds:
            a, b = w.props.get("Part0"), w.props.get("Part1")
            if not isinstance(a, Instance) or not isinstance(b, Instance):
                continue
            for src, dst in ((a, b), (b, a)):
                if id(src) in rigged and id(dst) not in rigged:
                    top = _top_under(dst, model_inst)
                    tobj = objs.get(id(top))
                    if tobj is not None and tobj.parent is not arm:
                        _bone_parent(imp, tobj, arm, rigged[id(src)])
                    rigged[id(dst)] = rigged[id(src)]
                    for d in top.descendants():
                        rigged.setdefault(id(d), rigged[id(src)])
                    changed = True
        if not changed:
            break
    imp.report.count("rigs")
    return arm


def _top_under(inst, model):
    cur = inst
    while cur.parent is not None and cur.parent is not model:
        cur = cur.parent
    return cur


def apply_body_colors(imp, model_inst):
    bc = model_inst.find_first_child_of_class("BodyColors")
    if bc is None:
        return
    from .rbx.enums import brick_color
    parts = {d.name: d for d in model_inst.descendants() if id(d) in imp.objects}
    for group, names in BODY_COLOR_GROUPS.items():
        col = bc.props.get(group + "Color3")
        if not isinstance(col, tuple):
            num = bc.props.get(group + "Color")
            col = brick_color(num) if isinstance(num, int) else None
        if col is None:
            continue
        col = to_linear(col)
        for n in names:
            inst = parts.get(n)
            obj = imp.objects.get(id(inst)) if inst else None
            if obj is not None and obj.rblx.kind == "PART":
                obj.rblx.color = col
                obj.color = (*col, obj.color[3])


# R15 body parts that share one clothing box (the template treats e.g. the
# upper arm, lower arm and hand as one arm)
R15_CLOTHING_GROUPS = {
    "torso": ("UpperTorso", "LowerTorso"),
    "left_arm": ("LeftUpperArm", "LeftLowerArm", "LeftHand"),
    "right_arm": ("RightUpperArm", "RightLowerArm", "RightHand"),
    "left_leg": ("LeftUpperLeg", "LeftLowerLeg", "LeftFoot"),
    "right_leg": ("RightUpperLeg", "RightLowerLeg", "RightFoot"),
}


def set_clothing_boxes(imp, parts, scale=None, world_of=None):
    """Store the box each mesh body part's clothing is projected from.
    `imp` (an Importer) supplies scale and rest-pose matrices; without it pass
    `scale` and `world_of(obj)`."""
    from mathutils import Vector
    from . import geometry
    if imp is not None:
        scale = imp.scale
        world_of = imp.world.__getitem__

    class _W:
        def __getitem__(self, o):
            return world_of(o)

    world = _W()
    for name, obj in parts.items():
        if obj.rblx.shape in ("BLOCK", "TRUSS") or obj.type != "MESH":
            continue
        group = next((g for g in R15_CLOTHING_GROUPS.values() if name in g), None)
        geometry.ensure_single_user_mesh(obj)
        if group is None:
            # R6 package mesh: the classic body part box (e.g. 1 x 2 x 1)
            half = [s * scale / 2.0 for s in obj.rblx.size]
            ratio = [s / i if i > 1e-6 else 1.0 for s, i in zip(obj.rblx.size, obj.rblx.initial_size)]
            obj["rblx_template_box"] = [0.0, 0.0, 0.0] + [h / r for h, r in zip(half, ratio)]
            continue
        members = [parts[n] for n in group if n in parts and parts[n].type == "MESH"]
        pts = [world[m] @ Vector(c) for m in members for c in m.bound_box]
        lo = Vector([min(p[i] for p in pts) for i in range(3)])
        hi = Vector([max(p[i] for p in pts) for i in range(3)])
        inv = world[obj].inverted_safe()
        c_local = inv @ ((lo + hi) / 2.0)
        half_local = inv.to_3x3() @ ((hi - lo) / 2.0)
        c_rbx = geometry._rbx(c_local)
        h_rbx = geometry._rbx(half_local)
        obj["rblx_template_box"] = list(c_rbx) + [abs(h_rbx.x), abs(h_rbx.y), abs(h_rbx.z)]


def apply_clothing(imp, model_inst):
    parts = {d.name: imp.objects[id(d)] for d in model_inst.descendants()
             if id(d) in imp.objects and imp.objects[id(d)].rblx.kind == "PART"}
    set_clothing_boxes(imp, parts)
    order = (("Pants", "PantsTemplate", PANTS_PARTS), ("Shirt", "ShirtTemplate", SHIRT_PARTS))
    for cls, prop, table in order:
        for c in model_inst.children:
            if c.class_name != cls:
                continue
            content = c.props.get(prop)
            if not isinstance(content, str) or not content.strip():
                continue
            tint = to_linear(c.props["Color3"]) if isinstance(c.props.get("Color3"), tuple) else (1, 1, 1)
            for part_name, region in table.items():
                obj = parts.get(part_name)
                if obj is None:
                    continue
                imp.add_layer_from_content(obj, content, "TEMPLATE", c.name or cls, cls,
                                           color=tint, region=region)
    # Body package overlay textures sit on top of the clothing
    for ov in [d for d in model_inst.descendants() if d.class_name == "CharacterMeshOverlay"]:
        obj = imp.objects.get(id(ov.parent))
        content = ov.props.get("Texture")
        if obj is not None and isinstance(content, str):
            imp.add_layer_from_content(obj, content, "UV", "Package Overlay", "CharacterMesh")
    for c in model_inst.children:
        if c.class_name == "ShirtGraphic":
            content = c.props.get("Graphic")
            target = parts.get("Torso") or parts.get("UpperTorso")
            if isinstance(content, str) and content.strip() and target is not None:
                tint = to_linear(c.props["Color3"]) if isinstance(c.props.get("Color3"), tuple) else (1, 1, 1)
                imp.add_layer_from_content(target, content, "FACE", c.name or "T-Shirt",
                                           "ShirtGraphic", color=tint, face="FRONT")


R6_BEVEL = 0.065  # studs: the chamfer on Roblox's own R6 body part meshes
R6_LIMBS = ("Torso", "Left Arm", "Right Arm", "Left Leg", "Right Leg")


def smooth_r6_body(imp, model_inst):
    """Give plain-block R6 body parts the rounded edges Roblox renders them with."""
    from . import geometry
    for d in model_inst.children:
        if d.name in R6_LIMBS and id(d) in imp.objects:
            obj = imp.objects[id(d)]
            if obj.rblx.kind == "PART" and obj.rblx.shape == "BLOCK" and obj.rblx.bevel == 0.0:
                obj.rblx.bevel = R6_BEVEL
                geometry.rebuild_part(obj)


def setup(imp, model_inst, model_obj):
    """Finish a character model after its parts were imported."""
    smooth_r6_body(imp, model_inst)
    apply_body_colors(imp, model_inst)
    apply_clothing(imp, model_inst)
    model_obj["rblx_character"] = True
    return build_rig(imp, model_inst, model_obj)


# ---------------------------------------------------------------------------
# Building characters as Roblox documents

R6_COLORS = {
    "Head": (245 / 255, 205 / 255, 48 / 255), "Torso": (13 / 255, 105 / 255, 172 / 255),
    "LeftArm": (245 / 255, 205 / 255, 48 / 255), "RightArm": (245 / 255, 205 / 255, 48 / 255),
    "LeftLeg": (164 / 255, 189 / 255, 71 / 255), "RightLeg": (164 / 255, 189 / 255, 71 / 255),
}

_R6_LAYOUT = {
    # name: (size, position, attachments {name: position})
    "HumanoidRootPart": ((2, 2, 1), (0, 3, 0), {"RootAttachment": (0, 0, 0)}),
    "Torso": ((2, 2, 1), (0, 3, 0), {
        "NeckAttachment": (0, 1, 0), "BodyFrontAttachment": (0, 0, -0.5),
        "BodyBackAttachment": (0, 0, 0.5), "LeftCollarAttachment": (-1, 1, 0),
        "RightCollarAttachment": (1, 1, 0), "WaistFrontAttachment": (0, -1, -0.5),
        "WaistCenterAttachment": (0, -1, 0), "WaistBackAttachment": (0, -1, 0.5)}),
    "Head": ((2, 1, 1), (0, 4.5, 0), {
        "HatAttachment": (0, 0.6, 0), "HairAttachment": (0, 0.6, 0),
        "FaceFrontAttachment": (0, 0, -0.6), "FaceCenterAttachment": (0, 0, 0)}),
    "Left Arm": ((1, 2, 1), (-1.5, 3, 0), {
        "LeftShoulderAttachment": (0, 1, 0), "LeftGripAttachment": (0, -1, 0)}),
    "Right Arm": ((1, 2, 1), (1.5, 3, 0), {
        "RightShoulderAttachment": (0, 1, 0), "RightGripAttachment": (0, -1, 0)}),
    "Left Leg": ((1, 2, 1), (-0.5, 1, 0), {"LeftFootAttachment": (0, -1, 0)}),
    "Right Leg": ((1, 2, 1), (0.5, 1, 0), {"RightFootAttachment": (0, -1, 0)}),
}


def _new(cls, name, parent=None, **props):
    inst = Instance(cls)
    inst.props["Name"] = name
    inst.props.update(props)
    if parent is not None:
        parent.add_child(inst)
    return inst


def build_r6_document(name="Rig"):
    """A standard R6 character (no Roblox files needed)."""
    model = _new("Model", name)
    _new("Humanoid", "Humanoid", model)
    for pname, (size, pos, atts) in _R6_LAYOUT.items():
        part = _new("Part", pname, model, size=tuple(map(float, size)),
                    CFrame=CFrame(tuple(map(float, pos))), Material=272,
                    Color3uint8=(0.639, 0.635, 0.647))
        if pname == "HumanoidRootPart":
            part.props["Transparency"] = 1.0
        for aname, apos in atts.items():
            _new("Attachment", aname, part, CFrame=CFrame(tuple(map(float, apos))))
        if pname == "Head":
            _new("SpecialMesh", "Mesh", part, MeshType=0, Scale=(1.25, 1.25, 1.25))
            _new("Decal", "face", part, Texture="rbxasset://textures/face.png", Face=5)
    bc = _new("BodyColors", "Body Colors", model)
    for group, col in R6_COLORS.items():
        bc.props[group + "Color3"] = col
    return Document([model], "generated")


def ground_model(model):
    """Move a character so it stands on Y = 0, centred on its HumanoidRootPart
    (Studio's rig files sit wherever they were saved)."""
    parts = [d for d in model.descendants() if d.class_name in ("Part", "MeshPart")
             and isinstance(d.props.get("CFrame"), CFrame)]
    if not parts:
        return
    root = next((p for p in parts if p.name == "HumanoidRootPart"), parts[0])
    bottom = min(p.props["CFrame"].pos[1] - abs(tuple(p.props.get("size", (0, 0, 0)))[1]) / 2.0
                 for p in parts if p.name != "HumanoidRootPart")
    rx, _ry, rz = root.props["CFrame"].pos
    shift = CFrame((-rx, -bottom, -rz))
    for p in parts:
        p.props["CFrame"] = shift * p.props["CFrame"]
    pivot = model.props.get("WorldPivotData")
    if isinstance(pivot, CFrame):
        model.props["WorldPivotData"] = shift * pivot


def load_r15_document():
    """Roblox Studio's own R15 rig (avatar/characterR15.rbxm), standing at the origin."""
    path = assets.studio_file("avatar/characterR15.rbxm")
    if path is None:
        return None
    doc = load_file(path)
    for r in doc.roots:
        if r.class_name == "Model":
            r.props["Name"] = "Rig"
            pose_from_joints(r)
            ground_model(r)
            return doc
    return None


# ---------------------------------------------------------------------------
# Avatars (Roblox web APIs + asset downloads)

ACCESSORY_TYPES = {8, 41, 42, 43, 44, 45, 46, 47, 64, 65, 66, 67, 68, 69, 70, 71, 72}
BODY_PART_TYPES = {27: "Torso", 28: "RightArm", 29: "LeftArm", 30: "LeftLeg", 31: "RightLeg"}


def lookup_user_id(name_or_id):
    from .download import http_get_json
    text = str(name_or_id).strip()
    if text.isdigit():
        return int(text), text
    data = http_get_json("https://users.roblox.com/v1/usernames/users",
                         data={"usernames": [text], "excludeBannedUsers": True})
    users = data.get("data") or []
    if not users:
        raise ValueError("No Roblox user named %r" % text)
    return int(users[0]["id"]), users[0].get("name", text)


def fetch_avatar(user_id):
    from .download import DownloadError, http_get_json
    av = http_get_json("https://avatar.roblox.com/v1/users/%d/avatar" % user_id)
    try:
        v2 = http_get_json("https://avatar.roblox.com/v2/avatar/users/%d/avatar" % user_id)
        if v2.get("bodyColor3s"):
            av["bodyColor3s"] = v2["bodyColor3s"]
    except DownloadError:
        pass
    return av


def _hex(h):
    h = (h or "").lstrip("#")
    if len(h) != 6:
        return None
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _attachment_world(part, att):
    return part.props.get("CFrame", CFrame()) * att.props.get("CFrame", CFrame())


def attach_accessory(model, accessory, adjust=None):
    """Position an Accessory's Handle on the body like Roblox does (matching
    attachment names) and weld it to that body part. `adjust` is Roblox's
    Accessory Adjustment: (position offset studs, rotation degrees, scale),
    applied in the attachment's frame."""
    handle = accessory.find_first_child("Handle")
    if handle is None:
        return False
    if adjust is not None and any(abs(v - 1.0) > 1e-6 for v in adjust[2]):
        _scale_accessory(handle, adjust[2])
    hatt = next((c for c in handle.children if c.class_name == "Attachment"), None)
    parts = [d for d in model.descendants() if d.class_name in ("Part", "MeshPart")
             and d is not handle]
    target = None
    if hatt is not None:
        for p in parts:
            batt = p.find_first_child(hatt.name)
            if batt is not None and batt.class_name == "Attachment":
                target = (p, batt)
                break
    if target is None:
        head = next((p for p in parts if p.name == "Head"), None)
        if head is None:
            return False
        target = (head, None)
        world = head.props.get("CFrame", CFrame()) * CFrame((0.0, 0.6, 0.0))
    else:
        world = _attachment_world(*target)
    if adjust is not None:
        world = world * CFrame(adjust[0], _rotation_from_orientation(adjust[1]))
        accessory.props["RBXAdjusted"] = True
    if hatt is not None:
        handle.props["CFrame"] = world * hatt.props.get("CFrame", CFrame()).inverse()
    else:
        handle.props["CFrame"] = world
    model.add_child(accessory)
    _new("Weld", "AccessoryWeld", handle, Part0=handle, Part1=target[0])
    return True


def _download_model(resolver, asset_id, report):
    path = resolver.resolve("rbxassetid://%s" % asset_id)
    if path is None:
        report.miss("rbxassetid://%s" % asset_id, "avatar")
        return None
    try:
        return load_file(path)
    except Exception as ex:
        report.warnings.append("Asset %s: %s" % (asset_id, ex))
        return None


def _replace_body_part(model, new_part):
    old = model.find_first_child(new_part.name)
    if old is None:
        return
    if old.class_name != "MeshPart":
        # e.g. the template's classic Head (Part + SpecialMesh) -> MeshPart head
        old.class_name = "MeshPart"
        for c in list(old.children):
            if c.class_name in ("SpecialMesh", "FileMesh"):
                c.remove()
    for k in ("MeshId", "MeshID", "TextureID", "TextureId", "size", "InitialSize"):
        if k in new_part.props:
            old.props[k] = new_part.props[k]
    for att in new_part.children:
        if att.class_name == "Attachment":
            mine = old.find_first_child(att.name)
            if mine is not None and mine.class_name == "Attachment":
                mine.props["CFrame"] = att.props.get("CFrame", CFrame())
    sa = new_part.find_first_child_of_class("SurfaceAppearance")
    if sa is not None:
        old.add_child(sa)


def _sync_motors_to_attachments(model):
    for j in [d for d in model.descendants() if d.class_name == "Motor6D"]:
        p0, p1 = j.props.get("Part0"), j.props.get("Part1")
        if not isinstance(p0, Instance) or not isinstance(p1, Instance):
            continue
        name = j.name + "RigAttachment"
        a0, a1 = p0.find_first_child(name), p1.find_first_child(name)
        if a0 is not None and a1 is not None:
            j.props["C0"] = a0.props.get("CFrame", CFrame())
            j.props["C1"] = a1.props.get("CFrame", CFrame())


def _apply_scales(model, scales):
    w = float(scales.get("width", 1.0) or 1.0)
    h = float(scales.get("height", 1.0) or 1.0)
    d = float(scales.get("depth", 1.0) or 1.0)
    hd = float(scales.get("head", 1.0) or 1.0)
    for part in [p for p in model.children if p.class_name in ("Part", "MeshPart")]:
        f = (hd, hd, hd) if part.name == "Head" else (w, h, d)
        if part.name == "HumanoidRootPart":
            f = (w, h, d)
        for k in ("size",):
            if isinstance(part.props.get(k), tuple):
                part.props[k] = tuple(a * b for a, b in zip(part.props[k], f))
        for att in part.children:
            if att.class_name == "Attachment" and isinstance(att.props.get("CFrame"), CFrame):
                att.props["CFrame"] = att.props["CFrame"].scaled_pos(*f)


CHARACTER_MESH_PARTS = {0: "Head", 1: "Torso", 2: "Left Arm", 3: "Right Arm", 4: "Left Leg",
                        5: "Right Leg"}


def apply_character_meshes(model, resolver):
    """R6 body packages: each CharacterMesh in the character swaps a body part
    for the package's mesh (with its base texture under the clothing and its
    overlay texture on top). Parts whose mesh can't be downloaded stay blocks."""
    applied = 0
    for cm in [d for d in model.descendants() if d.class_name == "CharacterMesh"]:
        part_name = CHARACTER_MESH_PARTS.get(cm.props.get("BodyPart"))
        part = model.find_first_child(part_name) if part_name else None
        mesh_id = cm.props.get("MeshId")
        if part is None or part.class_name != "Part" or not mesh_id:
            continue
        content = "rbxassetid://%s" % mesh_id
        if not resolver.resolve_mesh(content):
            continue
        for c in list(part.children):
            if c.class_name in ("SpecialMesh", "FileMesh", "BlockMesh", "CylinderMesh"):
                c.remove()
        sm = _new("SpecialMesh", "CharacterMesh", part, MeshType=5, MeshId=content,
                  Scale=(1.0, 1.0, 1.0))
        base = cm.props.get("BaseTextureId")
        if base:
            sm.props["TextureId"] = "rbxassetid://%s" % base
        overlay = cm.props.get("OverlayTextureId")
        if overlay:
            _new("CharacterMeshOverlay", "Overlay", part, Texture="rbxassetid://%s" % overlay)
        applied += 1
    return applied


def _rotation_from_orientation(deg):
    """Like CFrame.fromOrientation(rx, ry, rz): Y, then X, then Z (degrees)."""
    import math
    rx, ry, rz = (math.radians(a) for a in deg)
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry),
                              math.cos(rz), math.sin(rz))
    X = CFrame(rot=(1, 0, 0, 0, cx, -sx, 0, sx, cx))
    Y = CFrame(rot=(cy, 0, sy, 0, 1, 0, -sy, 0, cy))
    Z = CFrame(rot=(cz, -sz, 0, sz, cz, 0, 0, 0, 1))
    return (Y * X * Z).rot


def accessory_adjustment(asset):
    """Accessory Adjustment (position/rotation/scale) from an avatar API asset
    entry, or None. Accepts the field spellings Roblox's APIs use."""
    meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}

    def vec(names, default):
        for n in names:
            v = meta.get(n)
            if isinstance(v, dict):
                return tuple(float(v.get(a, v.get(a.lower(), d))) for a, d in zip("XYZ", default))
            if isinstance(v, (list, tuple)) and len(v) == 3:
                return tuple(float(x) for x in v)
        return default

    pos = vec(("position", "Position"), (0.0, 0.0, 0.0))
    rot = vec(("rotation", "Rotation"), (0.0, 0.0, 0.0))
    scale = vec(("scale", "Scale"), (1.0, 1.0, 1.0))
    if pos == (0.0, 0.0, 0.0) and rot == (0.0, 0.0, 0.0) and scale == (1.0, 1.0, 1.0):
        return None
    return pos, rot, scale


def _scale_accessory(handle, s):
    for k in ("size",):
        if isinstance(handle.props.get(k), tuple):
            handle.props[k] = tuple(a * b for a, b in zip(handle.props[k], s))
    for c in handle.children:
        if c.class_name in ("SpecialMesh", "FileMesh"):
            c.props["Scale"] = tuple(a * b for a, b in zip(c.props.get("Scale", (1, 1, 1)), s))
            c.props["Offset"] = tuple(a * b for a, b in zip(c.props.get("Offset", (0, 0, 0)), s))
        elif c.class_name == "Attachment" and isinstance(c.props.get("CFrame"), CFrame):
            c.props["CFrame"] = c.props["CFrame"].scaled_pos(*s)


def _drop_classic_face(head):
    """Dynamic heads have their face in the head texture; remove the Decal face."""
    for c in list(head.children):
        if c.class_name == "Decal" and c.name.lower() == "face":
            c.remove()


def apply_head_mesh(head, sm, resolver):
    """Use a head asset's SpecialMesh (classic or dynamic head) on the Head.
    Only switches when the mesh file is available, so the classic head stays
    if it can't be downloaded. Returns True if applied."""
    mesh_id = sm.get("MeshId", "MeshID", default="")
    if not isinstance(mesh_id, str) or not resolver.resolve_mesh(mesh_id):
        return False
    old = head.find_first_child_of_class("SpecialMesh")
    if old is not None:
        old.remove()
    # Head assets carry their attachment positions as Vector3Values
    for v in [c for c in sm.children if c.class_name == "Vector3Value" and c.name.endswith("Attachment")]:
        pos = v.props.get("Value")
        if not isinstance(pos, tuple):
            continue
        att = head.find_first_child(v.name)
        if att is None or att.class_name != "Attachment":
            att = _new("Attachment", v.name, head)
        cf = att.props.get("CFrame") if isinstance(att.props.get("CFrame"), CFrame) else CFrame()
        att.props["CFrame"] = CFrame(pos, cf.rot)
    sm.remove()
    head.add_child(sm)
    tex = sm.get("TextureId", "TextureID", default="")
    if isinstance(tex, str) and tex.strip() and resolver.resolve_image(tex):
        _drop_classic_face(head)
    return True


def build_avatar_document(name_or_id, resolver, report, rig_type="AUTO"):
    """Assemble a user's avatar as a Roblox document. Clothing, faces and
    accessories need asset downloads (Open Cloud API key)."""
    user_id, user_name = lookup_user_id(name_or_id)
    av = fetch_avatar(user_id)
    avatar_type = av.get("playerAvatarType", "R15")
    if rig_type != "AUTO":
        avatar_type = rig_type
    if avatar_type == "R15":
        doc = load_r15_document()
        if doc is None:
            report.warnings.append("Roblox Studio's R15 rig wasn't found; using R6 instead")
            doc = build_r6_document()
            avatar_type = "R6"
    else:
        doc = build_r6_document()
    model = next(r for r in doc.roots if r.class_name == "Model")
    model.props["Name"] = user_name

    # Body colors
    bc = model.find_first_child_of_class("BodyColors") or _new("BodyColors", "Body Colors", model)
    c3 = av.get("bodyColor3s") or {}
    for group, key in (("Head", "headColor3"), ("Torso", "torsoColor3"),
                       ("LeftArm", "leftArmColor3"), ("RightArm", "rightArmColor3"),
                       ("LeftLeg", "leftLegColor3"), ("RightLeg", "rightLegColor3")):
        col = _hex(c3.get(key))
        if col is None:
            num = (av.get("bodyColors") or {}).get(key.replace("Color3", "ColorId"))
            if isinstance(num, int):
                from .rbx.enums import brick_color
                col = brick_color(num)
        if col is not None:
            bc.props[group + "Color3"] = col

    head = model.find_first_child("Head")
    asset_list = av.get("assets") or []
    resolver.prefetch(["rbxassetid://%s" % a["id"] for a in asset_list])
    needs_login = []  # names of items whose files couldn't be downloaded

    def missing(a, what=""):
        needs_login.append((a.get("name") or str(a.get("id"))) + what)

    # Heads and body parts first, so accessories attach to the final head/body
    head_types = set(BODY_PART_TYPES) | {17, 79}
    body_final = [False]

    def finish_body():
        # R15 scaling/posing must happen before accessories are attached
        if body_final[0]:
            return
        body_final[0] = True
        if avatar_type == "R15":
            _apply_scales(model, av.get("scales") or {})
            _sync_motors_to_attachments(model)
            pose_from_joints(model)

    def order(a):
        t = (a.get("assetType") or {}).get("id")
        return 0 if t in head_types else (2 if t in ACCESSORY_TYPES else 1)

    for a in sorted(asset_list, key=order):
        aid = a.get("id")
        tid = (a.get("assetType") or {}).get("id")
        content = "rbxassetid://%s" % aid
        if tid in ACCESSORY_TYPES:
            finish_body()
        if tid in (11, 12, 2):
            cls, prop, label = {11: ("Shirt", "ShirtTemplate", "Shirt"),
                                12: ("Pants", "PantsTemplate", "Pants"),
                                2: ("ShirtGraphic", "Graphic", "Shirt Graphic")}[tid]
            _new(cls, label, model, **{prop: content})
            if resolver.resolve_image(content) is None:
                missing(a)
        elif tid == 18 and head is not None:
            face = head.find_first_child("face") or _new("Decal", "face", head, Face=5)
            face.props["Texture"] = content
            if resolver.resolve_image(content) is None:
                missing(a)
        elif tid in ACCESSORY_TYPES:
            adoc = _download_model(resolver, aid, report)
            if adoc is None:
                missing(a)
                continue
            adjust = accessory_adjustment(a)
            if adjust is not None:
                report.count("adjusted accessories")
            for inst in adoc.all_instances():
                if inst.class_name in ("Accessory", "Accoutrement", "Hat"):
                    inst.remove()
                    if not attach_accessory(model, inst, adjust):
                        report.warnings.append("Couldn't attach accessory %s" % a.get("name"))
                    break
        elif tid in head_types:
            pdoc = _download_model(resolver, aid, report)
            if pdoc is None:
                missing(a)
                continue
            folder = None
            for fname in ("R15ArtistIntent", "R15Fixed", "R15"):
                folder = next((i for i in pdoc.all_instances()
                               if i.class_name == "Folder" and i.name == fname), None)
                if folder is not None:
                    break
            meshparts = [p for p in (folder.children if folder is not None else pdoc.all_instances())
                         if p.class_name == "MeshPart"]
            sm = next((i for i in pdoc.all_instances() if i.class_name == "SpecialMesh"), None)
            r6_meshes = [i for i in pdoc.all_instances() if i.class_name == "CharacterMesh"]
            if avatar_type == "R6" and r6_meshes and tid in BODY_PART_TYPES:
                for cm in r6_meshes:
                    if resolver.resolve_mesh("rbxassetid://%s" % cm.props.get("MeshId")):
                        cm.remove()
                        model.add_child(cm)
                    else:
                        missing(a, " (R6 mesh)")
            elif avatar_type == "R15" and meshparts:
                for p in meshparts:
                    if resolver.resolve_mesh(p.get("MeshId", "MeshID", default="")):
                        _replace_body_part(model, p)
                    else:
                        missing(a, " (%s mesh)" % p.name)
            elif sm is not None and head is not None and tid in (17, 79):
                if not apply_head_mesh(head, sm, resolver):
                    missing(a, " (head mesh)")
            elif meshparts and head is not None and tid in (17, 79):
                hp = next((p for p in meshparts if p.name == "Head"), meshparts[0])
                if resolver.resolve_mesh(hp.get("MeshId", "MeshID", default="")):
                    hp.props["Name"] = "Head"
                    _replace_body_part(model, hp)
                    _drop_classic_face(head)
                else:
                    missing(a, " (head mesh)")
    report.avatar_needs_login = needs_login

    finish_body()
    ground_model(model)
    return doc, user_name, avatar_type
