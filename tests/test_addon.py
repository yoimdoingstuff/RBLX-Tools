"""End-to-end tests for RBLX Tools. Run with Blender (no UI needed):

    blender --background --factory-startup --python tests/test_addon.py

Prints PASS/FAIL/SKIP per check and a failure count at the end. Optional
checks use (when present) the Moon/Eclipse Animator .rbxm files in the repo
root, Roblox Studio's install and cache, and the network (public Roblox APIs)."""

import glob
import math
import os
import struct
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="rblx_tools_test_")
sys.path.insert(0, REPO)

import bpy
from mathutils import Vector

FAILS = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def skip(msg):
    print("SKIP  " + msg)


def T(v):
    return str(tuple(round(x, 3) for x in v))


def close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for x, y in zip(a, b))


bpy.ops.wm.read_factory_settings(use_empty=True)
import rblx_tools
from rblx_tools import assets as A, character as CH, importer as I, materials as M
from rblx_tools import operators as OPS, draco
from rblx_tools.rbx import CFrame, mesh as rbxmesh
from rblx_tools.rbx.color import to_linear

rblx_tools.register()
scene = bpy.context.scene
print("registered")

# Keep the test's asset library out of the real Blender config
TEST_LIBRARY = os.path.join(SCRATCH, "library")
A._default_library_dir = lambda: (os.makedirs(TEST_LIBRARY, exist_ok=True), TEST_LIBRARY)[1]


def select_only(*objs):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def render_pixels(res=32):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = scene.render.resolution_y = res
    out = os.path.join(SCRATCH, "render.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(out, check_existing=False)
    px = list(img.pixels)
    bpy.data.images.remove(img)
    return lambda x, y: px[(y * res + x) * 4:(y * res + x) * 4 + 3]


def front_camera(dist=10.0):
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0, -dist, 0)  # Blender front view = Roblox front (-Z)
    cam.rotation_euler = (math.pi / 2, 0, 0)
    bpy.context.scene.camera = cam
    return cam


# ---------------------------------------------------------------- parts
for shape in ("BLOCK", "BALL", "CYLINDER", "WEDGE", "CORNER_WEDGE", "TRUSS", "HEAD"):
    res = bpy.ops.rblx.add_part(shape=shape)
    obj = bpy.context.active_object
    check(res == {"FINISHED"} and obj.rblx.kind == "PART" and len(obj.data.polygons) > 0,
          "add_part %s -> %d faces" % (shape, len(obj.data.polygons)))

bpy.ops.rblx.add_part(shape="BLOCK")
p = bpy.context.active_object
p.rblx.size = (4.0, 1.0, 2.0)
check(close(p.dimensions, (4.0, 2.0, 1.0)), "Block size (4,1,2) studs -> Blender dims %s" % T(p.dimensions))
p.rblx.position = (1.0, 2.0, 3.0)
bpy.context.view_layer.update()
check(close(p.location, (-1.0, 3.0, 2.0)), "Roblox pos (1,2,3) -> Blender %s" % T(p.location))
check(close(p.rblx.position, (1.0, 2.0, 3.0)), "Position round-trip %s" % T(p.rblx.position))
p.rblx.orientation = (10.0, 20.0, 30.0)
bpy.context.view_layer.update()
check(close(p.rblx.orientation, (10.0, 20.0, 30.0), 1e-2), "Orientation round-trip %s" % T(p.rblx.orientation))
p.rblx.shape = "CYLINDER"
p.rblx.size = (6.0, 2.0, 2.0)
bpy.context.view_layer.update()
check(close(p.dimensions, (6.0, 2.0, 2.0), 1e-2), "Cylinder runs along X: dims %s" % T(p.dimensions))
p.rblx.material = "Neon"
check(p.material_slots[0].material.name == "RBX Neon", "Material switch -> RBX Neon")
p.rblx.brick_color = "7"  # Bright red
check(close(p.rblx.color, to_linear((196 / 255, 40 / 255, 28 / 255))) and p.rblx.brick_color == "7",
      "BrickColor picker sets Color (stored linear) and reads back")
p.rblx.color = (1.0, 0.0, 0.0)
p.rblx.transparency = 0.25
check(close(p.color, (1.0, 0.0, 0.0, 0.75)), "obj.color synced %s" % T(p.color))
p.rblx.keyframe_insert("color", frame=1)
check(p.animation_data is not None, "Color is keyframeable")

# Studio-style multi-edit
bpy.ops.rblx.add_part(shape="BLOCK")
a = bpy.context.active_object
bpy.ops.rblx.add_part(shape="BLOCK")
b = bpy.context.active_object
select_only(a, b)
a.rblx.color = (0.0, 0.0, 1.0)
a.rblx.material = "Wood"
a.rblx.size = (1.0, 5.0, 1.0)
check(close(b.rblx.color, (0, 0, 1)) and b.rblx.material == "Wood" and close(b.rblx.size, (1, 5, 1)),
      "Editing the active part edits all selected (Color, Material, Size)")
scene.rblx.edit_all_selected = False
a.rblx.color = (1.0, 1.0, 0.0)
check(close(b.rblx.color, (0, 0, 1)), "Multi-edit can be turned off")
scene.rblx.edit_all_selected = True

# ---------------------------------------------------------------- lighting
for preset in ("DEFAULT", "CLASSIC", "SUNSET", "NIGHT", "FOGGY"):
    bpy.ops.rblx.lighting_preset(preset=preset)
check(bpy.data.objects.get("RBX Sun") is not None and scene.world.name == "RBX World",
      "Lighting presets create sun + world")
L = scene.rblx_lighting
L.fog_end = 100000
L.clock_time = 12.0
sun_dir = bpy.data.objects["RBX Sun"].matrix_world.to_3x3() @ Vector((0, 0, 1))
check(sun_dir.z > 0.5, "Noon sun is high (z=%.2f)" % sun_dir.z)
L.clock_time = 0.0
check(bpy.data.objects["RBX Sun"].data.energy == 0.0 and bpy.data.objects["RBX Moon"].data.energy > 0,
      "Midnight: sun off, moon on")
L.clock_time = 14.5

# ---------------------------------------------------------------- Draco meshes
draco_ok = draco.available()
check(draco_ok, "Blender's Draco decoder found (%s)" % (draco.load_error() or "ok"))
storage = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "rbx-storage")
real_mesh = None
for path in glob.glob(os.path.join(storage, "*", "*"))[:400]:
    with open(path, "rb") as f:
        data = f.read()
    i = data.find(b"version 7.00", 0, 64)
    if i >= 0:
        real_mesh = data[i:]
        break
assets_dir = os.path.join(SCRATCH, "assets")
os.makedirs(assets_dir, exist_ok=True)
if real_mesh and draco_ok:
    md = rbxmesh.read_mesh(real_mesh)
    check(len(md.positions) > 0 and len(md.faces) > 0 and len(md.uvs) == len(md.positions),
          "Draco v7 mesh from Studio cache: %d verts, %d tris" % (len(md.positions), len(md.faces)))
    with open(os.path.join(assets_dir, "3333333.mesh"), "wb") as fh:
        fh.write(real_mesh)
else:
    skip("No Roblox Studio cache with v7 meshes on this machine")

# ---------------------------------------------------------------- test assets
verts = [(-1, -1, -1), (1, -1, -1), (0, 1, -1), (0, 0, 1)]
faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
blob = b"version 2.00\n" + struct.pack("<HBBII", 12, 36, 12, len(verts), len(faces))
for v in verts:
    blob += struct.pack("<9f", *v, 0, 1, 0, 0.5, 0.5, 0)
for f in faces:
    blob += struct.pack("<3I", *f)
with open(os.path.join(assets_dir, "1111111.mesh"), "wb") as fh:
    fh.write(blob)


def save_png(name, w, h, pixel_fn):
    img = bpy.data.images.new(name, w, h, alpha=True)
    px = []
    for y in range(h):
        for x in range(w):
            px.extend(pixel_fn(x, y))
    img.pixels = px
    img.filepath_raw = os.path.join(assets_dir, name + ".png")
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return os.path.join(assets_dir, name + ".png")


save_png("Smiley_2222222", 4, 4, lambda x, y: (0.0, 0.5, 1.0, 1.0))
red_png = save_png("red", 8, 8, lambda x, y: (1.0, 0.0, 0.0, 1.0))
white_png = save_png("white", 8, 8, lambda x, y: (1.0, 1.0, 1.0, 1.0))
# Roblox-style overlay: transparent left half, opaque white right half
half_png = save_png("halfmask", 16, 16, lambda x, y: (1.0, 1.0, 1.0, 1.0 if x >= 8 else 0.0))
# A Shirt asset model whose ShirtTemplate points at an image asset
save_png("5000002", 4, 4, lambda x, y: (1.0, 0.0, 1.0, 1.0))
with open(os.path.join(assets_dir, "5000001.rbxmx"), "w") as fh:
    fh.write('<roblox version="4"><Item class="Shirt" referent="A"><Properties>'
             '<string name="Name">Shirt</string><Content name="ShirtTemplate"><url>'
             'rbxassetid://5000002</url></Content></Properties></Item></roblox>')

resolver = A.AssetResolver([assets_dir], use_studio=True, downloader=None, use_cache=False)
check(resolver.resolve_image("rbxassetid://5000001", ).endswith("5000002.png"),
      "Shirt asset id is followed to its ShirtTemplate image")

place = """<roblox version="4">
<Item class="Workspace" referent="W"><Properties><string name="Name">Workspace</string></Properties>
 <Item class="Model" referent="M"><Properties><string name="Name">House</string>
   <OptionalCoordinateFrame name="WorldPivotData"><CFrame><X>0</X><Y>5</Y><Z>0</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CFrame></OptionalCoordinateFrame>
  </Properties>
  <Item class="Part" referent="P1"><Properties><string name="Name">Wall</string>
   <CoordinateFrame name="CFrame"><X>10</X><Y>5</Y><Z>-4</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>
   <Vector3 name="size"><X>8</X><Y>10</Y><Z>1</Z></Vector3>
   <Color3uint8 name="Color3uint8">4294901760</Color3uint8>
   <token name="Material">512</token><token name="shape">1</token></Properties>
   <Item class="Decal" referent="D1"><Properties><string name="Name">Smiley</string>
    <Content name="Texture"><url>rbxassetid://2222222</url></Content><token name="Face">5</token>
    <Color3 name="Color3"><R>1</R><G>1</G><B>1</B></Color3></Properties></Item>
   <Item class="Texture" referent="T1"><Properties><string name="Name">Bricks</string>
    <Content name="Texture"><url>rbxassetid://2222222</url></Content><token name="Face">2</token>
    <float name="StudsPerTileU">2</float><float name="StudsPerTileV">2</float></Properties></Item>
   <Item class="SurfaceLight" referent="L1"><Properties><string name="Name">Glow</string>
    <float name="Brightness">2</float><float name="Range">16</float><token name="Face">5</token></Properties></Item>
  </Item>
  <Item class="WedgePart" referent="P2"><Properties><string name="Name">Roof</string>
   <CoordinateFrame name="CFrame"><X>0</X><Y>12</Y><Z>0</Z><R00>0</R00><R01>0</R01><R02>1</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>-1</R20><R21>0</R21><R22>0</R22></CoordinateFrame>
   <Vector3 name="size"><X>4</X><Y>2</Y><Z>6</Z></Vector3><BrickColor name="BrickColor">21</BrickColor></Properties></Item>
  <Item class="MeshPart" referent="P3"><Properties><string name="Name">Gem</string>
   <CoordinateFrame name="CFrame"><X>0</X><Y>3</Y><Z>0</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>
   <Vector3 name="size"><X>4</X><Y>4</Y><Z>4</Z></Vector3><Vector3 name="InitialSize"><X>2</X><Y>2</Y><Z>2</Z></Vector3>
   <Content name="MeshId"><url>rbxassetid://1111111</url></Content>
   <Content name="TextureID"><url>rbxassetid://2222222</url></Content></Properties></Item>
  <Item class="MeshPart" referent="P6"><Properties><string name="Name">RealMesh</string>
   <Vector3 name="size"><X>3</X><Y>3</Y><Z>3</Z></Vector3><Vector3 name="InitialSize"><X>3</X><Y>3</Y><Z>3</Z></Vector3>
   <Content name="MeshId"><url>rbxassetid://3333333</url></Content></Properties></Item>
  <Item class="MeshPart" referent="P4"><Properties><string name="Name">MissingMesh</string>
   <Vector3 name="size"><X>1</X><Y>1</Y><Z>1</Z></Vector3>
   <Content name="MeshId"><url>rbxassetid://9999999</url></Content></Properties></Item>
  <Item class="Part" referent="P5"><Properties><string name="Name">Ball</string>
   <Vector3 name="size"><X>3</X><Y>3</Y><Z>3</Z></Vector3><token name="shape">0</token><token name="Material">288</token></Properties>
   <Item class="PointLight" referent="L2"><Properties><string name="Name">Lamp</string></Properties></Item>
  </Item>
 </Item>
 <Item class="Script" referent="S"><Properties><string name="Name">Ignore me</string></Properties></Item>
</Item>
<Item class="Lighting" referent="LT"><Properties><string name="Name">Lighting</string>
 <string name="TimeOfDay">17:30:00</string><float name="Brightness">2.5</float><float name="FogEnd">500</float></Properties>
 <Item class="Atmosphere" referent="AT"><Properties><string name="Name">Atmosphere</string><float name="Density">0.35</float></Properties></Item>
</Item>
<Item class="MaterialService" referent="MS"><Properties><string name="Name">MaterialService</string>
 <bool name="Use2022Materials">false</bool></Properties></Item>
</roblox>"""
place_path = os.path.join(SCRATCH, "test_place.rbxlx")
with open(place_path, "w", encoding="utf-8") as fh:
    fh.write(place)

# ---------------------------------------------------------------- import place
res = bpy.ops.import_scene.rblx(filepath=place_path, asset_folder=assets_dir, download=False)
check(res == {"FINISHED"}, "Import test place")
O = bpy.data.objects
wall, roof, gem, missing, house = (O.get(n) for n in ("Wall", "Roof", "Gem", "MissingMesh", "House"))
check(all(x is not None for x in (wall, roof, gem, missing, house)), "All parts + model created")
bpy.context.view_layer.update()
check(wall.parent == house and close(wall.matrix_world.translation, (-10, -4, 5)),
      "Wall parented to House at %s" % T(wall.matrix_world.translation))
check(close(wall.dimensions, (8, 1, 10)), "Wall dims %s" % T(wall.dimensions))
names = [(l.kind, l.mapping, l.face, l.image is not None) for l in wall.rblx.layers]
check(("Decal", "FACE", "FRONT", True) in names and ("Texture", "TILED", "BACK", True) in names,
      "Decal + Texture became layers on the wall: %s" % names)
check(wall.rblx.material_mode == "LAYERED" and wall.material_slots[0].material.get("rblx_layered"),
      "Wall got a layered material")
check(close(roof.rblx.color, to_linear((196 / 255, 40 / 255, 28 / 255))) and roof.rblx.shape == "WEDGE",
      "Roof: BrickColor 21 wedge (Roblox sRGB colour converted to linear)")
fog = O.get("RBX Fog Volume")
check(fog is not None and not fog.hide_render and not fog.visible_shadow,
      "Fog is a volume box that doesn't block sunlight")
check(close(roof.rblx.orientation, (0, 90, 0), 1e-2), "Roof orientation %s" % T(roof.rblx.orientation))
check(gem.rblx.shape == "MESH" and len(gem.data.polygons) == 4, "MeshPart .mesh v2 loaded")
check(close(gem.dimensions, (4, 4, 4), 1e-2), "MeshPart scaled to Size: %s" % T(gem.dimensions))
check(any(l.kind == "TextureID" and l.mapping == "UV" and l.image for l in gem.rblx.layers),
      "MeshPart TextureID -> UV texture layer")
# Decals on meshes wrap with the mesh UVs (Roblox ignores Face there)
hl = M.add_layer(gem, M.load_image(os.path.join(assets_dir, "Smiley_2222222.png")), "FACE",
                 "highlights", "Decal", "", "RIGHT")
nodes = gem.material_slots[0].material.node_tree.nodes
check(M.decal_wraps(gem, hl) and not any(n.bl_idname == "ShaderNodeVectorTransform" for n in nodes)
      and sum(1 for n in nodes if n.bl_idname == "ShaderNodeUVMap") >= 2,
      "Decal on a mesh part wraps by UV instead of projecting onto one face")
check(not M.decal_wraps(wall, wall.rblx.layers[0]), "Decal on a block still goes on its face")
prop = bpy.ops.import_scene.rblx.get_rna_type().properties["filepath"]
check(prop.is_skip_save, "Import doesn't remember the last file (no repeat imports)")
real = O.get("RealMesh")
if real_mesh and draco_ok:
    check(real is not None and len(real.data.polygons) > 4 and not real.rblx.asset_missing
          and close(real.dimensions, (3, 3, 3), 1e-2),
          "MeshPart with a Draco v7 mesh imports (%d faces, dims %s)"
          % (len(real.data.polygons), T(real.dimensions)))
check(missing.rblx.asset_missing and len(missing.data.polygons) == 6, "Missing mesh -> flagged box")
check(O.get("Glow") is not None and O.get("Lamp") is not None, "Lights imported")
check(O.get("Ignore me") is None, "Scripts skipped")
check(abs(L.clock_time - 17.5) < 1e-3 and L.fog_end == 500, "Lighting loaded from place")
report = bpy.data.texts["RBX Import Report"].as_string()
check("rbxassetid://9999999" in report, "Report lists the missing asset")
check(not bpy.context.scene.rblx.use_2022_materials and
      wall.material_slots[0].material.get("rblx_style") == "LEGACY",
      "MaterialService.Use2022Materials=false imported (legacy materials)")

with open(os.path.join(assets_dir, "9999999.mesh"), "wb") as fh:
    fh.write(blob)
ok = I.reload_part_mesh(missing, A.AssetResolver([assets_dir], use_cache=False))
check(ok and len(missing.data.polygons) == 4, "Reload missing mesh after adding the file")

# ---------------------------------------------------------------- texture layers: render checks
bpy.ops.wm.read_factory_settings(use_empty=True)
rblx_tools.unregister()
rblx_tools.register()
scene = bpy.context.scene
bpy.ops.rblx.lighting_preset(preset="CLASSIC")
part = OPS.create_part(bpy.context, "BLOCK", size=(8, 8, 1))
part.rblx.color = (0.0, 1.0, 0.0)
part.rblx.material = "SmoothPlastic"
front_camera()
px = render_pixels()
c = px(16, 16)
check(c[1] > 2 * c[0] and c[1] > 2 * c[2], "Plain part renders green %s" % T(c))

img = M.load_image(red_png)
layer = M.add_layer(part, img, "FACE", "red decal", "Decal", red_png, "FRONT")
px = render_pixels()
c = px(16, 16)
check(c[0] > 2 * c[1] and c[0] > 2 * c[2], "Decal on the front face renders red %s" % T(c))
layer.face = "BACK"
px = render_pixels()
c = px(16, 16)
check(c[1] > 2 * c[0], "Decal moved to the back face: front is green again %s" % T(c))

part.rblx.layers.clear()
M.refresh(part)
img = M.load_image(half_png)
layer = M.add_layer(part, img, "FACE", "overlay", "Image", half_png, "FRONT")
layer.color = (0.0, 0.0, 1.0)  # recolour the texture separately from the part
px = render_pixels()
left, right = px(8, 16), px(24, 16)
blue_side = left if left[2] > left[1] else right
green_side = right if blue_side is left else left
check(blue_side[2] > 2 * blue_side[1] and green_side[1] > 2 * green_side[2],
      "Transparent texture: tinted blue where opaque, part green shows where clear %s %s"
      % (T(left), T(right)))
layer.transparency = 1.0
px = render_pixels()
c = px(8, 16)
d = px(24, 16)
check(c[1] > 2 * c[2] and d[1] > 2 * d[2], "Layer Transparency=1 hides it")

# UV wrap on a mesh-style part + tiled
part.rblx.layers.clear()
img = M.load_image(white_png)
layer = M.add_layer(part, img, "UV", "wrap", "Image", white_png)
layer.color = (1.0, 0.0, 1.0)
px = render_pixels()
c = px(16, 16)
check(c[0] > 2 * c[1] and c[2] > 2 * c[1], "UV wrap layer tinted magenta %s" % T(c))
layer.mapping = "TILED"
check(part.material_slots[0].material.get("rblx_layered"), "Switching mapping rebuilds material")

# layer operators
select_only(part)
res = bpy.ops.rblx.layer_add(filepath=red_png, mapping="FACE", face="TOP")
check(res == {"FINISHED"} and part.rblx.layers[-1].face == "TOP", "Add Texture operator")
n = len(part.rblx.layers)
part.rblx.active_layer = n - 1
bpy.ops.rblx.layer_move(direction="DOWN")
check(part.rblx.layers[n - 2].face == "TOP", "Move layer")
bpy.ops.rblx.layer_make_unique()
check(part.rblx.layers[part.rblx.active_layer].image.packed_file is not None, "Make image unique")
bpy.ops.rblx.layer_remove()
check(len(part.rblx.layers) == n - 1, "Remove layer")

# ---------------------------------------------------------------- characters
bpy.ops.wm.read_factory_settings(use_empty=True)
rblx_tools.unregister()
rblx_tools.register()
scene = bpy.context.scene
res = bpy.ops.rblx.add_character(rig_type="R6")
check(res == {"FINISHED"}, "Add R6 character")
rig = next((o for o in bpy.data.objects if o.rblx.kind == "RIG"), None)
check(rig is not None and len(rig.data.bones) == 7,
      "R6 rig has 7 bones: %s" % (sorted(b.name for b in rig.data.bones) if rig else None))
arm = bpy.data.objects.get("Right Arm")
torso = bpy.data.objects.get("Torso")
check(arm is not None and arm.parent == rig and arm.parent_bone == "Right Arm", "Arm parented to its bone")
bpy.context.view_layer.update()
check(close(arm.matrix_world.translation, (-1.5, 0.0, 3.0)),
      "Right Arm at rest on the character's right (Blender -X when facing -Y) %s"
      % T(arm.matrix_world.translation))
check(close(torso.rblx.color, to_linear((13 / 255, 105 / 255, 172 / 255))), "BodyColors applied (blue torso)")
check(abs(torso.rblx.bevel - 0.065) < 1e-6 and len(torso.data.polygons) > 6,
      "R6 body parts get Roblox's rounded edges (%d faces)" % len(torso.data.polygons))
head = bpy.data.objects.get("Head")
check(head is not None and any(l.name == "face" and l.image is not None for l in head.rblx.layers),
      "Head has a face (classic face fallback)")
check(head.rblx.shape in ("MESH", "HEAD") and head.dimensions.x < 1.6, "Classic head shape %s" % T(head.dimensions))
pb = rig.pose.bones["Right Arm"]
pb.rotation_mode = "XYZ"
pb.rotation_euler = (0.0, 0.0, math.radians(90))
bpy.context.view_layer.update()
moved = not close(arm.matrix_world.translation, (-1.5, 0.0, 3.0))
check(moved, "Posing the Right Arm bone moves the arm part -> %s" % T(arm.matrix_world.translation))
pb.rotation_euler = (0, 0, 0)

# clothing via operator
shirt_png = save_png("shirt", 585, 559, lambda x, y: (1.0, 0.2, 0.2, 1.0))
select_only(torso)
res = bpy.ops.rblx.apply_clothing(filepath=shirt_png, kind="SHIRT")
check(res == {"FINISHED"} and any(l.kind == "Shirt" for l in torso.rblx.layers)
      and torso.data.uv_layers.get("RBX_Template_TORSO") is not None, "Shirt on R6 torso with template UVs")
la = bpy.data.objects["Left Arm"]
check(any(l.kind == "Shirt" and l.template_region == "LEFT_LIMB" for l in la.rblx.layers),
      "Shirt on left arm uses the left-arm template area")
res = bpy.ops.rblx.apply_clothing(filepath=shirt_png, kind="PANTS")
kinds = [l.kind for l in torso.rblx.layers]
check(kinds.index("Pants") < kinds.index("Shirt"), "Pants go under the shirt: %s" % kinds)

# accessories positioning (document level)
doc = CH.build_r6_document()
model = doc.roots[0]
from rblx_tools.rbx import Instance
acc = Instance("Accessory")
acc.props["Name"] = "Hat"
handle = Instance("Part")
handle.props.update(Name="Handle", size=(1.0, 1.0, 1.0))
acc.add_child(handle)
hatt = Instance("Attachment")
hatt.props.update(Name="HatAttachment", CFrame=CFrame((0.0, -0.3, 0.0)))
handle.add_child(hatt)
check(CH.attach_accessory(model, acc) and close(handle.props["CFrame"].pos, (0, 5.4, 0)),
      "Accessory placed by matching HatAttachment: %s" % T(handle.props["CFrame"].pos))
# v1 text meshes keep their UVs as stored (v2+ are flipped)
v1 = b"version 1.00\n1\n[0,0,0][0,1,0][0.1,0.25,0][2,0,0][0,1,0][0.9,0.25,0][0,2,0][0,1,0][0.5,0.75,0]"
md1 = rbxmesh.read_mesh(v1)
check(close(md1.uvs[0], (0.1, 0.25)) and close(md1.positions[1], (1.0, 0.0, 0.0)),
      "v1 mesh: UVs not flipped, positions halved (%s)" % (md1.uvs[0],))

# Accessory Adjustment: offset/rotation/scale in the attachment's frame
doc_a = CH.build_r6_document()
acc2 = Instance("Accessory")
acc2.props["Name"] = "Adjusted"
h2 = Instance("Part")
h2.props.update(Name="Handle", size=(1.0, 1.0, 1.0))
acc2.add_child(h2)
a2 = Instance("Attachment")
a2.props.update(Name="HatAttachment", CFrame=CFrame((0.0, -0.3, 0.0)))
h2.add_child(a2)
adj = CH.accessory_adjustment({"meta": {"position": {"X": 0, "Y": 0.2, "Z": 0},
                                        "rotation": {"X": 0, "Y": 90, "Z": 0},
                                        "scale": {"X": 2, "Y": 2, "Z": 2}}})
CH.attach_accessory(doc_a.roots[0], acc2, adj)
cf2 = h2.props["CFrame"]
check(adj is not None and close(cf2.pos, (0, 5.4 + 0.2 + 0.3, 0), 1e-4) and close(h2.props["size"], (2, 2, 2))
      and abs(cf2.rot[2] - 1.0) < 1e-6,
      "Accessory Adjustment applies offset, 90deg turn and 2x scale: pos %s" % T(cf2.pos))
check(CH.accessory_adjustment({"meta": {"order": 1}}) is None and CH.accessory_adjustment({}) is None,
      "No adjustment when the avatar has none")

# R6 body package (CharacterMesh) swaps a block for the package mesh
doc_p = CH.build_r6_document()
cm = Instance("CharacterMesh")
cm.props.update(Name="CharacterMesh", BodyPart=1, MeshId=1111111, BaseTextureId=2222222, OverlayTextureId=0)
doc_p.roots[0].add_child(cm)
cm2 = Instance("CharacterMesh")
cm2.props.update(Name="CharacterMesh", BodyPart=2, MeshId=987654321987)  # not downloadable
doc_p.roots[0].add_child(cm2)
n_applied = CH.apply_character_meshes(doc_p.roots[0], local if "local" in dir() else
                                      A.AssetResolver([assets_dir], use_cache=False))
t_sm = doc_p.roots[0].find_first_child("Torso").find_first_child_of_class("SpecialMesh")
check(n_applied == 1 and t_sm is not None and t_sm.props["MeshId"].endswith("1111111")
      and t_sm.props["TextureId"].endswith("2222222")
      and doc_p.roots[0].find_first_child("Left Arm").find_first_child_of_class("SpecialMesh") is None,
      "R6 body package mesh applied; parts whose mesh can't download stay blocks")

# Dynamic/classic head assets (SpecialMesh + face texture + attachment Vector3Values)
local = A.AssetResolver([assets_dir], use_cache=False)
doc_h = CH.build_r6_document()
head_i = doc_h.roots[0].find_first_child("Head")
missing_sm = Instance("SpecialMesh")
missing_sm.props.update(Name="Mesh", MeshType=5, MeshId="rbxassetid://424242424242")
check(not CH.apply_head_mesh(head_i, missing_sm, local) and head_i.find_first_child("face") is not None,
      "Head asset whose mesh can't be downloaded keeps the classic head and face")
sm = Instance("SpecialMesh")
sm.props.update(Name="Mesh", MeshType=5, MeshId="rbxassetid://1111111", TextureId="rbxassetid://2222222")
v = Instance("Vector3Value")
v.props.update(Name="HairAttachment", Value=(0.0, 0.9, 0.1))
sm.add_child(v)
ok = CH.apply_head_mesh(head_i, sm, local)
hair_att = head_i.find_first_child("HairAttachment")
check(ok and head_i.find_first_child_of_class("SpecialMesh").props["MeshId"].endswith("1111111")
      and head_i.find_first_child("face") is None and close(hair_att.props["CFrame"].pos, (0, 0.9, 0.1)),
      "Dynamic head: mesh + face texture replace the classic face, attachments move")

imp = I.Importer(bpy.context, I.ImportOptions(allow_download=False))
imp.run_document(doc, "WithHat")
hat_handle = next(o for o in imp.collection.objects if o.name.startswith("Handle"))
hat_obj = hat_handle.parent
rig2 = next(o for o in imp.collection.objects if o.rblx.kind == "RIG")
check(hat_obj.parent == rig2 and hat_obj.parent_bone == "Head", "Accessory follows the Head bone")

# R15 from Studio
r15 = CH.load_r15_document()
if r15 is not None:
    res = bpy.ops.rblx.add_character(rig_type="R15")
    rig15 = bpy.context.active_object
    check(res == {"FINISHED"} and rig15.rblx.kind == "RIG" and len(rig15.data.bones) == 16,
          "R15 rig from Studio: %d bones" % len(rig15.data.bones))
    bpy.context.view_layer.update()
    r15_parts = [o for o in bpy.data.objects if o.rblx.kind == "PART" and o.parent == rig15]
    lowest = min((o.matrix_world @ Vector(c)).z for o in r15_parts if o.type == "MESH" for c in o.bound_box)
    check(abs(lowest) < 0.25, "R15 rig stands on the ground at the origin (lowest point z=%.2f)" % lowest)
    uarm = next((o for o in r15_parts if o.name.startswith("LeftUpperArm")), None)
    select_only(uarm)
    bpy.ops.rblx.apply_clothing(filepath=shirt_png, kind="SHIRT")
    hand = next((o for o in r15_parts if o.name.startswith("LeftHand")), None)
    box_u, box_h = uarm.get("rblx_template_box"), hand.get("rblx_template_box")
    check(uarm.data.uv_layers.get("RBX_Template_LEFT_LIMB") is not None and box_u is not None and
          box_h is not None and abs(box_u[4] - box_h[4]) < 1e-3 and box_u[4] > 0.9,
          "R15 shirt: upper arm and hand share one arm-sized clothing box (half height %.2f)"
          % (box_u[4] if box_u else -1))
else:
    skip("Roblox Studio not installed: R15 rig")

# ---------------------------------------------------------------- material style (2022 / legacy)
from rblx_tools import build, panels
from rblx_tools import materials as M
scene = bpy.context.scene
scene.rblx.use_2022_materials = True
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.rblx.add_part(shape="BLOCK")
wood = bpy.context.active_object
wood.rblx.material = "Wood"
mat = wood.material_slots[0].material


def wave_scale(m):
    w = next((n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexWave"), None)
    return w.inputs["Scale"].default_value if w else None


s2022 = wave_scale(mat)
check(mat.get("rblx_style") == "2022" and s2022 is not None, "Wood has 2022-style wood grain")
scene.rblx.use_2022_materials = False
mat2 = wood.material_slots[0].material
check(mat2 == mat and mat.get("rblx_style") == "LEGACY" and wave_scale(mat) not in (None, s2022),
      "Turning 2022 Materials off rebuilds the same material in the legacy style (%s -> %s)"
      % (s2022, wave_scale(mat)))
img = bpy.data.images.new("styletest", 4, 4, alpha=True)
M.add_layer(wood, image=img, mapping="UV")
M.refresh(wood)
lay = wood.material_slots[0].material
check(lay.get("rblx_layered") and lay.get("rblx_style") == "LEGACY", "Textured part uses legacy style")
scene.rblx.use_2022_materials = True
check(lay.get("rblx_style") == "2022" and mat.get("rblx_style") == "2022",
      "Turning 2022 Materials back on updates textured and shared materials")
check(M.surface_detail("Plastic", "2022") is None and M.surface_detail("Brick", "LEGACY")[1] <
      M.surface_detail("Brick", "2022")[1], "Legacy patterns are chunkier than 2022 ones")

# ---------------------------------------------------------------- build mode
check(panels.RBLX_PT_build.bl_category == "Tool" and panels.RBLX_PT_build.bl_label == "Roblox Build",
      "Roblox panels go in the Properties Editor's Tool tab by default")
_loc = panels.location
panels.location = lambda: "SIDEBAR"
panels.reregister()
check(panels.RBLX_PT_build.bl_category == "Roblox" and panels.RBLX_PT_build.bl_label == "Build"
      and panels.RBLX_PT_build.is_registered, "Panels can move to the 3D View sidebar")
panels.location = _loc
panels.reregister()
check(panels.RBLX_PT_properties.bl_category == "Tool" and panels.RBLX_PT_properties.is_registered,
      "...and back to the Tool tab")

model = bpy.data.objects.new("Car", None)
model.rblx.kind, model.rblx.class_name = "MODEL", "Model"
folder = bpy.data.objects.new("Stuff", None)
folder.rblx.kind, folder.rblx.class_name = "MODEL", "Folder"
for o in (model, folder):
    scene.collection.objects.link(o)
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.rblx.add_part(shape="BLOCK")
wheel = bpy.context.active_object
wheel.parent = model
model.parent = folder
check(build.pick_target(wheel) == model and build.pick_target(wheel, part_only=True) == wheel,
      "Clicking a part selects its Model (not the Folder); Alt picks the part")
check(build.moving_roots([model, wheel]) == [model], "Dragging a Model moves it, not its parts twice")
check(abs(build.snap(3.4, 1.0) - 3.0) < 1e-9 and build.snap(3.4, 0.0) == 3.4, "Grid snapping")
t = build.line_param(Vector((0, -10, 1)), Vector((0, 1, 0)), Vector((0, 0, 0)), Vector((0, 0, 1)))
check(t is not None and abs(t - 1.0) < 1e-6, "Handle drag follows the closest point on its axis")
check(not build.is_on() and "rblx.tool_move" not in str(build._state["registered"]),
      "Build mode is off until turned on")
build.set_build_mode(bpy.context, True)
check(build.is_on() and len(build._state["registered"]) == 4, "Build mode on adds the 4 tools")
build.set_build_mode(bpy.context, False)
check(not build.is_on() and not build._state["registered"], "Build mode off removes them")
keys = {(k[1]["type"], bool(k[1].get("ctrl")), bool(k[1].get("shift"))): k[0]
        for k in build.RBLX_TL_select.bl_keymap}
check(all(keys.get((k, False, False)) == "rblx.studio_camera" for k in "WASDQE") and
      keys.get(("W", False, True)) == "rblx.studio_camera" and
      keys.get(("RIGHTMOUSE", False, False)) == "rblx.studio_camera" and
      keys.get(("D", True, False)) == "object.duplicate" and
      keys.get(("G", True, False)) == "rblx.group_model" and
      keys.get(("R", True, False)) == "rblx.rotate_selection",
      "Roblox tools carry the Studio keys (WASD/QE, right-mouse look, Ctrl+D/G/R)")
from rblx_tools import studio
rv = type("RV", (), {})()
rv.view_location, rv.view_distance = Vector((0, 0, 0)), 10.0
rv.view_rotation = Vector((0, 0, 1)).to_track_quat("Z", "Y")
eye0 = studio._eye(rv)
studio.look(rv, 50, 20)
check((studio._eye(rv) - eye0).length < 1e-4, "Right-mouse look turns the camera in place")
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.rblx.add_part(shape="BLOCK")
a = bpy.context.active_object
bpy.ops.rblx.add_part(shape="BLOCK")
b = bpy.context.active_object
a.select_set(True)
bpy.ops.rblx.group_model()
grp = bpy.context.active_object
check(grp.rblx.kind == "MODEL" and a.parent == grp and b.parent == grp, "Group as Model (Ctrl+G)")
grp_name = grp.name
bpy.ops.rblx.ungroup_model()
check(a.parent is None and b.parent is None and bpy.data.objects.get(grp_name) is None,
      "Ungroup (Ctrl+U)")

# ---------------------------------------------------------------- downloads / web APIs (network)
from rblx_tools.download import Downloader, DownloadError, clean_cookie
check(clean_cookie(' .ROBLOSECURITY="_|WARNING:abc123"; ') == "_|WARNING:abc123",
      "Cookie accepted with or without the .ROBLOSECURITY= prefix")
lib = os.path.join(SCRATCH, "dl_library")
dl = Downloader(lib, anonymous=True, timeout=20)
mesh_path = dl.fetch("1699715537")  # Roblox's default R15 LeftHand mesh
if mesh_path is None and "Network error" in dl.errors.get("1699715537", ""):
    skip("No network: downloads")
else:
    check(mesh_path is not None and os.path.dirname(mesh_path) == os.path.join(lib, "meshes")
          and dl.methods.get("1699715537") == "no login",
          "Roblox-made mesh downloads with no login into library/meshes: %s"
          % (mesh_path and os.path.relpath(mesh_path, lib)))
    if mesh_path:
        md = rbxmesh.read_mesh(open(mesh_path, "rb").read())
        check(len(md.faces) > 0, "Downloaded mesh decodes (%s, %d tris)" % (md.version, len(md.faces)))
    tex_path = dl.fetch("6023426923")  # a Roblox-made texture
    check(tex_path is not None and os.path.dirname(tex_path) == os.path.join(lib, "textures")
          and M.load_image(tex_path) is not None,
          "Roblox-made texture downloads into library/textures: %s"
          % (tex_path and os.path.relpath(tex_path, lib)))
    # Saved for future use: a resolver without any downloader finds them offline
    offline = A.AssetResolver([lib], use_cache=False)
    check(offline.resolve_mesh("rbxassetid://1699715537") == mesh_path and
          offline.resolve_image("http://www.roblox.com/asset/?id=6023426923") == tex_path,
          "Library files are reused later without downloading")
    # Creator uploads need a login; a fake cookie is rejected cleanly
    fake = "_|WARNING:-DO-NOT-SHARE-THIS.--fakecookie123"
    dl2 = Downloader(os.path.join(SCRATCH, "dl2"), cookie=fake, anonymous=True, timeout=20)
    p2 = dl2.fetch("102224981335565")
    err = dl2.errors.get("102224981335565", "")
    check(p2 is None and "cookie" in err and "Authentication required" in err and "fakecookie" not in err,
          "Creator asset with a bad cookie: clear error, cookie not leaked: %s" % err)
    check("cookie" in dl2.disabled, "Rejected cookie isn't retried for every asset")
    # Optional: your own credentials from environment variables (never printed or saved)
    for env, kw in (("RBLX_TEST_COOKIE", "cookie"), ("RBLX_TEST_API_KEY", "api_key")):
        secret = os.environ.get(env, "").strip()
        if not secret:
            skip("%s not set: real %s download" % (env, kw))
            continue
        real = Downloader(os.path.join(SCRATCH, "real_" + kw), anonymous=False, timeout=30,
                          **{kw: secret})
        aid = os.environ.get("RBLX_TEST_ASSET", "102224981335565")
        rp = real.fetch(aid)
        check(rp is not None, "Creator asset %s downloads with your %s -> %s" % (
            aid, kw, os.path.basename(rp) if rp else real.errors.get(aid, "").replace(secret, "***")))
        del secret, real
    dl3 = Downloader(os.path.join(SCRATCH, "dl3"), api_key="not-a-real-key", anonymous=False, timeout=20)
    p3 = dl3.fetch("102224981335565")
    check(p3 is None and "API key" in dl3.errors.get("102224981335565", ""),
          "Bad API key is reported clearly: %s" % dl3.errors.get("102224981335565"))
try:
    uid, uname = CH.lookup_user_id("Roblox")
    av = CH.fetch_avatar(uid)
    check(uid == 1 and "assets" in av, "Public Roblox APIs: user %s -> avatar with %d assets"
          % (uname, len(av.get("assets", []))))
    report = I.ImportReport()
    res_no_dl = A.AssetResolver([assets_dir], use_cache=False)
    doc, name, rigtype = CH.build_avatar_document("Roblox", res_no_dl, report)
    imp = I.Importer(bpy.context, I.ImportOptions(allow_download=False), res_no_dl)
    imp.run_document(doc, name)
    rig3 = next((o for o in imp.collection.objects if o.rblx.kind == "RIG"), None)
    check(rig3 is not None, "Avatar 'Roblox' imports as a rigged %s character (no API key)" % rigtype)
except DownloadError as ex:
    skip("Avatar APIs unreachable: %s" % ex)
except Exception:
    traceback.print_exc()
    check(False, "Avatar import")

# ---------------------------------------------------------------- binary plugin files
for fn in ("moonanimator2.rbxm", "eclipseanimator.rbxm"):
    path = os.path.join(REPO, fn)
    if os.path.isfile(path):
        try:
            res = bpy.ops.import_scene.rblx(filepath=path, download=False)
            n = len(bpy.data.collections[os.path.splitext(fn)[0]].objects)
            check(res == {"FINISHED"} and n > 0, "Import binary %s -> %d objects" % (fn, n))
        except Exception:
            traceback.print_exc()
            check(False, "Import binary " + fn)

rblx_tools.unregister()
print("\n%d failure(s)" % len(FAILS))
for f in FAILS:
    print("  -", f)
