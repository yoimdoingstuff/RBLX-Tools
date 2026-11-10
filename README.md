# RBLX-Tools
Blender plugin for animating Roblox related scenes.

Import Roblox models and places into Blender, edit parts with a Studio-style
properties panel, and light scenes with Roblox's Lighting settings.

Tested on Blender 5.2. Needs Blender 4.2 or newer.

## Features

- **Roblox file import**: `.rbxm` / `.rbxl` (binary) and `.rbxmx` / `.rbxlx`
  (XML). Use File > Import > Roblox, or drag a file into the viewport.
  - Parts: Block, Ball, Cylinder, Wedge, CornerWedge and Truss, with correct
    size, position, rotation, color, material and transparency.
  - MeshParts and SpecialMesh FileMeshes. Roblox `.mesh` versions 1 to 5 are
    supported, and 6 and 7 when they aren't Draco-compressed.
  - Models and Folders become empties, placed at the model's pivot, so you can
    move or animate a whole model at once.
  - Decals and Textures, SurfaceAppearance (PBR maps), and Point, Spot and
    Surface lights. Attachments are optional.
  - Place files also bring in their Lighting settings, including Atmosphere and
    Sky.
  - Scripts, GUIs and other non-visual objects are skipped.
- **Properties panel** (Sidebar > Roblox > Properties) for the selected part:
  - Color, Material, Transparency, Reflectance and CastShadow.
  - Position, Orientation and Size in studs, on Roblox's axes (Y up).
  - Shape, plus Anchored, CanCollide and the other behavior flags.
  - MeshId and TextureID.
  - Color, Transparency and Reflectance can be keyframed: hover over the field
    and press I.
- **Roblox lighting** (Sidebar > Roblox > Lighting):
  - ClockTime moves the sun and moon. Brightness, Ambient, OutdoorAmbient,
    ColorShift, ShadowSoftness, ExposureCompensation, Fog and Atmosphere work
    like their Studio counterparts.
  - The sky can be a Roblox-style gradient, Blender's physical sky, or your own
    sky image.
  - Presets: Baseplate Default, Classic, Sunset, Night and Foggy. You can also
    load the lighting from any place file.
- **Roblox materials**: one shared material per Roblox material type (Plastic,
  Wood, Neon, Glass, ForceField, ...).
  - Each part's own Color and Transparency are read from the part, so one
    material serves every part.
  - Optionally point the addon at a folder of tileable textures named
    `Wood.png`, `Wood_normal.png`, `Wood_roughness.png` and so on, and they're
    used automatically.
- **Roblox textures**: add any image (for example one downloaded from Roblox)
  to selected parts in one of three ways:
  - **Decal**: stretched once over one face.
  - **Texture**: tiled by StudsPerTile.
  - **Part texture**: wrapped over the whole part using its UVs, like a
    MeshPart's TextureID.
- **Insert parts**: Add > Roblox Part, or Sidebar > Roblox > Insert.
- **Make Roblox Part**: turns any Blender mesh into a part, so it gets the
  properties panel too.

## Install

1. Zip the `rblx_tools` folder. You can also build the zip with Blender:
   ```bash
   blender --command extension build --source-dir rblx_tools --output-dir dist
   ```
2. In Blender, go to Edit > Preferences > Get Extensions, open the ⌄ menu, and
   choose **Install from Disk...**. Pick the zip.
3. Open the sidebar in the 3D view (N) and select the **Roblox** tab.

## Assets (meshes and images)

Roblox files only store asset ids like `rbxassetid://12345678`, not the actual
meshes and images. The addon doesn't download anything; it looks for the
files on your computer:

- **Asset Folder** (Preferences, or Sidebar > Roblox > Import & Assets): a
  folder with files you've downloaded, named by asset id. For example
  `12345678.png`, `12345678.mesh`, or `Sword_12345678.mesh`. Subfolders are
  searched too, and files don't need an extension.
- **Roblox Studio content**: built-in `rbxasset://` paths are found
  automatically from your Roblox Studio install.

Anything it can't find is listed in **Text Editor > RBX Import Report**:
- Missing meshes import as boxes of the right size.
- Missing decal images import invisible.

Once you've added the files to your asset folder, click **Reload Missing
Assets**.

## Units and axes

- 1 stud = 1 Blender unit by default, so numbers match Studio. You can change
  this with **Stud Scale** when importing (0.28 is Roblox's real-world meters
  per stud).
- Roblox is Y-up and Blender is Z-up. The addon converts between them, and the
  properties panel always shows Roblox values.

## Known limitations

- Unions (CSG) import as boxes. Their geometry is stored in a format that isn't
  decoded yet.
- Draco-compressed meshes (newer `.mesh` v6/v7 uploads) aren't supported yet.
- Terrain isn't imported.
- The lighting is an approximation of Roblox's renderer in Blender, not an
  exact match.

## Roadmap

- **Moon Animator 2 / Eclipse Animator animations**
  - Option 1: import animations exported from Studio. You build the animation
    with the plugin, save the animated rig or model, and the addon turns its
    KeyframeSequences into Blender keyframes.
  - Option 2: recreate the plugins' motion in Blender, by reading how each
    plugin generates its animation and rebuilding it as Blender keyframes.
- R6/R15 character rigs imported as armatures, with Motor6D joints as bones.
- Union/CSG geometry, Draco meshes, and Terrain.
- `.obj`/`.fbx` meshes in the asset folder.
- Exporting back to Roblox.
- Bloom, ColorCorrection, SunRays and DepthOfField post effects.

## Development

The file-format code lives in `rblx_tools/rbx/` and doesn't depend on
Blender. To run the test suite (no UI needed):

```bash
blender --background --factory-startup --python tests/test_addon.py
```
