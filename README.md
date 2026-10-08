# SpritePostprocess

**English** | [简体中文](README.zh-CN.md)

SpritePostprocess is a standalone, offline, cross-project tool for post-processing animation that already exists. It does not call a generative model and does not depend on a particular character, game engine project, ComfyUI service, or previous delivery folder.

The graphical interface and command-line interface use the same configuration and processing core. Animation names, direction counts, frame counts, and canvas dimensions are configurable. `512 -> 64/32`, eight directions, 16 frames, and 32 pixels per unit are examples, not requirements.

## Beginner quick start

### Windows graphical interface (recommended)

Double-click `Start.cmd`. On first use, click **Environment Check** to check the Python dependencies. Reading or writing Aseprite files also requires the Aseprite CLI. Then:

1. Select the source folder and choose a **new result folder that does not exist yet**.
2. Select a preset and click **Create Config**. The config is stored outside the result folder so creating that folder does not block processing.
3. In **Common Settings**, choose the work size, output sizes, cleanup strength, layout and occupancy, preview settings, and export formats. Click **Apply Common Settings to JSON**.
4. Use **Advanced JSON** only when you need features such as mirroring, reversing, frame matching, or a per-animation zoom correction.
5. Click **Save + Run**. Progress appears in the log and does not take over Unity or another foreground application.
6. When processing finishes, click **Verify Output** to check the files, or **Open Output Folder** to view previews and delivery files.

The interface remembers the last selected language in `.ui-preferences.json` beside the tool. Config files and reports keep stable English JSON keys, so the same config can safely be opened from either interface language.

The `neutral` preset leaves white-edge cleanup disabled and preserves the source character occupancy. The `pixel-character` preset enables strict white-edge cleanup and fixed shared-fit scaling. Both presets remain fully editable. For white fur, glowing outlines, snow, feathers, or similar art, start with `neutral` or `conservative` rather than strict cleanup.

The interface does not modify a game project directly. Editing a config does not start a job, and processing always uses the last saved JSON.

### Command line

The `--lang en|zh-CN` option may be placed before or after the subcommand. `SPRITEPOST_LANG` can provide the default language.

```powershell
python spritepost.py --lang en doctor

python spritepost.py init --lang en --input "E:/Art/creature/aseprite" --output "E:/Jobs/creature.json" --result-dir "E:/Delivery/creature" --preset pixel-character

python spritepost.py process "E:/Jobs/creature.json" --lang en
python spritepost.py verify "E:/Delivery/creature" --lang en
python spritepost.py inspect "E:/Art/creature/walk_front.aseprite" --lang en
```

You can also use `Start.cmd doctor`, or `Start.ps1 -Python "path/to/python.exe" doctor`. The GUI and CLI use the same Python environment.

### Setup and portability

Python **3.10 or newer** is required. A typical isolated setup on Windows is:

```powershell
git clone https://github.com/fAaAtDoOoG/SpritePostprocess.git
cd SpritePostprocess
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start.cmd
```

- Runtime packages are NumPy, OpenCV, and Pillow; supported ranges are listed in `requirements.txt`.
- The GUI uses the Tkinter module bundled with most Python installers. The CLI does not need a desktop session. On Linux, the GUI may require a separately installed system Tk package.
- Reading or writing `.aseprite`/`.ase` requires a local Aseprite CLI. PNG-only input with `export.aseprite` disabled does not require Aseprite.
- Choose Aseprite in the GUI, set the config field `aseprite`, set `SPRITEPOST_ASEPRITE`, put Aseprite on `PATH`, or let the tool inspect common Steam installation locations.
- Select Python with `Start.ps1 -Python`, `SPRITEPOST_PYTHON`, `runtime.local.json`, a local `.venv`, or `PATH`, in that order.

`runtime.local.json` is an optional machine-local file next to the tool:

```json
{
  "python": "C:/Users/you/Tools/SpritePostprocess/.venv/Scripts/python.exe"
}
```

The path must be absolute. This file is intentionally excluded from release archives and Git so that a checkout remains portable. To move the tool to another computer, copy or clone the repository, create a local Python environment, install `requirements.txt`, and select that computer's Aseprite executable if needed. The tool never downloads, installs, or upgrades dependencies without an explicit command.

## Processing workflow

```text
existing animation
  -> read frames and timing
  -> optional high-resolution frame matching / frame-order operations
  -> cleanup at source resolution
  -> fixed work canvas and optional zoom correction
  -> shared scale and placement
  -> premultiplied-alpha resize
  -> cleanup at each output size and explicit mirrors
  -> Aseprite / PNG / previews / reports / ZIP
  -> file verification
```

1. **Read artwork and timing:** Aseprite files, PNG sprite sheets, and PNG frame sequences are supported. The actual frame count is used; a filename containing `48f` is not trusted.
2. **Recover an edited frame order (optional):** provide a high-resolution `source` and a user-edited `edited` animation. The tool matches each edited frame, preserves its order and duration, compares normalized premultiplied RGBA, and records the best score and runner-up margin. A low-confidence match stops with a report instead of silently choosing an approximation. An explicit `frame_map` can be used instead.
3. **Apply explicit order operations:** reverse and ping-pong are optional. Durations and provenance move with the corresponding frames.
4. **Clean at source resolution:** configurable cleanup targets transparent-edge contamination, small floating white specks, and hidden RGB in fully transparent pixels. It does not globally delete white pixels.
5. **Create the work canvas:** frames are fitted proportionally into the configured high-resolution work canvas. Upscaling a small source is reported because it cannot restore missing detail. `source_at_least_work_resolution` describes file dimensions only; it cannot prove the image was never previously enlarged.
6. **Correct progressive growth (optional):** only an explicit `zoom` config activates this step. A continuous scale curve is applied to the final selected sequence at work resolution around one fixed bottom-center anchor. Ordinary gait changes are never automatically classified as camera zoom.
7. **Normalize occupancy and alignment:** every animation in a `group` receives one shared scale. Each animation receives one translation derived from its union bounds across the complete sequence, not per-frame stretching or recentering. Use an explicit `scale_multiplier` for a direction-specific adjustment.
8. **Resize outputs:** the default is premultiplied-alpha OpenCV Lanczos4. Every target size is generated directly from the work resolution; 32 px is not generated from the 64 px output. Rectangular aspect ratios are preserved without stretching. `nearest` and `box` are also available.
9. **Clean again and create mirrors:** each output resolution is cleaned again. Explicit mirror outputs are pixel-flipped from the processed source animation, keeping paired results deterministic.
10. **Deliver:** fixed full-canvas PNG sheets and JSON manifests, Aseprite files, optional individual PNG frames, original-length and requested-length previews, contact-sheet previews, a ZIP archive, and a processing report.
11. **Verify files:** Aseprite files are exported again and compared pixel-for-pixel with PNG sheets. Verification checks frame count, dimensions, duration, mirror relations, full-canvas grids, and APNG timing. It verifies file integrity, not the artistic quality of a motion.
12. **Respect engine boundaries:** optional Unity checks are read-only. Only an explicit `deploy` command replaces one specified PNG. The tool does not search game references, rewrite a project, alter Animator Controllers, or modify `.anim` files.

The tool expects character artwork that already has meaningful transparency. **It is not a background-segmentation model.** An opaque white background or a flattened checkerboard must be removed correctly before post-processing.

## Configuration

All relative paths are resolved from the directory containing the JSON config. Unknown or misspelled fields are errors instead of being silently ignored. See `examples/basic.json` and `examples/advanced.json`.

### Core options

| Field | Purpose |
| --- | --- |
| `name` | Delivery name using safe letters, digits, underscores, dots, and hyphens |
| `output` | A new delivery directory; existing paths and paths overlapping inputs are rejected |
| `work_size` | Work canvas `[width,height]`, such as `[512,512]` or `[768,512]` |
| `sizes` | One or more target sizes; rectangular sizes are supported |
| `resample` | `lanczos4`, `nearest`, or `box`; all use premultiplied alpha. OpenCV limits BOX affine transforms to linear, while final reduction uses area filtering |
| `cleanup.profile` | `off`, `conservative`, or `strict` |
| `layout.mode` | `preserve` keeps source occupancy and placement; `shared_fit` applies a fixed shared fit per group |
| `layout.occupancy` | Maximum union-bound occupancy for a group; default `0.9` |
| `layout.anchor` | Normalized bottom-center placement; default `[0.5,0.95]`. This is not an engine pivot |
| `layout.allow_upscale` | Whether a group's shared scale may exceed 1 |
| `export.aseprite` | Write Aseprite files; default true. PNG sheets and manifests always remain the delivery contract |
| `export.png_frames` | Also write separate transparent PNG frames |
| `export.previews` | Write animated previews |
| `export.preview_sizes` | Preview sizes, independent of delivery sizes |
| `export.preview_scale` | Integer nearest-neighbor enlargement for previews |
| `export.preview_frames` | Additional repeated preview length; default 48. It does not change delivered frame count |
| `export.zip` | Write a complete delivery ZIP without the work cache |

There is no top-level `layout.group`. Set `group` on animation entries. When omitted, all animations in one config share a group. Put different characters in separate groups or separate configs so they are not normalized together.

### Input formats

An Aseprite source:

```json
{"name":"walk_right","source":"../input/walk_right.aseprite"}
```

A horizontal PNG sprite sheet:

```json
{"name":"walk_right","source":{"path":"../input/sheet.png","frame_size":[512,512],"fps":16}}
```

A PNG frame sequence:

```json
{"name":"walk_right","source":{"path":"../input/frames","type":"sequence","glob":"*.png","durations_ms":[62,63,62,63]}}
```

- Sprite sheets are read row-first. When metadata is supplied, its frame rectangles take precedence; Aseprite `trimmed` and `sourceSize` metadata is supported.
- `durations_ms` may be one integer or one value per frame. Otherwise, source Aseprite/JSON timing is used. A PNG source without timing metadata must provide FPS or a duration; the tool does not guess.
- FPS is converted to integer millisecond durations by cumulative rounding. At 16 FPS, the result alternates 62/63 ms rather than forcing every frame to 62 ms.
- Frame sequence filenames use natural sorting, so `2.png` precedes `10.png`. Zero-padded names remain recommended for compatibility with other tools.
- A single PNG image can use `type:image` and still needs a frame duration.
- `init` first discovers Aseprite files in the selected folder. If none exist, it discovers PNG files with same-name JSON. Review the generated list for complex atlases, nested folders, or duplicate-resolution copies.

### Mirroring, reversing, and ping-pong

```json
{"name":"walk_left","mirror_of":"walk_right","axis":"horizontal"}
```

Animation names are labels and are not restricted to compass directions. The tool does not infer missing directions or overwrite authored directions. A mirror may reference a later entry and may chain through other mirrors, but mirror dependency cycles are rejected.

Set `reverse:true` to reverse a sequence. `pingpong` accepts:

- `none`: preserve the original sequence.
- `repeat_ends`: `0,1,2,3,4,5,6,7,7,6,5,4,3,2,1,0`; eight frames become sixteen, with repeated endpoints by explicit choice.
- `no_repeat_ends`: `0,1,2,3,4,5,6,7,6,5,4,3,2,1`; eight frames become fourteen.

### Match an edited low-resolution sequence to high-resolution frames

```json
{
  "name":"idle_front",
  "source":"../input/original_512.aseprite",
  "edited":"../input/user_edited_64.aseprite",
  "matching":{"allow_mirror":false,"max_error":0.12,"min_margin":0.002,"compare_size":64}
}
```

After a failed match, inspect `matching/idle_front.json` in the partial output. Override the result with a human-confirmed `frame_map:[12,13,14,15,0,1]`. Indices are zero-based. When `edited` is present, `frame_map` must contain exactly one entry per edited frame; edited durations remain authoritative.

Matching can reject uncertain input; it cannot guarantee recovery. Near-identical poses, aggressive edge cleanup, repainting, occlusion, and scale changes may require a manual map. Pixel-identical candidates are recorded as equivalent because choosing among them does not change output pixels.

### Progressive growth correction

```json
{"name":"walk_front","source":"../input/front.aseprite","zoom":{"start_scale":1.0,"end_scale":0.94,"easing":"smoothstep"}}
```

This example scales the last frame to 94% of the first-frame scale. `linear` easing is also supported. The correction is never enabled automatically. `report.json` records applied factors, bounds, areas, and the first/last area ratio. A zoom curve does not guarantee that the source animation remains a seamless loop. If the transform would crop visible content, processing stops rather than silently cutting the character.

### Fine-tune white-edge cleanup

The strict preset uses contour candidates, replacement from nearby valid colors, and small white connected-island processing. Every value can be overridden:

```json
{
  "profile":"strict",
  "edge_width":2,
  "reference_radius":4,
  "alpha_cutoff":8,
  "dust_area":4,
  "opaque_luminance":178,
  "partial_luminance":150,
  "opaque_saturation":0.38,
  "partial_saturation":0.48,
  "opaque_gap":16,
  "partial_gap":12,
  "passes":12
}
```

Widths, radii, and connected-component areas are measured in pixels at the current processing stage. Compare `conservative` and `strict` on representative frames first. Interior white is not removed by a global threshold, but legitimate white touching the silhouette may still be identified as contamination. A `detector_residual` of zero means only that this detector found no remaining candidates; it is not human visual approval. Even with cleanup disabled, hidden RGB is cleared wherever alpha is zero to prevent later color bleeding.

## Output contract

```text
result/
  config.resolved.json       complete resolved config and absolute source paths
  report.json                scaling, provenance, cleanup, warnings; complete or failed
  verification.json          file verification result
  512px/, 64px/, 32px/       names follow the actual configured sizes
    aseprite/*.aseprite       full-canvas, single-layer RGBA delivery files
    sheets/*.png             horizontal sheets without trimming, rotation, or reordering
    sheets/*.json            rectangles, indices, millisecond timing, provenance, pivot
    frames/<name>/*.png      optional individual frames
  previews/<size>/            original-length and requested-length GIF/APNG/contact sheets
  matching/*.json             generated for matching jobs
  work/                       Aseprite source export cache; excluded from ZIP
  <name>_delivery.zip
```

- Exported Aseprite files are flattened to one RGBA layer and preserve delivered pixels, frame order, and duration. Source layers, slices, palette, tags, and arbitrary metadata are not guaranteed. Original Aseprite files are never modified.
- Previews use nearest-neighbor enlargement. APNG preserves millisecond timing; GIF has a 10 ms timing quantum and therefore approximates some durations. Contact sheets sample by actual time and are not resampled game animations.
- If a 16-frame animation requests a 48-frame preview, the preview repeats the loop three times; it does not claim that 48 new frames were created.
- An output directory containing files is rejected. The tool does not silently resume, overwrite, or delete an old delivery. A failed run keeps its report and intermediate files; correct the config and choose a new output directory.
- Passing cleanup detection, opening a file, or passing static import checks is not presented as visual in-game acceptance.

## Optional Unity adaptation

The core is not tied to Unity. For Unity projects, this command performs a read-only static check:

```powershell
python spritepost.py unity-check "E:/MyGame/Assets/Sprites/Creature" --config "E:/Jobs/creature.json"
```

It reads `.png.meta` and `.aseprite.meta` files and checks full frame rectangles, Full Rect mesh type, Point filtering, mipmaps, compression, pivot, IDs, and texture size limits. It inspects metadata for the currently enabled Aseprite import mode so inactive tight-mesh data is not reported as active. Unknown serialization versions produce warnings instead of false claims.

`unity.pixels_per_unit` and `unity.pivot` are configurable. `require_full_rect`, `require_point`, `require_no_mipmaps`, and `require_uncompressed` can be disabled. These settings affect optional checks and manifests; they are not forced on unrelated projects.

To explicitly replace one existing PNG:

```powershell
python spritepost.py deploy --sheet "E:/Delivery/creature/64px/sheets/walk_right.png" --manifest "E:/Delivery/creature/64px/sheets/walk_right.json" --destination "E:/MyGame/Assets/Sprites/Creature/walk_right.png" --backup-dir "E:/Backups/Creature"
```

- An existing target must already have a `.meta` file and must match the manifest's dimensions, frame count, full rectangles, and order. Mismatches are rejected to prevent frame skipping and reference changes.
- The original PNG and `.meta` are backed up, then only the PNG is atomically replaced. The `.meta`, GUID, SpriteIDs, and `.anim` files are not changed. The backup must be outside `Assets` and outside the target directory.
- A new destination receives only the PNG. The tool does not invent a `.meta`; the target engine owns first import.
- This is not an Animator or AnimationClip rebuilding tool. Other engines can consume the manifest's cumulative timing and fixed rectangles through their own importer.
- Generated files are never automatically written to a project, and no project-specific migration scripts are invoked. Static validation does not replace import, reference, and playback checks in the target engine version.

## Troubleshooting

### “The output directory already exists”

Choose a new empty path, such as `creature_delivery_v02`. The safety rule prevents accidental destruction of an accepted delivery. A config file also must not be stored inside its own output folder; place it beside that folder, for example `E:/Jobs/creature.json` with output `E:/Delivery/creature`.

### Missing Python package or Python not found

Run **Environment Check** or `Start.cmd doctor`. Create `.venv`, install `requirements.txt`, and select the interpreter with `Start.ps1 -Python`, `SPRITEPOST_PYTHON`, or `runtime.local.json`. Do not copy another computer's absolute runtime config.

### Aseprite is not found

PNG-only operation works when `export.aseprite` is false. Otherwise select the Aseprite executable in the GUI, set `SPRITEPOST_ASEPRITE`, put it on `PATH`, or set the config field `aseprite` to its local path.

### Frame matching is ambiguous

Open the generated file under `matching/`, compare the candidates, and supply an explicit zero-based `frame_map`. Do not increase thresholds until an incorrect match merely stops reporting an error.

### White details were removed, or white contamination remains

Use `conservative` or `off` for valid white silhouette details. Use `strict` only for contaminated edges and review representative frames. Fine-tune edge width, luminance, saturation, gap, dust area, and pass count when a preset is too weak or too aggressive. The cleanup stage does not replace proper background segmentation.

## Regression tests and release packaging

```powershell
python -m unittest discover -s tests -v
python -m compileall -q spritepost tests gui.py spritepost.py
python build_release.py
```

Real Aseprite tests run when Aseprite is available and are explicitly skipped otherwise. The release archive includes the tool, examples, documentation, and tests. It excludes machine-local paths, personal artwork, runtime caches, and game project content.
