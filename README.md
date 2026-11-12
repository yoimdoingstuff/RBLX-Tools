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
- **Downloading assets**: meshes, textures and models are downloaded
  automatically with your own API key or `.ROBLOSECURITY` cookie (see below).
  Roblox-made assets, like the default body meshes, download with no login at
  all. Everything downloaded is kept in the **asset library**
  (`meshes/`, `textures/`, `models/`), so it's reused by later imports, even
  offline.
- **Characters**
  - Any Model with a Humanoid becomes a **rigged character**. An armature is
    built from its Motor6D joints, and each body part follows its bone, so you
    animate in Pose Mode.
  - BodyColors, Shirts, Pants, T-Shirts, faces and accessories are applied.
  - **Add > Roblox > R6 / R15 Character** inserts a ready-to-animate rig. R6
    works offline; R15 uses the rig from your Roblox Studio install.
  - **Avatar from Username**: imports anyone's avatar as a rigged R6 or R15
    character, with skin tone, clothing, classic or dynamic head and face, body
    parts and accessories.
    - Most of those items are creator uploads, which Roblox only lets you
      download with a login, so set an API key or cookie (see below).
    - Without one you get the body, skin tone, Roblox-made items, and the
      classic head and face. The import names every item it couldn't download.
  - **Body packages**: R15 body parts and R6 packages (CharacterMesh) replace
    the default body, with base and overlay textures.
  - **Accessory Adjustment**: an avatar's adjusted accessory position,
    rotation and scale are applied. This follows Roblox's documented
    Position/Rotation/Scale but hasn't been checked against an adjusted avatar
    yet.
  - R6 body parts get the same rounded edges Roblox gives them. Any block can
    use this through the part's **Bevel** property.
- **Where the panels are**: Blender doesn't let add-ons add their own tab to
  the Properties Editor, so the Roblox panels (Build, Properties, Textures,
  Character, Insert, Lighting, Import & Assets) go in its **Tool** tab (the
  wrench and screwdriver icon at the top). The 3D View sidebar can then stay
  closed. To get the old 3D View sidebar tab back, set **Roblox Panels** to
  "3D View Sidebar" in the addon preferences or in Import & Assets.
- **Build Mode**: turn it on and off with the **Build** button in the 3D View
  header or the Roblox Build panel. While it's off, Blender works as usual.
  While it's on, four Studio-style tools appear in the toolbar (T):
  - **Roblox Select**:
    - Click a part to select its Model, like Studio. Alt+click selects the
      part itself; Shift or Ctrl+click adds to the selection.
    - Drag a part to slide it over other surfaces. It lands on whatever is
      under the cursor and its corner snaps to the stud grid.
    - While dragging, **R** rotates and **T** tilts by 90°. Esc or right-click
      cancels the drag.
    - Dragging on empty space draws a selection box.
  - **Roblox Move**: arrow handles move the selection along an axis in Move
    increments.
  - **Roblox Scale**: ball handles resize one face of a part, keeping the
    opposite face in place. Hold Ctrl to resize both sides.
  - **Roblox Rotate**: rings rotate in Rotate increments.
  - **Snapping**: Move (default 1 stud) and Rotate (default 15°) increments
    can each be turned off. **World/Local** sets the handle axes (Ctrl+L).
    **Show Stud Grid** makes the viewport grid one stud per square.
  - **Studio toolbar**: the row at the top of the 3D View, in this order:
    - Part buttons: one click inserts a Block, Sphere, Wedge, Corner Wedge or
      Cylinder. Like Studio, the new part lands on the surface in the middle of
      the view, snapped to the grid and selected. Insert again and it stacks on
      top.
    - The four tools, then the Move and Rotate snapping and World/Local.
    - For the selected part: Material, Color, Anchored and Locked.
    - Group and Ungroup.
    On a narrow screen, Ctrl+scroll over the row to see the rest.
  - **Studio camera** (on by default; turn off in the Build panel or the addon
    preferences):
    - **W A S D** move, **Q / E** go down / up, and holding **Shift** goes
      slower.
    - **Scroll while moving** changes the camera speed (shown in the header).
      The speed is remembered.
    - Hold **right mouse** to look around; WASD keeps working while you do. A
      right click that doesn't move still opens the context menu.
    - **Middle mouse** pans, Shift+middle mouse orbits like Blender, and
      **scroll** zooms toward the cursor.
    - **F** focuses the selection.
  - **Studio shortcuts**:
    - Ctrl+1–4 tools, Ctrl+L World/Local.
    - Ctrl+D duplicate in place, Ctrl+G group as Model, Ctrl+U ungroup.
    - Ctrl+R rotate 90°, Ctrl+T tilt 90°.
    - Delete / Backspace delete, Ctrl+Z / Ctrl+Y undo / redo.
  - These keys only apply while a Roblox tool is active. Pick a Blender tool,
    or turn Build Mode off, to get Blender's own keys back. For example, A
    selects all and Shift+A opens the Add menu again.
  - Locked parts can't be clicked.
- **Studio-style properties** (Roblox Properties panel, and Properties Editor >
  Object > Roblox):
  - Grouped like Studio: Appearance (BrickColor, CastShadow, Color, Material,
    Reflectance, Transparency), Data (ClassName, Name, Position, Orientation),
    Behavior, and Part (Shape, Size).
  - Like Studio, a change applies to **every selected part**. The "Edit N
    selected" button turns that off.
  - Color, Transparency and Reflectance can be keyframed: hover over the field
    and press I.
- **Textures** (Roblox Textures panel): every part has a stack of texture
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
- **Roblox lighting** (Roblox Lighting panel):
  - ClockTime moves the sun and moon. Brightness, Ambient, OutdoorAmbient,
    ColorShift, ShadowSoftness, ExposureCompensation, Fog and Atmosphere work
    like their Studio counterparts.
  - Presets, or load the lighting from any place file.
- **Roblox materials**: one shared material per Roblox material type, with
  procedural surface detail (wood grain, bricks, cobblestones, ...).
  - **2022 Materials**: matches Roblox's `MaterialService.Use2022Materials`.
    - On (the default) gives the finer, subtler 2022 material look.
    - Off gives the older, chunkier pre-2022 look.
    - Imported places use the place's own setting.
    - The toggle is in the Properties panel (Appearance) and in Import & Assets.
  - These are procedural stand-ins, not Roblox's actual texture images: Studio
    downloads those on demand instead of keeping them on disk.
  - For the real look, point **Material Textures** at a folder of tileable
    textures named `Wood.png`, `Wood_normal.png`, `Wood_roughness.png`, ...
    Put them in `2022/` and `Legacy/` subfolders to have a set for each style.

## Install

1. Zip the `rblx_tools` folder. You can also build the zip with Blender:
   ```bash
   blender --command extension build --source-dir rblx_tools --output-dir dist
   ```
2. In Blender, go to Edit > Preferences > Get Extensions, open the ⌄ menu, and
   choose **Install from Disk...**. Pick the zip.
3. In the Properties Editor, open the **Tool** tab (the wrench and screwdriver
   icon at the top of its tab column). The Roblox panels are there, below
   Blender's own tool options.

## Getting meshes and textures

Roblox files only store asset ids like `rbxassetid://12345678`, not the actual
meshes and textures. Since April 2025 Roblox only gives most asset files to
logged-in requests. The addon tries these in order and falls back to the next
one if an asset is refused:

1. **Open Cloud API key** (what Roblox recommends):
   1. Go to <https://create.roblox.com/dashboard/credentials> and choose
      **Create API Key**.
   2. Add the **Assets** API system with the `legacy-asset:manage`
      permission (only reading is used). Set accepted IP addresses to your
      own IP, or `0.0.0.0/0`.
   3. Paste the key into the Roblox Import & Assets panel, or Edit >
      Preferences > Add-ons > RBLX Tools. The key is saved in your Blender
      preferences and only sent to `apis.roblox.com`.
2. **Your `.ROBLOSECURITY` cookie**: paste it into the **Cookie** field (with
   or without the `.ROBLOSECURITY=` part).
   - By default it's kept **in memory only** and forgotten when Blender
     closes. It's never written to your .blend files or preferences.
   - Tick **Remember Cookie** to save it in your Blender preferences (plain
     text on your computer).
   - It's only sent to `assetdelivery.roblox.com`.
   - **Never share your cookie**: anyone who has it can log in as you. If it
     leaks, log out of all sessions on roblox.com to invalidate it.
   - Roblox discourages cookie access for tools and may turn it off, which is
     why the API key is tried first.
3. **No login**: Roblox-made assets (default body meshes, many built-in
   textures) download without any credentials.

Also make sure Blender's **Allow Online Access** is on (Preferences > System >
Network). **Test Download** fetches one asset id and tells you which method
worked.

### Asset library

Everything downloaded is saved for future use:

| Folder | What's in it |
| --- | --- |
| `meshes/` | `.mesh` files (MeshPart / SpecialMesh meshes) |
| `textures/` | `.png`, `.jpg`, `.webp`, ... (TextureIDs, Decals, clothing, faces) |
| `models/` | `.rbxm` / `.rbxmx` (Decal, Shirt, Pants and accessory assets) |
| `other/` | anything else |

Files are named by asset id, e.g. `textures/6023426923.png`, and any import
that needs them uses them without downloading again. By default the library is
in the addon's own user folder. You can pick another folder in the settings,
use **Open Folder** to browse it, or **Clear** to empty it.

Without downloads, the addon still uses:
- **Asset Folder**: files you've saved yourself, named by asset id. For example
  `12345678.png`, `12345678.mesh`, or `Sword_12345678.mesh`. Subfolders are
  searched too, and files don't need an extension.
- **Roblox Studio content**: built-in `rbxasset://` files, the classic head
  mesh and the R15 rig. This works with the normal installer and with
  Bloxstrap-style launchers (Bloxstrap, Fishstrap, Voidstrap).

Anything still missing is listed in **Text Editor > RBX Import Report**, with
the reason (for example "Authentication required" when no key or cookie
worked):
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
- Colors are converted from Roblox's sRGB to Blender's linear color. Values
  are stored linear, and the color picker's hex matches Studio's.

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
