"""End-to-end tests for RBLX Tools. Run with Blender (no UI needed):

    blender --background --factory-startup --python tests/test_addon.py

Prints PASS/FAIL per check and a failure count at the end. If the Moon
Animator / Eclipse Animator .rbxm files are in the repo root they are also
imported as real-world binary files."""

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


def T(v):
    return str(tuple(round(x, 3) for x in v))


def close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for x, y in zip(a, b))


bpy.ops.wm.read_factory_settings(use_empty=True)
import rblx_tools
rblx_tools.register()
scene = bpy.context.scene
print("registered")

# ---------------------------------------------------------------- parts
for shape in ("BLOCK", "BALL", "CYLINDER", "WEDGE", "CORNER_WEDGE", "TRUSS"):
    res = bpy.ops.rblx.add_part(shape=shape)
    obj = bpy.context.active_object
    check(res == {"FINISHED"} and obj.rblx.kind == "PART" and len(obj.data.polygons) > 0,
          "add_part %s -> %d faces" % (shape, len(obj.data.polygons)))

bpy.ops.rblx.add_part(shape="BLOCK")
p = bpy.context.active_object
p.rblx.size = (4.0, 1.0, 2.0)
dims = p.dimensions
check(close(dims, (4.0, 2.0, 1.0)), "Block size (4,1,2) studs -> Blender dims %s" % T(dims))

p.rblx.position = (1.0, 2.0, 3.0)
bpy.context.view_layer.update()
check(close(p.location, (1.0, -3.0, 2.0)), "Roblox pos (1,2,3) -> Blender %s" % T(p.location))
check(close(p.rblx.position, (1.0, 2.0, 3.0)), "Position round-trip %s" % T(p.rblx.position))

p.rblx.orientation = (10.0, 20.0, 30.0)
bpy.context.view_layer.update()
check(close(p.rblx.orientation, (10.0, 20.0, 30.0), 1e-2),
      "Orientation round-trip %s" % T(round(v, 3) for v in p.rblx.orientation))

p.rblx.shape = "CYLINDER"
p.rblx.size = (6.0, 2.0, 2.0)
bpy.context.view_layer.update()
check(close(p.dimensions, (6.0, 2.0, 2.0), 1e-2), "Cylinder runs along X: dims %s" % T(p.dimensions))

p.rblx.material = "Neon"
check(p.material_slots[0].material.name == "RBX Neon", "Material switch -> RBX Neon")
p.rblx.color = (1.0, 0.0, 0.0)
p.rblx.transparency = 0.25
check(close(p.color, (1.0, 0.0, 0.0, 0.75)), "obj.color synced %s" % T(p.color))

# keyframe-able?
p.rblx.keyframe_insert("color", frame=1)
p.rblx.keyframe_insert("transparency", frame=1)
check(p.animation_data is not None and len(p.animation_data.action.fcurves if hasattr(p.animation_data.action, "fcurves") else [1]) >= 1,
      "Color/Transparency keyframes inserted")

# scale -> size sync
p.rblx.shape = "BLOCK"
p.rblx.size = (2.0, 2.0, 2.0)
p.scale = (2.0, 1.0, 1.0)
bpy.ops.object.select_all(action="DESELECT")
p.select_set(True)
bpy.context.view_layer.objects.active = p
bpy.ops.rblx.sync_size()
check(close(p.rblx.size, (4.0, 2.0, 2.0)) and close(p.scale, (1, 1, 1)),
      "Apply Scale to Size -> %s" % T(p.rblx.size))

# ---------------------------------------------------------------- lighting
for preset in ("DEFAULT", "CLASSIC", "SUNSET", "NIGHT", "FOGGY"):
    bpy.ops.rblx.lighting_preset(preset=preset)
sun = bpy.data.objects.get("RBX Sun")
check(sun is not None and scene.world.name == "RBX World", "Lighting created sun + world")
L = scene.rblx_lighting
L.fog_end = 100000
L.clock_time = 12.0
sun_dir = sun.matrix_world.to_3x3() @ Vector((0, 0, 1))
check(sun_dir.z > 0.5, "Noon sun is high (z=%.2f)" % sun_dir.z)
L.clock_time = 0.0
check(bpy.data.objects["RBX Sun"].data.energy == 0.0 and bpy.data.objects["RBX Moon"].data.energy > 0,
      "Midnight: sun off, moon on")
for mode in ("PHYSICAL", "NONE", "GRADIENT"):
    L.sky_mode = mode
check(scene.world.node_tree.nodes.get("RBX_SkyRamp") is not None, "Sky modes rebuild world")
L.clock_time = 14.5

# ---------------------------------------------------------------- test assets
assets_dir = os.path.join(SCRATCH, "assets")
os.makedirs(assets_dir, exist_ok=True)
if os.path.exists(os.path.join(assets_dir, "9999999.mesh")):
    os.remove(os.path.join(assets_dir, "9999999.mesh"))

# v2.00 mesh: a unit-ish tetrahedron, 4 verts, 4 faces, 36-byte vertices
verts = [(-1, -1, -1), (1, -1, -1), (0, 1, -1), (0, 0, 1)]
faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
blob = b"version 2.00\n" + struct.pack("<HBBII", 12, 36, 12, len(verts), len(faces))
for v in verts:
    blob += struct.pack("<9f", *v, 0, 1, 0, 0.5, 0.5, 0)
for f in faces:
    blob += struct.pack("<3I", *f)
with open(os.path.join(assets_dir, "1111111.mesh"), "wb") as fh:
    fh.write(blob)

img = bpy.data.images.new("decal_src", 4, 4, alpha=True)
img.pixels = [0.0, 0.5, 1.0, 1.0] * 16
img.filepath_raw = os.path.join(assets_dir, "Smiley_2222222.png")
img.file_format = "PNG"
img.save()
bpy.data.images.remove(img)

place = """<roblox version="4">
<Item class="Workspace" referent="W"><Properties><string name="Name">Workspace</string></Properties>
 <Item class="Model" referent="M"><Properties><string name="Name">House</string>
   <OptionalCoordinateFrame name="WorldPivotData"><CFrame><X>0</X><Y>5</Y><Z>0</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CFrame></OptionalCoordinateFrame>
  </Properties>
  <Item class="Part" referent="P1"><Properties><string name="Name">Wall</string>
   <CoordinateFrame name="CFrame"><X>10</X><Y>5</Y><Z>-4</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>
   <Vector3 name="size"><X>8</X><Y>10</Y><Z>1</Z></Vector3>
   <Color3uint8 name="Color3uint8">4294901760</Color3uint8>
   <token name="Material">512</token><float name="Transparency">0</float><bool name="Anchored">true</bool>
   <token name="shape">1</token></Properties>
   <Item class="Decal" referent="D1"><Properties><string name="Name">Smiley</string>
    <Content name="Texture"><url>rbxassetid://2222222</url></Content><token name="Face">5</token>
    <Color3 name="Color3"><R>1</R><G>1</G><B>1</B></Color3></Properties></Item>
   <Item class="Texture" referent="T1"><Properties><string name="Name">Bricks</string>
    <Content name="Texture"><url>rbxassetid://2222222</url></Content><token name="Face">2</token>
    <float name="StudsPerTileU">2</float><float name="StudsPerTileV">2</float></Properties></Item>
   <Item class="SurfaceLight" referent="L1"><Properties><string name="Name">Glow</string>
    <float name="Brightness">2</float><float name="Range">16</float><token name="Face">5</token>
    <float name="Angle">90</float></Properties></Item>
  </Item>
  <Item class="WedgePart" referent="P2"><Properties><string name="Name">Roof</string>
   <CoordinateFrame name="CFrame"><X>0</X><Y>12</Y><Z>0</Z><R00>0</R00><R01>0</R01><R02>1</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>-1</R20><R21>0</R21><R22>0</R22></CoordinateFrame>
   <Vector3 name="size"><X>4</X><Y>2</Y><Z>6</Z></Vector3><BrickColor name="BrickColor">21</BrickColor></Properties></Item>
  <Item class="MeshPart" referent="P3"><Properties><string name="Name">Gem</string>
   <CoordinateFrame name="CFrame"><X>0</X><Y>3</Y><Z>0</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>
   <Vector3 name="size"><X>4</X><Y>4</Y><Z>4</Z></Vector3><Vector3 name="InitialSize"><X>2</X><Y>2</Y><Z>2</Z></Vector3>
   <Content name="MeshId"><url>rbxassetid://1111111</url></Content>
   <Content name="TextureID"><url>rbxassetid://2222222</url></Content></Properties></Item>
  <Item class="MeshPart" referent="P4"><Properties><string name="Name">MissingMesh</string>
   <Vector3 name="size"><X>1</X><Y>1</Y><Z>1</Z></Vector3>
   <Content name="MeshId"><url>rbxassetid://9999999</url></Content></Properties></Item>
  <Item class="Part" referent="P5"><Properties><string name="Name">Ball</string>
   <Vector3 name="size"><X>3</X><Y>3</Y><Z>3</Z></Vector3><token name="shape">0</token><token name="Material">288</token></Properties>
   <Item class="PointLight" referent="L2"><Properties><string name="Name">Lamp</string><float name="Brightness">1</float><float name="Range">10</float></Properties></Item>
  </Item>
 </Item>
 <Item class="Script" referent="S"><Properties><string name="Name">Ignore me</string></Properties></Item>
</Item>
<Item class="Lighting" referent="LT"><Properties><string name="Name">Lighting</string>
 <string name="TimeOfDay">17:30:00</string><float name="Brightness">2.5</float>
 <Color3 name="OutdoorAmbient"><R>0.3</R><G>0.3</G><B>0.4</B></Color3>
 <float name="FogEnd">500</float><Color3 name="FogColor"><R>0.8</R><G>0.7</G><B>0.6</B></Color3></Properties>
 <Item class="Atmosphere" referent="AT"><Properties><string name="Name">Atmosphere</string><float name="Density">0.35</float></Properties></Item>
</Item>
</roblox>"""
place_path = os.path.join(SCRATCH, "test_place.rbxlx")
with open(place_path, "w", encoding="utf-8") as fh:
    fh.write(place)

# ---------------------------------------------------------------- import place
res = bpy.ops.import_scene.rblx(filepath=place_path, asset_folder=assets_dir, import_attachments=True)
check(res == {"FINISHED"}, "Import test place")
O = bpy.data.objects
wall, roof, gem, missing, house = O.get("Wall"), O.get("Roof"), O.get("Gem"), O.get("MissingMesh"), O.get("House")
check(all(x is not None for x in (wall, roof, gem, missing, house)), "All parts + model created")
bpy.context.view_layer.update()
check(wall.parent == house and close(wall.matrix_world.translation, (10, 4, 5)),
      "Wall parented to House at Blender %s" % T(wall.matrix_world.translation))
check(close(wall.dimensions, (8, 1, 10)), "Wall dims %s" % T(wall.dimensions))
check(wall.material_slots[0].material.name == "RBX Wood", "Wall material Wood")
check(close(wall.rblx.color, (1, 0, 0)), "Wall color from Color3uint8")
check(close(roof.rblx.color, (196 / 255, 40 / 255, 28 / 255)), "Roof BrickColor 21 -> Bright red")
check(roof.rblx.shape == "WEDGE", "Roof is a wedge")
check(close(roof.rblx.orientation, (0, 90, 0), 1e-2), "Roof orientation %s" % T(roof.rblx.orientation))
decal = O.get("Smiley")
check(decal is not None and decal.parent == wall and not decal.rblx.asset_missing
      and decal.material_slots[0].material.name.startswith("RBX Decal"), "Decal found image via asset id")
tex = O.get("Bricks")
check(tex is not None and tex.material_slots[0].material.name.startswith("RBX TiledTexture"), "Tiled texture")
check(gem.rblx.shape == "MESH" and len(gem.data.polygons) == 4 and not gem.rblx.asset_missing,
      "MeshPart loaded .mesh v2 (%d faces)" % len(gem.data.polygons))
check(close(gem.dimensions, (4, 4, 4), 1e-2), "MeshPart scaled to Size: %s" % T(gem.dimensions))
check(gem.material_slots[0].material.name.startswith("RBX Texture"), "MeshPart TextureID material")
check(missing.rblx.asset_missing and len(missing.data.polygons) == 6, "Missing mesh -> flagged placeholder box")
check(O.get("Glow") is not None and O["Glow"].type == "LIGHT", "SurfaceLight imported")
check(O.get("Lamp") is not None and O["Lamp"].data.type == "POINT", "PointLight imported")
check(O.get("Ignore me") is None, "Scripts skipped")
check(abs(L.clock_time - 17.5) < 1e-3 and abs(L.brightness - 2.5) < 1e-3 and L.fog_end == 500,
      "Lighting loaded from place (ClockTime %.2f)" % L.clock_time)
check(scene.world.node_tree.nodes.get("RBX_Fog") is not None, "Fog volume created")
check(bpy.data.texts.get("RBX Import Report") is not None, "Import report written")
print(bpy.data.texts["RBX Import Report"].as_string())

# reload missing: provide mesh 9999999 now
with open(os.path.join(assets_dir, "9999999.mesh"), "wb") as fh:
    fh.write(blob)
p = bpy.context.preferences
bpy.ops.rblx.reload_assets()
# resolver uses prefs (none registered here) so give it the folder through the importer API
from rblx_tools import assets as A, importer as I
ok = I.reload_part_mesh(missing, A.AssetResolver([assets_dir]))
check(ok and len(missing.data.polygons) == 4, "Reload missing mesh after adding file")

# size change on mesh part scales the object
gem.rblx.size = (2.0, 2.0, 2.0)
bpy.context.view_layer.update()
check(close(gem.dimensions, (2, 2, 2), 1e-2), "MeshPart Size edit rescales: %s" % T(gem.dimensions))

# add texture operator on a part
bpy.ops.object.select_all(action="DESELECT")
roof.select_set(True)
bpy.context.view_layer.objects.active = roof
res = bpy.ops.rblx.add_texture(filepath=os.path.join(assets_dir, "Smiley_2222222.png"), mode="DECAL", face="TOP")
check(res == {"FINISHED"} and any(c.rblx.kind == "DECAL" for c in roof.children), "Add Texture (decal) on part")

# convert regular mesh
bpy.ops.mesh.primitive_monkey_add()
monkey = bpy.context.active_object
bpy.ops.rblx.convert_to_part()
check(monkey.rblx.kind == "PART" and monkey.rblx.shape == "MESH", "Convert mesh to Roblox part")

# ---------------------------------------------------------------- binary files
for fn in ("moonanimator2.rbxm", "eclipseanimator.rbxm"):
    path = os.path.join(REPO, fn)
    if os.path.isfile(path):
        try:
            res = bpy.ops.import_scene.rblx(filepath=path)
            n = sum(1 for o in bpy.data.collections[os.path.splitext(fn)[0]].objects)
            check(res == {"FINISHED"} and n > 0, "Import binary %s -> %d objects" % (fn, n))
        except Exception:
            traceback.print_exc()
            check(False, "Import binary " + fn)

# ---------------------------------------------------------------- render check
bpy.ops.wm.read_factory_settings(use_empty=True)
rblx_tools.unregister()
rblx_tools.register()
scene = bpy.context.scene
from rblx_tools import operators as OPS
part = OPS.create_part(bpy.context, "BLOCK", size=(20, 20, 1))
part.rblx.color = (1.0, 0.0, 0.0)
part.rblx.material = "SmoothPlastic"
part.rblx.orientation = (0, 0, 0)
cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -10, 0)  # Roblox front (-Z) is Blender -Y
cam.rotation_euler = (math.pi / 2, 0, 0)
scene.camera = cam
bpy.ops.rblx.lighting_preset(preset="CLASSIC")
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 4
scene.render.resolution_x = scene.render.resolution_y = 16
out = os.path.join(SCRATCH, "render_test.png")
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(out)
px = list(img.pixels)
mid = (8 * 16 + 8) * 4
r, g, b = px[mid:mid + 3]
check(r > 0.2 and r > 3 * g and r > 3 * b, "Render: part shows its rblx.color red (rgb %.2f %.2f %.2f)" % (r, g, b))

rblx_tools.unregister()
print("\n%d failure(s)" % len(FAILS))
for f in FAILS:
    print("  -", f)
