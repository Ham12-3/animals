# Vantara world (Blender): artistic interpretation

A Blender recreation of Vantara built from open map data, for when there is no
footage to reconstruct from.

> **Artistic interpretation.** Only Vantara's outline, the surrounding roads,
> water and railway come from map data. Everything inside the site (enclosures,
> buildings, pools, planting) is designed from public descriptions, not
> surveyed. Not affiliated with or endorsed by Vantara.
>
> Map data © OpenStreetMap contributors, available under the
> [Open Database License](https://www.openstreetmap.org/copyright).

## Files

| | |
| --- | --- |
| `data/vantara_area.osm` | Raw OpenStreetMap extract, 6 x 6 km around Vantara (ODbL) |
| `data/site.json` | Outline, roads, water, rail in metres around Vantara's centre (X east, Y north) |
| `scripts/osm_to_json.py` | `vantara_area.osm` -> `site.json` |
| `scripts/build_site_base.py` | Builds the Blender scene from `site.json` (runs inside Blender) |
| `data/layout.json` | Designed zone layout (artistic interpretation), from `design_layout.py` |
| `scripts/design_layout.py` | Writes `layout.json`; checks everything sits inside the outline |
| `scripts/build_zones.py` | Builds the zone blockouts from `layout.json` (runs inside Blender) |
| `scripts/fetch_polyhaven.py` | Downloads the CC0 Poly Haven textures and models into `assets/` (not in git) |
| `scripts/dress_zones.py` | Step 3 dressing: textures, building detail, water, fences, vegetation, animals (runs inside Blender) |
| `scripts/export_web.py` | Step 4: exports the world for the web explorer to `publish/` (not in git) and renders the overview map |
| `scripts/render_previews.py` | Renders every preview camera to `renders/` (runs inside Blender) |
| `vantara_world.blend` | The scene (not in git; rebuild it with the scripts) |
| `renders/` | Preview renders (not in git) |

## Rebuild

```bash
uv run --project pipeline python world/scripts/osm_to_json.py
cd pipeline
uv run python -m vantara_pipeline.blender_bridge execute_code \
  --code "exec(open('../world/scripts/build_site_base.py', encoding='utf-8').read())"
```

Needs Blender running with the MCP-for-Blender add-on connected (port 9876).
The build replaces everything in the open file, so it should be the world file.

## Step 1 (done): site base

- Real-scale ground (10 km), Vantara's mapped outline (1,104 x 324 m) on
  landscaped ground with a 2.2 m perimeter wall
- Roads at real widths (tertiary 7 m, local 5-5.5 m, service 4 m), lakes,
  streams, the Kanalus railway
- Physical sky, with the sun placed for Jamnagar (22.33 N) at 10:00 IST on
  15 March: 39.5 deg elevation, from the east-south-east
- Aerial and south-gate cameras; label "artistic interpretation" with the
  OpenStreetMap credit in the scene

## Step 2 (done): zone blockouts

`scripts/design_layout.py` -> `data/layout.json` -> `scripts/build_zones.py`.
Zones sit in the blocks formed by the real internal roads; their contents are
designed. Elephant Care Centre (shelters, sand yards and paddock, bathing
pond, mud wallow, hydrotherapy pool, kitchen), Wildlife Hospital, Big Cat
Rescue (10 fenced enclosures + a large one), Herbivore Reserve (3 paddocks),
entrance plaza. The west wedge is left as woodland.

```bash
uv run --project pipeline python world/scripts/design_layout.py
cd pipeline
uv run python -m vantara_pipeline.blender_bridge execute_code   --code "exec(open('../world/scripts/build_zones.py', encoding='utf-8').read())"
```

## Step 3 (done): dressing

CC0 Poly Haven textures on every surface, seeded scatter of trees, shrubs and
boulders, windows/doors/parapets/rooftop plant on buildings, chain-link fences,
water, and the CC0 placeholder animals in their zones. Assets: Poly Haven
(polyhaven.com), CC0.

```bash
uv run --project pipeline python world/scripts/fetch_polyhaven.py
cd pipeline
uv run python -m vantara_pipeline.blender_bridge execute_code   --code "exec(open('C:/Users/mobol/Downloads/animals/world/scripts/dress_zones.py', encoding='utf-8').read())"
uv run python -m vantara_pipeline.blender_bridge execute_code   --code "STEP='step3'; exec(open('C:/Users/mobol/Downloads/animals/world/scripts/render_previews.py', encoding='utf-8').read())"
```

Blender resolves relative paths from its own folder, so pass absolute paths.
Rendering all cameras takes ~20 minutes on the laptop.

## Step 4 (done): web export

```bash
cd pipeline
uv run python -m vantara_pipeline.blender_bridge execute_code   --code "exec(open('C:/Users/mobol/Downloads/animals/world/scripts/export_web.py', encoding='utf-8').read())"
```

Writes `publish/world/` (manifest, glTF parts with shared textures,
instanced plants with two levels of detail, collision mesh) and
`publish/<zone>/<zone>.json` for each explorer zone, renders
`web/public/map/overview.webp` and updates the map positions in `zones.json`
(skip the render with `RENDER_MAP=False; ` before `exec`). The dev server
serves `publish/` under `/dev-assets`; open `/explore?zone=elephant-care-centre`.
About 12 MB in total.
