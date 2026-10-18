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

### World: labels and click-to-zoom
- Every named part of the site is now a "place" in `world.json` (62: six
  zones plus buildings, shelters, enclosures, paddocks, pools, ponds,
  paths), each with a short description, a size and a walkable standing
  point outside buildings, fences and water (`export_web.py`).
- 3D name labels on all of them, in three tiers so the view never fills
  with text: zone names from afar, main places within 350 m, small things
  (night houses, ponds in paddocks, parking) within 90 m. Labels behind the
  viewer or behind a building are hidden (exact test against building
  footprints; see-through fences and open sheds don't hide anything).
- Click a label: the camera flies there (orbit view, 1.4 s eased arc) and
  a card shows the name, zone and description, with "Zoom to it" and
  "Walk here". Double-click anywhere in orbit view zooms to that spot and
  opens the card of the place under it.
- The overview map shows every main place as a dot (name on hover); click
  one to fly there, in any zone. Walking is no longer limited to the
  current zone: the whole site is walkable.
- Fixed while testing: labels showing mirrored for places behind the viewer;
  labels through buildings; duplicate "Entrance plaza" label; HUD title now
  follows the selected place.

## 2026-10-18

### World: fuller forest and real water (in Blender, then dropped)
- Designed in Blender: ponds, the wallow and the lakes became basins (holes
  cut in every ground layer, sloped wet banks, a bed, see-through water that
  is light at the edges and dark in the middle, a wet-mud shore band);
  the hydrotherapy pool got walls, a floor and an elephant ramp. About 3x the
  trees: a closed woodland with understory, avenues along the internal
  roads, shade in every yard, planted shores, a darker woodland floor.
  Animals cut by 40% (15 -> 9: 4 elephants, 3 tigers, 2 rhinos).
- Problem: the laptop's Intel Iris Xe can't render the full scene. EEVEE ran
  out of GPU memory (blank frames), and Blender hung twice; the screen
  flashed as Windows reset the graphics driver. Lighter settings (fewer
  samples, smaller shadow pool, solid viewport) only delayed it.
- Decision: remove Blender from the workflow. The browser explorer already
  runs the world at 60 fps, so the world will be built in the browser from
  the data files instead.

### No-Blender step 1: world compiler
- `world/scripts/compile_world.py` (+ `worldgeo.py`, plain Python) turns
  `site.json` + `layout.json` into `world/publish/world/world.json`: every
  ground layer (with holes for water), road, wall, building, roof, window,
  fence, water basin, the pool, every plant and animal, the 61 places, as
  simple primitives the browser will turn into meshes. Also writes the
  per-zone metadata files.
- Same scene as the Blender version (794 trees, 670 bushes, 1,084 shrubs,
  69 rocks, 316 windows, 9 animals), in 3.5 s instead of ~6 min, and
  0.31 MB of data.
- `world/tests/test_compile_world.py`: 11 checks (deterministic, plants inside
  the site and off buildings, animals out of the water, water cut out of the
  ground, basins slope down, materials defined, places have standing spots,
  sun position). Found and fixed: the eastern lake reaches 5.8 km out, past
  the 10 km ground square, so it got no hole; the ground is now 14 km.
- Not yet: the explorer still expects the old Blender export, so it shows an
  error until step 3 (the browser builder) lands.

### No-Blender step 2: textures and plant models
- `world/scripts/prepare_textures.py` (OpenCV): surface textures for the web
  (colour 1024 px, normal maps 512 px) -> `world/publish/world/textures/`,
  2.7 MB; stages 512 px copies of the plant textures.
- `world/tools/build_plants.mjs` (Node: gltf-transform 4.5.1 + meshoptimizer
  1.3.0, MIT; `world/tools/node_modules` is gitignored): every plant variant
  as a near and a far model in one `plants.glb` (3.6 MB, built in ~5 s),
  base centre at the origin, meshopt-compressed.
  - Bark, branches: shape-preserving simplification only. The first try also
    allowed "sloppy" simplification, which broke the tree trunk.
  - Leaves: keep a random share of whole leaves and enlarge each kept leaf
    about its centre, so the canopy thins far less than the face count.
  - Budgets (near/far faces): tree 60k/10k, bush 6k/1.5k, shrub 3k/1k,
    rock 3k/500. The boulder Blender couldn't reduce below 26k is now 2.9k.
- `world.json` now names its assets; a test checks every texture and plant
  variant it references exists. 12 tests pass.
- Web world total: ~6.6 MB (Blender export was 11.6 MB).

### three.js docs check (for step 3)
Read the current docs (threejs.org/docs, r186) before building:
- `BatchedMesh`: different geometries, one draw call, per-object frustum
  culling (`perObjectFrustumCulled`) and `setGeometryIdAt` to swap a plant's
  level of detail in place -> plants.
- `ShapeUtils.triangulateShape(contour, holes)` (Earcut) -> ground layers
  with pond and lake holes.
- `BufferGeometryUtils.mergeGeometries` -> buildings, fences, windows merged
  into a few meshes per material.
- `Material.polygonOffset` (stacked ground layers), `alphaHash` /
  `alphaToCoverage` (leaf edges), `vertexColors` (graded water).
- `LightShadow.autoUpdate` / `needsUpdate`: the world and sun are static, so
  the shadow map only needs redrawing when the shadow area moves or animals
  move.
- `GLTFLoader.setMeshoptDecoder` + `KHR_mesh_quantization` /
  `EXT_meshopt_compression` are supported (plants.glb). The CSM cascaded
  shadows add-on exists but is heavier; keeping one shadow area that follows
  the viewer for the Iris Xe.

### No-Blender step 3: the world built in the browser
- `web/src/components/explorer/world/`: `geometry.ts` (one GeometryBuilder per
  material; ground with holes via `ShapeUtils.triangulateShape`, ribbons,
  prisms, gables, boxes, basins, pool; faces turned the right way, UVs in
  world metres / tile), `materials.ts` (Poly Haven textures loaded once and
  shared, polygon offset per ground layer, generated chain-link, vertex-
  coloured water), `plants.ts` (one `BatchedMesh` per plant material,
  per-plant culling, level of detail swapped in place with
  `setGeometryIdAt`; distant trees as billboards rendered on the viewer's
  machine into a front|side atlas), `build.ts` (assembles it all once per
  session, plus the collision mesh: every solid surface, shore walls, tree
  trunks and rocks).
- `WorldScene` now only shows the built world; the sun shadow map is redrawn
  only when its area moves or every 3rd frame (`shadow.autoUpdate = false`).
- No Blender anywhere: the explorer reads world.json, textures and
  plants.glb (about 6.6 MB).
- Measured in the browser pane: spawn view 51k triangles / 30 draw calls;
  inside the woodland 2.5M triangles / 29 draw calls; aerial 43k triangles /
  42 draw calls; 60 fps on the Iris Xe.
- Bugs found and fixed while testing:
  - Textures 404'd: the dev asset route only served files directly in a zone
    folder; it is now a catch-all route that checks every path segment
    (`..` is rejected).
  - Near trees were invisible while their shadows showed: the billboard step
    had rendered the trees' own materials on plain meshes first, so three.js
    kept those materials compiled for non-batched drawing and the batches
    drew nothing. The billboard renders now use material copies.
- Checked: woodland (full canopy, understory, shade), bathing pond (wet
  shore, water), aerial (matches the Blender render), collision with pond
  shores and tree trunks.
- Not yet polished: pond water looks pale/mirror-like from low angles.

### No-Blender step 4: vector overview map
- `world/scripts/overview_map.py` (called by `compile_world.py`) draws the
  map as an SVG from the same data as the 3D world: ground layers, water,
  roads, railway, streams, wall, fences, tree and bush canopies, buildings
  and shelters. `web/public/map/overview.svg`, 124 kB, sharp at any size;
  replaces the Blender render (`overview.webp`, deleted). Zone positions in
  `zones.json` are written from the same frame (unchanged), and the map
  overlay's caption now says it is drawn from the data.

### No-Blender step 5: Blender removed
- Deleted (still in git history): `world/scripts/build_site_base.py`,
  `build_zones.py`, `dress_zones.py`, `export_web.py`, `render_previews.py`,
  `pipeline/vantara_pipeline/blender_bridge.py`,
  `pipeline/blender/prepare_animals.py`, `.mcp.json` (its only entry was the
  Blender MCP server).
- Deleted local files (never in git): `world/vantara_world.blend` and its
  backup (78 MB each), the 18 Blender preview renders.
- READMEs (root, world, web, pipeline), code comments, `animals.json` and
  `.gitignore` updated; the only remaining mentions of Blender are history.
- The animal GLBs stay as they are (made once in Blender); a replacement must
  already be a GLB facing +Z at real size, and `animals.json` is edited by hand.
- Checks: 12 world tests, 22 pipeline tests, web typecheck and lint pass; in
  the browser the world loads with every asset 200 and the map overlay shows
  the vector map with zone and place dots in place.

### Polish: water, animals tool, site pages
- Pond and lake water no longer mirror the sky: a physical material with
  lower reflectance and more roughness, murkier colours, and a generated,
  tileable ripple normal map that drifts slowly (`BuiltWorld.tick`).
- Animals: `world/tools/build_animals.mjs` (gltf-transform + sharp:
  textures to 1024 px WebP, unused data removed, meshopt) for the planned
  CC-BY Sketchfab set. The explorer now sizes each animal when it loads
  (precise skinned bounds -> `heightM`, feet on the ground, `yawDeg` to face
  +Z), which is safe for rigged models and keeps the placeholders unchanged.
  The Sketchfab files weren't downloaded; the placeholders stay for now.
- Site: home page with the vector map and an Explore link on every zone; new
  `/credits` page (map data, Poly Haven assets, animals, software); footer
  with OpenStreetMap credit and a Credits link; page metadata (title
  template, Open Graph, theme colour). The four zones are now `live` in
  zones.json (production shows only live zones).

### Deploy preparation (nothing deployed, nothing pushed)
- `web/scripts/upload-assets.mjs` (`pnpm assets:upload`): uploads only an
  allow-list built from world.json, zones.json and animals.json (28 files,
  7.2 MB) to a public Vercel Blob store at fixed, versioned paths (`v1/`),
  cached for a year; refuses anything outside `world/publish` and
  `public/models` (so the private test footage in `pipeline/work` can't go),
  symlinks and unknown file types; never prints the token. `--dry-run` lists
  the files; after uploading it checks CORS.
- CORS fallback: with `ASSET_ORIGIN` set, next.config.ts serves the Blob
  files from the site's own origin under `/assets` (validated https origin).
- Draco decoder copy removed (the world uses meshopt now).
- Deploy steps in `web/README.md`. Production build passes.
