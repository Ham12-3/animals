# Development log

Plain-language record of what was built, what was learned, and what is still
open. Newest entries at the bottom of each day.

## 2026-10-17

### Phases 1-2: setup and frame extraction (`f6c9fa2`)
- Monorepo: `pipeline/` (Python) and `web/` (Next.js 16 + React Three Fiber +
  Spark). `zones.json` lists the four planned zones.
- `extract-frames` turns videos into sharp, non-duplicate frames. Tested on a
  synthetic video with planted blur, captions and pauses: all caught.

### Phase 3: camera poses (`f6c9fa2`)
- `solve-poses` runs COLMAP on CPU. Tested on a private YouTube clip
  (Forrest Galante's tour, local only, never published): 40% of frames
  registered, because edited vlogs jump between rooms. Lesson: needs continuous
  walkthrough footage.

### Phase 4: splat training (`f6c9fa2`)
- Brush on the laptop's Iris Xe works but needs ~14 h for 30k steps and its
  progress bar crashes it; added auto-resume and a viewer mode.
- Colab notebook (gsplat) tested end to end on a public scene. Decision: real
  zones train on Colab.

### Phase 5: cleanup and compression (`f6c9fa2`)
- `publish-splat`: level ground, metric scale, floater removal, desktop and
  mobile SPZ, collision mesh, previews. Tested on the private kitchen splat.

### Phase 6: web explorer (`93b8230`)
- `/explore`: walk (WASD, phone joystick) with collision, orbit, flyover, map
  with fade transitions, loading screen, hotspots. 60 fps on the laptop.

### Phase 7: animals (`fdd2e97`)
- Blender (via MCP for Blender) prepares animal GLBs; explorer walks them on
  paths, lit by lighting fitted to the splats. Models are CC0 low-poly
  placeholders (realistic CC-BY ones need a Sketchfab account).

### Status check
- Everything above works, but there is no real Vantara footage, so the only
  visible result was a blurry test kitchen. Phase 8 (deploy) paused.
- **Change of direction:** build Vantara in Blender from open map data, as an
  artistic interpretation, and reuse the explorer for it.

### World step 1: site base
- OpenStreetMap only has Vantara's outline (1,104 x 324 m) plus nearby roads,
  lakes and railway; nothing inside the site is mapped.
- `world/`: OSM extract -> local metres -> Blender scene with the real outline,
  roads at real widths, lakes, railway, Jamnagar sky and sun (10:00, 15 March),
  label "artistic interpretation" + OSM credit.
- Fixed along the way: washed-out exposure, ground too small, lakes hidden
  under the ground, depth flicker between layers, duplicate objects on rebuild.

### World step 2: zone blockouts
- Zones follow the blocks formed by the real internal service roads (from
  OSM). What is inside each block is designed (artistic interpretation):
  - Elephant Care Centre (central block, ~370 x 260 m): six open shelters with
    sand yards, a 270 x 105 m sand paddock with a bathing pond and mud wallow,
    a hydrotherapy pool, the elephant kitchen, a care office.
  - Wildlife Hospital (beside the roundabouts): main block (3 storeys),
    surgery/ICU wing, two recovery wards, ambulance bay, parking.
  - Big Cat Rescue: 10 enclosures (50 x 42 m, 5 m mesh fences) with night
    houses on a central visitor path, plus one large enclosure with a pool.
  - Herbivore Reserve: three paddocks against the east boundary, each with a
    pond and shade shelter.
  - Entrance plaza at the south gate (gatehouse, visitor centre).
  - West wedge left as woodland: nothing published to base it on.
- `world/scripts/design_layout.py` writes the layout as data (`layout.json`)
  and checks every item lies inside the mapped outline;
  `world/scripts/build_zones.py` builds it in Blender (one collection per
  zone) with five preview cameras.
- Fixed: kitchen overlapping the paddock fence; ground-level cameras against
  fences; zone names painted on the ground now hidden at eye level.
- Renders: `world/renders/step2_*.png`. Still blockout level: plain
  materials, no trees, windows or textures yet (step 3).

### World step 3: dressing
- `world/scripts/dress_zones.py` (runs after `build_zones.py`) re-skins and
  dresses the blockout; `world/scripts/render_previews.py` renders every
  preview camera to `world/renders/step3_*.png`.
- Real CC0 textures from Poly Haven (10 sets, 1k, ~20 MB): dry ground, sand,
  withered grass, asphalt, red sandstone paving, white and yellow plaster,
  corrugated iron, clay roof tiles, mud. Box-projected in world metres, with
  large-scale colour variation and a second rotated sample so tiling doesn't
  show. Downloaded by `world/scripts/fetch_polyhaven.py` into
  `world/assets/` (gitignored, ~103 MB with the models).
- Vegetation (Poly Haven CC0 models, placed by a seeded scatter that keeps
  clear of buildings, roads, fences, water and the outline): ~260 shade trees
  (woodland wedge, grounds, shade in every enclosure and paddock), ~360 small
  trees, ~560 shrubs, ~40 boulders in the enclosures. The 1M-polygon tree is
  decimated to 200k and scaled to a 6-8 m shade tree. The bermuda-grass model
  was downloaded but not used: its tufts are 10 cm, invisible at site scale.
- Buildings: 316 windows by storey (clerestory band on the kitchen hall),
  doors, parapets, rooftop AC units and tanks, hospital entrance canopy.
- Chain-link fence shader, murky pond water, blue hydrotherapy pool.
- The 15 CC0 placeholder animals (6 elephants, 5 tigers, 4 rhinos) placed in
  their zones.
- Colour fix: renders were washing out grey-blue (sky too strong against the
  sun, sun counted twice, Filmic). Now: sun 4.5, sky fill 0.10, sky sun disc
  off, "Khronos PBR Neutral" view, exposure -1.0.
- Cost: a frame now takes 2-4 minutes on the laptop's Iris Xe (was ~10 s).
- Still placeholder: the low-poly animals; building shapes are simple boxes.

### World step 4: the Blender world in the web explorer
- `world/scripts/export_web.py` (runs in Blender after `dress_zones.py`)
  writes `world/publish/` (gitignored): `world/world.json` (manifest),
  `site.gltf` (ground, roads, wall, water, rail), `buildings.gltf` (zones +
  building detail), `plants.gltf`, `collision.glb`, shared textures, and one
  `<zone>/<zone>.json` per explorer zone (spawn, bounds, flyover loop).
- Blender's world-space materials don't export to glTF, so export copies get
  plain glTF materials with UVs generated in world metres per texture.
- Size: 11.6 MB for the whole site (budget 40 MB). Draco-compressed meshes,
  colour maps 1k, normal/AO maps 512, no roughness maps on surfaces.
- Plants: each variant exported twice (near: tree 30k faces; far: tree 4k),
  drawn as GPU instances. Near detail within 60 m; shrubs and rocks hidden
  beyond 150 m, bushes beyond 260 m. First try drew 4.4M triangles (23 fps
  on the Iris Xe); now ~1.6M at 60 fps.
- Explorer: a zone's metadata can now point at a mesh world instead of a
  splat. The world (sky, sun shadows following the viewer, Khronos PBR
  Neutral tone mapping like the Blender renders) stays loaded across zones,
  so jumping between zones on the map is instant. Collision, walk, orbit,
  flyover and the 15 animals (with real shadows) all work in it.
- Overview map: a top-down render of the model (`web/public/map/overview.webp`);
  the zone positions in `zones.json` now match it.
- Fixed: zone listing showed the shared "world" folder as a zone; pointer
  lock errors in embedded browsers (mouse drag-to-look now works as fallback);
  first lighting pass too bright and flat (sky light halved, warmer sun).
- Known: far trees (4k faces) look thin; `boulder_01` won't decimate below
  26k faces (19 instances, acceptable); animals are still the low-poly
  placeholders.
