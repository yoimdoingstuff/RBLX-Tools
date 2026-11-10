# RBLX-Tools
Blender plugin for animating Roblox related scenes.

Import Roblox models, places, characters and avatars into Blender. Edit parts
with a Studio-style properties panel, put your own textures on parts, and light
scenes with Roblox's Lighting settings.

Tested on Blender 5.2. Needs Blender 4.2 or newer.

## Features

- **Roblox file import**: `.rbxm` / `.rbxl` (binary) and `.rbxmx` / `.rbxlx`
  (XML). Use File > Import > Roblox, or drag a file into the viewport.
  - Parts: Block, Ball, Cylinder, Wedge, CornerWedge and Truss, with correct
    size, position, rotation, color, material and transparency.
  - **Meshes**: MeshParts and SpecialMeshes, including current Draco-compressed
    `.mesh` v6/v7 files (decoded with the Draco library that ships with
    Blender).
  - Models and Folders become empties at the model's pivot. Decals, Textures,
    SurfaceAppearance and lights are imported too.
  - Place files also bring in their Lighting settings.
- **Downloading assets**: meshes and images are downloaded automatically
  through Roblox Open Cloud with your own API key (see below). They're cached,
  so each asset is only downloaded once.
- **Characters**
  - Any Model with a Humanoid becomes a **rigged character**. An armature is
    built from its Motor6D joints, and each body part follows its bone, so you
    animate in Pose Mode.
  - BodyColors, Shirts, Pants, T-Shirts, faces and accessories are applied.
  - **Add > Roblox > R6 / R15 Character** inserts a ready-to-animate rig. R6
    works offline; R15 uses the rig from your Roblox Studio install.
  - **Avatar from Username**: imports anyone's avatar as a rigged R6 or R15
    character, with body colors, clothing, face, body parts and accessories.
- **Studio-style properties** (Sidebar > Roblox > Properties, and Properties
  Editor > Object > Roblox):
  - Grouped like Studio: Appearance (BrickColor, CastShadow, Color, Material,
    Reflectance, Transparency), Data (ClassName, Name, Position, Orientation),
    Behavior, and Part (Shape, Size).
  - Like Studio, a change applies to **every selected part**. The "Edit N
    selected" button turns that off.
  - Color, Transparency and Reflectance can be keyframed: hover over the field
    and press I.
- **Textures** (Sidebar > Roblox > Textures): every part has a stack of texture
  layers. Each layer is an image with:
  - **Type**:
    - **Decal**: one face.
    - **Texture**: tiled on one face (StudsPerTile, Offset).
    - **Wrap**: the whole part, using its UVs, like MeshPart.TextureID.
    - **Clothing**: the Roblox 585×559 shirt/pants template.
  - **Color3**: a tint that recolors the image **separately from the part**.
    Transparent areas of the image show the part's own Color underneath, which
    is how Roblox's transparent textures work.
  - **Transparency**, **Enabled**, and a draw order (move up/down).
  - **Editing**:
    - Replace the image.
    - Make Unique: give this part its own copy.
    - Edit Image: open it in an Image Editor.
    - Paint on Part: Texture Paint in the 3D view.
    - Save Image As, or pack it into the .blend.
  - **Drag an image file onto a part** in the viewport. It becomes a Decal on
    the face you dropped it on, or wraps the part if it's a mesh.
  - **Character panel**: Add Shirt / Pants / T-Shirt images (or asset ids) to
    the selected character.
- **Roblox lighting** (Sidebar > Roblox > Lighting):
  - ClockTime moves the sun and moon. Brightness, Ambient, OutdoorAmbient,
    ColorShift, ShadowSoftness, ExposureCompensation, Fog and Atmosphere work
    like their Studio counterparts.
  - Presets, or load the lighting from any place file.
- **Roblox materials**: one shared material per Roblox material type.
  Optionally point the addon at a folder of tileable textures named
  `Wood.png`, `Wood_normal.png`, ... and they're used automatically.

## Install

1. Zip the `rblx_tools` folder. You can also build the zip with Blender:
   ```bash
   blender --command extension build --source-dir rblx_tools --output-dir dist
   ```
2. In Blender, go to Edit > Preferences > Get Extensions, open the ⌄ menu, and
   choose **Install from Disk...**. Pick the zip.
3. Open the sidebar in the 3D view (N) and select the **Roblox** tab.

## Getting meshes and images (API key)

Roblox files only store asset ids like `rbxassetid://12345678`, not the actual
meshes and images. Since April 2025 Roblox only gives asset files to
authenticated requests, so the addon uses **your own Open Cloud API key**:

1. Go to <https://create.roblox.com/dashboard/credentials> and choose
   **Create API Key**.
2. Add the **Assets** API system with the `legacy-asset:manage` permission
   (read access is all that's used). Set accepted IP addresses to `0.0.0.0/0`
   or your own IP.
3. Paste the key into Edit > Preferences > Add-ons > RBLX Tools > **Open Cloud
   API Key**, or into Sidebar > Roblox > Import & Assets.
4. Make sure Blender's **Allow Online Access** is on (Preferences > System >
   Network).

The key is stored in your Blender preferences and only sent to
`apis.roblox.com`. Downloaded files go to the cache folder shown in the
preferences (you can clear it there).

Without a key, the addon still uses:
- **Asset Folder**: files you've saved yourself, named by asset id. For example
  `12345678.png`, `12345678.mesh`, or `Sword_12345678.mesh`. Subfolders are
  searched too, and files don't need an extension.
- **Roblox Studio content**: built-in `rbxasset://` files, the classic head
  mesh and the R15 rig. This works with the normal installer and with
  Bloxstrap-style launchers (Bloxstrap, Fishstrap, Voidstrap).

Anything still missing is listed in **Text Editor > RBX Import Report**, with
the reason:
- Missing meshes import as boxes of the right size.
- Missing images import as empty layers.

**Reload Missing Assets** tries again later.

## Units and axes

- 1 stud = 1 Blender unit by default, so numbers match Studio. You can change
  this with **Stud Scale** when importing (0.28 is Roblox's real-world meters
  per stud).
- Roblox is Y-up and Blender is Z-up. The addon converts between them, and the
  properties panel always shows Roblox values.
- A Roblox part's front (-Z, its LookVector) faces Blender's front view, so
  numpad 1 looks a character in the face.

## Known limitations

- Unions (CSG) import as boxes. Their geometry is stored in a format that isn't
  decoded yet.
- Layered clothing (3D shirts/jackets) and dynamic heads import as rigid meshes
  attached to the body. They don't deform with it.
- R15 avatar body scales (height, width, head) are applied approximately.
  Body type and proportion blending isn't.
- Terrain isn't imported.
- The lighting is an approximation of Roblox's renderer in Blender, not an
  exact match.

## Roadmap

- **Moon Animator 2 / Eclipse Animator animations**
  - Option 1: import animations exported from Studio. You build the animation
    with the plugin, save the animated rig or model, and the addon turns its
    KeyframeSequences into keyframes on the rig's bones. Rigs already store
    each joint's C0/C1 for this.
  - Option 2: recreate the plugins' motion in Blender, by reading how each
    plugin generates its animation and rebuilding it as Blender keyframes.
- Union/CSG geometry, layered clothing deformation, and Terrain.
- Exporting back to Roblox.
- Bloom, ColorCorrection, SunRays and DepthOfField post effects.

## Development

The file-format code lives in `rblx_tools/rbx/` and doesn't depend on
Blender. To run the test suite (no UI needed):

```bash
blender --background --factory-startup --python tests/test_addon.py
```
