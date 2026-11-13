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
  - Characters inside places (NPCs) work the same way. Accessories and classic
    Hats that were saved without a weld are attached the way Roblox does when
    the game runs, so they follow the head. Files saved by recent Studio
    versions (which rename properties like `ShirtTemplate` to
    `ShirtTemplateContent`) are read too.
  - Clothing and face images uploaded by players need a login to download (an
    API key or cookie, see below); without one those characters show skin
    colour only.
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
    - 1–4 pick the tools (Select, Move, Scale, Rotate), Ctrl+L World/Local.
    - Ctrl+D duplicate in place, Ctrl+G group as Model, Ctrl+U ungroup.
    - Ctrl+R rotate 90°, Ctrl+T tilt 90°.
    - Delete / Backspace delete, Ctrl+Z / Ctrl+Y undo / redo.
  - These keys only apply while a Roblox tool is active. Pick a Blender tool,
    or turn Build Mode off, to get Blender's own keys back. For example, A
    selects all and Shift+A opens the Add menu again.
  - Locked parts can't be clicked.
- **Effects** (Roblox Effects panel; also imported from place and model files):
  - **Post-processing**:
    - BloomEffect, SunRaysEffect, ColorCorrectionEffect (Brightness,
      Contrast, Saturation, TintColor) and BlurEffect run in Blender's
      compositor.
    - DepthOfFieldEffect sets the scene camera's depth of field.
    - They're read from Lighting and from the Workspace camera; disabled ones
      are skipped.
    - **Show in Viewport** previews them in Material Preview / Rendered
      shading.
    - If your scene already has its own compositor nodes, they're left alone.
  - **ParticleEmitter, Fire, Smoke and Sparkles**:
    - A Geometry Nodes particle simulation that works like Roblox's: Rate,
      Lifetime, Speed, SpreadAngle, Acceleration, Drag, Rotation, RotSpeed,
      EmissionDirection and LightEmission.
    - Size, Color and Transparency change over each particle's life, and you
      can edit them as curves and a color ramp in the panel.
    - Particles are camera-facing sprites using Roblox's own particle textures
      (taken from your Studio install).
    - Emitters inside an Attachment emit from the attachment.
    - Particles build up as the animation plays from the first frame. Use
      **Bake Particles** to render or scrub any frame.
  - **Beam**: a textured, curved ribbon between its two attachments, with
    Width0/1, CurveSize0/1, Color, Transparency, Texture and FaceCamera.
  - **Highlight**: the FillColor tint plus an outline, on a part or on every
    part of a model. "Always on top" isn't reproduced.
- **More effects**:
  - **Trail**: a fading ribbon left behind between two attachments as a part
    moves.
  - **Live Beams** follow their attachments when parts move or are animated.
  - **Explosion**: a burst of fire and smoke on one frame. Add it from the
    Effects panel at a part or the 3D cursor; Explosions in files are imported
    too.
  - **ParticleEmitter shapes**: Box, Sphere, Cylinder and Disc, emitting from
    the volume or only the surface, outward, inward or both.
  - **ParticleEmitter flipbooks**: 2x2, 4x4 and 8x8 sheets, playing in Loop,
    OneShot, PingPong or Random mode.
- **Unions (CSG)**:
  - UnionOperation, NegateOperation and IntersectOperation are rebuilt from the
    parts they were made from, using Blender's boolean tools.
  - That includes nested unions and modern unions whose parts live in an asset
    (downloaded like other assets).
  - Each part keeps its own color unless UsePartColor is on.
- **Terrain**:
  - Smooth terrain is rebuilt as a rounded surface with the place's terrain
    material colors and Roblox's terrain textures (top and side textures,
    each at Roblox's own tile size).
  - **Water** uses Roblox's 25 animated wave normal maps, speed and strength
    from WaterWaveSpeed / WaterWaveSize, with WaterColor, WaterTransparency
    and WaterReflectance. Like in Roblox, fully transparent water still shows
    its surface (tint, waves and reflections).
  - **Decoration** (grass): blades GrassLength tall grow on upward Grass
    terrain near the active camera, swaying, like Roblox only draws grass near
    the player. Density and distance are inputs of the "RBX Grass" modifier.
  - **Clouds** under Terrain become a cloud layer with Cover, Density and Color.
  - Tested on Roblox's template places (Village, Castle, Pirate Island,
    Suburban, Starting Place).
- **A place's look comes with it**: importing a place, or **Load Lighting From
  Place** (Lighting panel), brings over:
  - Lighting: ClockTime, Brightness, Ambient colors, Exposure and fog.
  - Technology: Future turns on Eevee ray tracing.
  - Atmosphere: Density, Offset, Color, Decay, Glare and Haze.
  - The Sky's skybox: the six images, downloaded like other assets.
  - Post effects in Lighting and on the camera.
  - MaterialService.
  
  All of these can be edited afterwards in the Lighting and Effects panels
  and change the render live.
- **Material Service panel**:
  - Use2022Materials.
  - **MaterialVariants**: custom looks for a Roblox material made of ColorMap,
    NormalMap, RoughnessMap and MetalnessMap images (asset ids or files),
    with StudsPerTile.
  - **Applying a variant**: set it on a part through its **MaterialVariant**
    property (in Properties > Appearance) or with "Use on Selected Parts".
  - **Override Material**: tick it to make every part of that base material
    use the variant (MaterialService.<Material>Name).
  - Variants and overrides from a place are imported.
- **Layered clothing fits the body**:
  - When the clothing's ReferenceMesh cage and the body's WrapTarget cages
    can be loaded, the clothing is moved by the difference between them
    (cages matched by UV, like Roblox), inner layers first.
  - Then it's weighted to the nearest body parts' bones, so it bends when you
    animate.
- **Animations in and out**:
  - **Import Animation** (Animate panel, or File > Import > Roblox Animation)
    reads KeyframeSequences from .rbxm/.rbxmx files. That's what Roblox's
    Animation Editor, Moon Animator 2 (File > Export) and Eclipse Animator
    save.
  - CurveAnimations (the Animation Editor's curve mode) are read too:
    position, Euler and quaternion rotation curves with their cubic tangents,
    baked to one key per frame so the motion matches. Their markers become
    timeline markers.
  - You can also give an animation asset id; your own animations need an API
    key or cookie.
  - Poses, easing styles and keyframe markers come across.
  - **Export Animation** saves the rig's animation as a KeyframeSequence
    (.rbxmx) with Loop and Priority settings. Insert it in Studio and load it
    in the Animation Editor or Moon to publish it.
- **Export Roblox Model** (Import & Assets panel, or File > Export > Roblox
  Model):
  - Saves the selected objects as a .rbxmx that Studio can insert.
  - Includes parts with their shape, size, CFrame, color, material and
    behavior; Models and Folders; MeshParts with their MeshId; Decals and
    Textures with asset ids; lights; particle emitters.
  - Characters get their Motor6D joints and a Humanoid, plus their animation.
- **Animation Mode**: animate Roblox rigs and parts the way Moon Animator 2
  and Eclipse Animator do.
  - **Turning it on**: in Blender's **Animation** workspace, the 3D View
    header shows an **Animate** button where Build is in other workspaces. The
    Dope Sheet header and the Roblox Animate panel have it too. Turning it on
    switches Build Mode off, and the reverse.
  - **Posing**:
    - Click a body part to pick its **joint**, like Moon. Alt+click picks the
      part or model itself; Shift+click adds to the selection.
    - **Rotation rings** turn the joint around its pivot. **R** switches to
      move arrows, **Y** switches world/local axes, and **C** toggles rotation
      snapping (15° by default).
  - **Keyframes**:
    - Every handle drag sets a keyframe at the current frame when you let go,
      using the chosen **easing**.
    - The easing styles are Roblox's: Linear, Constant, Sine, Back, Quad,
      Cubic, Quart, Quint, Expo, Circ, Bounce and Elastic, each with In, Out or
      InOut. "Smooth" is Blender's own curve.
    - A keyframe's easing shapes the motion from that keyframe to the next,
      like Roblox's keyframes.
  - **Keys** (Moon Animator's defaults, which Eclipse's default keys also use):
    - Space play / pause, 1 go to start, 4 / 6 previous / next frame, J / K
      previous / next keyframe.
    - = add a keyframe, G reset the joint, Delete or X delete the keyframe.
    - Ctrl+C / Ctrl+V copy / paste a pose.
    - 7 edit the easing of the keyframes at the current frame.
    - F focus, Ctrl+Z / Ctrl+Y undo / redo.
    - The Studio camera (WASD, right mouse look, scroll) works too.
  - **Toolbar**: the row at the top of the 3D View has play controls, Key /
    Delete / Reset, easing style and direction, the handle mode, world/local
    axes and rotation snapping.
  - **Timeline**: Blender's Dope Sheet / Timeline. While Animation Mode is on,
    it shows every animated rig's tracks, like Moon's timeline.
  - **Frame rate**: scenes without animation switch to 60 fps, like Moon and
    Eclipse.
  - **Import / Export** buttons load Roblox animations onto the rig and save
    it back as a KeyframeSequence (see "Animations in and out").
  - **Not included yet**: Moon's mirror tools (Ctrl+R reflect, paste
    flipped), onion skins and IK.
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
- **Roblox materials**: one shared material per Roblox material type.
  - **Roblox's own textures**: in the Material Service panel, **Download
    Roblox Material Textures** fetches them once (about 57 MB):
    - What you get: color, normal, roughness and metalness maps for parts,
      Roblox's terrain textures (2022 and legacy) and the water waves.
    - Where they come from: Roblox's own setup CDN (`setup.rbxcdn.com`). They
      are taken from the last Studio builds that still shipped them as files;
      newer Studio streams them.
    - They're converted to PNGs in the asset library (`roblox_materials/`).
    - No login is needed.
  - Roblox's color maps are detail textures, tinted by the part or terrain
    color like in Roblox.
  - Until the textures are downloaded (or with **Use Roblox's Textures**
    off), procedural stand-ins are used (wood grain, bricks, cobblestones, ...).
  - **2022 Materials**: matches Roblox's `MaterialService.Use2022Materials`.
    - On (the default): Roblox's 2022 textures.
    - Off: the pre-2022 part and terrain textures.
    - Roblox never shipped 2022 textures as files for part-only materials
      (Wood, Metal, Plastic, ...), so those use the pre-2022 set in both
      styles.
    - Imported places use the place's own setting.
    - The toggle is in the Properties panel (Appearance), the Material Service
      panel and Import & Assets.
  - Your own textures win over Roblox's: point **Material Textures** at a
    folder of tileable textures named `Wood.png`, `Wood_normal.png`,
    `Wood_roughness.png`, ... Put them in `2022/` and `Legacy/` subfolders to
    have a set for each style.

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

- **Unions** are rebuilt from the parts they were made of, using Blender's
  boolean tools:
  - The union's own Material is used for the whole union.
  - Unions whose asset needs a login are boxes until you add an API key or
    cookie.
- **Layered clothing**:
  - Cage fitting needs the clothing's and the body's cage meshes. Cages of
    UGC items usually need an API key or cookie to download. Without them,
    the clothing keeps its imported shape.
  - Roblox's own solver isn't published. The fitting moves the clothing with
    its cages, without Roblox's extra smoothing and layer-collision passes.
- **Terrain**:
  - Roblox's real textures are used, but a few looks are estimated by eye
    because Roblox doesn't document them:
    - the grass blade shape and density;
    - how big the water wave texture is and how fast its frames play;
    - the shape and height of the cloud layer.
  - Terrain doesn't use MaterialVariants.
  - Grass grows around the scene's active camera. Without a camera, it grows
    around the world origin.
- **Particles, Fire, Smoke and Sparkles** use Roblox's particle textures, but
  Roblox doesn't publish how Fire/Smoke/Sparkles emit, so their motion is
  matched by eye.
- **Skybox images** made by a place's creator (not by Roblox) need an API key
  or cookie to download. Until then the Roblox-style gradient sky is used.
- **Animations**:
  - Roblox only has some easings (Linear, Constant, Cubic, Elastic, Bounce).
    Other easings, including Blender's Bezier curves, are exported as a
    keyframe on every frame so the motion matches.
  - Animations are exported as KeyframeSequences, not CurveAnimations.
- **Model export** writes Roblox objects. Meshes made in Blender can't travel in
  a model file: they're written as blocks and listed in the export report.
  Bring them into Studio with its 3D Importer (.fbx/.obj).
- **R15 avatar body scales** (height, width, head) are applied approximately.
  Body type and proportion blending isn't.
- **Lighting** is an approximation of Roblox's renderer in Blender, not an
  exact match.
- **Effects**:
  - Trails and particles build up while the animation plays; Bake them to
    render any frame.
  - Trail WidthScale and FaceCamera aren't reproduced.
  - Highlight's "always on top" isn't reproduced.
- **Moon Animator's own save files** aren't read: Moon's code asks not to be
  used by AI tools, so its save format wasn't studied. Export your Moon
  animation to a KeyframeSequence (Moon: File > Export) and import that.

## Roadmap

- MaterialVariants on terrain.
- CurveAnimation export.

## Development

The file-format code lives in `rblx_tools/rbx/` and doesn't depend on
Blender. To run the test suite (no UI needed):

```bash
blender --background --factory-startup --python tests/test_addon.py
```
