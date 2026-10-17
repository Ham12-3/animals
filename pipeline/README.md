# Pipeline

Python tooling that turns walkthrough videos into Gaussian splats. Runs on CPU;
GPU-only steps get a Google Colab notebook.

```bash
uv sync                      # Python env (opencv, numpy)
uv run pytest                # synthetic-video tests
```

Requires FFmpeg (`ffmpeg`, `ffprobe`) on PATH. COLMAP comes from the `pycolmap`
wheel (CPU), so nothing else to install.

## Phase 2: frame extraction

```bash
uv run extract-frames <zone-id>      # zone ids come from ../zones.json
uv run extract-frames --all
```

Reads videos from `input/<zone>/` (the `videos` list in zones.json, or every
video in the folder), and writes `work/<zone>/`. A zones.json entry can use part
of a video: `"tour.mp4#t=95,131"` (seconds).

For footage that is not (yet) a zone, run ad hoc:

```bash
uv run extract-frames --name trial --video a.mp4 --video "b.webm#t=95,131"
```

| Output | |
| --- | --- |
| `frames/` | Kept frames. `v01_000123.jpg` = video 1, sample 123, so name order = walking order (needed by COLMAP's sequential matcher). |
| `masks/` | Only when a fixed logo/watermark/timestamp was found: COLMAP masks (black = ignore). |
| `rejected/<reason>/` | Thumbnails of every dropped frame, to check the filters. |
| `contact_sheet.jpg` | All kept frames on one image. |
| `frames.csv` | Scores and decision for every sampled frame. |
| `extract_report.json` | Counts, warnings, and the thresholds used. |

### How frames are chosen

1. **Sample** with FFmpeg at 2-3 fps (auto: ~900 raw frames for the zone), long side capped at 2560 px. HDR (HLG/PQ) is tone-mapped to SDR.
2. **Blur**: Laplacian variance below 0.35x the video's median (or an absolute floor), or below half of its neighbours' median (camera shake).
3. **Motion blur**: soft frames whose gradients all point one way (structure-tensor coherence).
4. **Text overlays**: text-shaped regions that stay fixed on screen while the scene moves. Captions/titles covering >1% of the frame drop the frame; overlays present in most of a video (logos, timestamps) are masked instead.
5. **Near-duplicates**: perceptual hash. Runs of look-alike frames (camera paused) keep only the sharpest; near-identical frames anywhere in the zone are dropped.
6. **Budget**: above 400 frames, the walk is split into 400 equal stretches and the sharpest of each is kept. Below 150, the report says why and what footage to add.

Tuning flags: `--fps`, `--max-size`, `--blur-rel`, `--dup-hamming`,
`--text-max-area`, `--no-text-filter`, `--min-frames`, `--max-frames`,
`--keep-raw`. See `uv run extract-frames --help`.

### Edited footage: pick the usable shots first

Vlogs and documentaries cut every few seconds. `find-shots` splits a video at
its cuts and writes `<video>.shots.json` plus `<video>.shots.jpg`, a numbered
sheet of every shot of 4 s or longer with a moving camera:

```bash
uv run find-shots input/some-zone/tour.webm
```

Pick shots that show the same place and pass them as `#t=START,END` ranges.

## Phase 3: camera poses (COLMAP)

```bash
uv run solve-poses <zone-or-name>
```

SIFT features at 1600 px on CPU, sequential matching (with quadratic overlap so
repeat passes over a spot link up), then incremental mapping. Writes
`work/<zone>/colmap/`: `sparse/0` (the largest model), `undistorted/` (input for
splat training), `points.ply`, `topdown.jpg`, and `poses_report.json`. Below 70%
registration the report says why (blur, too little overlap, disconnected
places) and what footage would fix it.

Flags: `--camera per-video|single|per-image` (default: one camera per source
clip), `--matcher exhaustive` for small sets, `--max-image-size`.

## Phase 4: splat training

### Locally with Brush (any GPU, no CUDA)

Unpack the [Brush](https://github.com/ArthurBrussee/brush/releases) Windows
release (v0.3.0) into `pipeline/tools/brush/` (or set `BRUSH_BIN`), then:

```bash
uv run train-splat <zone-or-name>            # 30k steps at 1600 px, PLY out
uv run train-splat <zone-or-name> --resume   # continue after an interruption
```

Builds `work/<zone>/splat/dataset/` from the undistorted COLMAP model
(`images/`, `sparse/0/`, and `masks/` warped into the undistorted frames), runs
Brush headless, and writes `work/<zone>/splat/<zone>.ply` plus
`train_report.json`. Extra flags pass straight to Brush (e.g. `--max-splats`).

Brush 0.3.0's console progress bar panics (an `indicatif` ETA bug, exit code
`0xC0000409`). On a slow GPU it happens every few minutes, because the bar's
speed estimate decays to zero between steps. Two defences:

- The wrapper checkpoints every 1000 steps and restarts from the latest one
  (`init.ply` + `--start-iter`), so a crash costs at most 1000 steps.
- `--viewer` trains inside Brush's window instead, which has no such progress
  bar. Use it on laptops; leave the window open (minimising is fine).

Measured on an Intel Iris Xe (shared memory): about 30-45 steps/min, so 30k steps
take 12-14 hours. Brush's viewer also starves the browser of GPU time while it
runs. For real zones prefer the Colab notebook below.

### On a Colab GPU with gsplat

[`colab/train_splat_gsplat.ipynb`](colab/train_splat_gsplat.ipynb) trains the
same dataset with gsplat 1.5.3 on a T4 (tested end to end on a public 251-image
scene, masks included). Make the upload:

```bash
uv run train-splat <zone> --prepare-only --zip   # -> work/<zone>/splat/<zone>-dataset.zip
```

Put the zip in Google Drive, open the notebook in Colab, set `ZONE` and
`DATASET_ZIP`, and run all cells. Masks are honoured (masked pixels carry no
loss). Only upload footage you have the rights to.

## Phase 5: cleanup, alignment, compression

```bash
npm install                          # once, in pipeline/: installs splat-transform (pinned)
uv run publish-splat <zone-or-name>
```

Reads `work/<zone>/splat/<zone>.ply` plus the COLMAP model and writes
`work/<zone>/publish/`:

| Output | |
| --- | --- |
| `<zone>.spz` | Desktop build: highest SH degree (view-dependent colour) that fits 40 MB, decimated if needed. |
| `<zone>.mobile.spz` | Mobile LOD: SH0, at most 500k splats, under 15 MB. |
| `<zone>.json` | For the web app: units (metres), ground at y = 0, bounds, spawn point and heading, camera path (for flyover), field of view, north. |
| `preview_before.webp`, `preview_after.webp`, `preview_mobile.webp` | Renders from the first camera, before/after cleanup. |
| `topdown.webp` | Plan view, for setting north. |
| `publish_report.json` | Splats removed at each step, alignment, warnings. |

**Alignment** (exact, in Python: positions, orientations, scales and SH
coefficients are all rotated):

- *Level ground:* RANSAC plane through the SfM points below the cameras, normal
  within 25 deg of the cameras' average up. It becomes y = 0, +Y up.
- *Scale:* metres, assuming the camera was carried 1.5 m above the ground.
  Override per zone with `align.eyeHeight` or `align.scale` in zones.json.
- *North:* video can't tell. -Z is the main walking direction until you set
  `align.northDeg` (the compass heading of -Z: compare `topdown.webp` with a
  satellite map).

**Cleanup:** drops near-transparent splats (opacity < 2%), smears wider than
3 m, everything outside the reconstructed area (SfM extent plus margin), and
floaters not contributing to any solid 5 cm voxel (`splat-transform -F`).

Check a published zone locally: `pnpm dev` in `web/`, then open
`http://localhost:3000/dev/spark?zone=<zone>`. It loads straight from
`pipeline/work` through a development-only route, so nothing private is copied
into the web app.

## Phase 7: animals

Models live in Blender (driven through the MCP-for-Blender add-on socket, see
`vantara_pipeline/blender_bridge.py`), one collection per animal named
`Animal: <name>`. Then:

```bash
uv run python -m vantara_pipeline.blender_bridge execute_code \
  --code "exec(open('blender/prepare_animals.py', encoding='utf-8').read())"
```

`blender/prepare_animals.py` poses each model at rest, scales it to real height,
centres it with feet on the ground facing glTF +Z, gives untextured meshes a
realistic flat albedo, and exports `web/public/models/<name>.glb` (modifiers
applied, skin + every action as a clip). It writes
`web/src/content/animals.json` (sizes, clips, idle/walk clip names, credits).
Edit the `ANIMALS` table at the top to add or swap models.

Current models are CC0 low-poly placeholders (see `web/public/models/CREDITS.md`):
only the elephant has clips and none has a walk cycle, so the explorer adds a
procedural gait. Swap in the realistic CC-BY set by importing them into the
same collections and re-running the script.

`publish-splat` also estimates each zone's **lighting** for these meshes:
opaque flat splats give surface normals and colours, a first-order spherical
harmonic fit gives ambient + sun (direction and colour), written to
`<zone>.json` as `lighting` (irradiance, linear RGB, assuming 35% average
albedo; the sun is kept above the horizon).
