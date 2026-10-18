# Vantara world: artistic interpretation

Vantara built from open map data and a designed layout, compiled with plain
Python and built into 3D in the browser. No heavy rendering on the machine that
builds it.

> **Artistic interpretation.** Only Vantara's outline, the surrounding roads,
> water and railway come from map data. Everything inside the site (enclosures,
> buildings, pools, planting) is designed from public descriptions, not
> surveyed. Not affiliated with or endorsed by Vantara.
>
> Map data © OpenStreetMap contributors, available under the
> [Open Database License](https://www.openstreetmap.org/copyright).
> Textures and plant models: [Poly Haven](https://polyhaven.com), CC0.

## How it works

```
data/vantara_area.osm --osm_to_json.py--> data/site.json ----+
scripts/design_layout.py ---------------> data/layout.json --+--compile_world.py--> publish/world/world.json
                                                             |                     publish/<zone>/<zone>.json
                                                             |                     web/public/map/overview.svg
assets/polyhaven (fetch_polyhaven.py) --prepare_textures.py--> publish/world/textures/
                                      --tools/build_plants.mjs--> publish/world/plants.glb
```

`world.json` (~0.3 MB) describes the whole site as simple primitives: ground
layers with holes for water, roads, walls, buildings, roofs, windows, fences,
pond and lake basins, the hydrotherapy pool, every plant and animal, the
labelled places. The explorer (`web/src/components/explorer/world/`) turns it
into meshes when the page loads. The web world totals about 6.6 MB.

## Rebuild

```bash
uv run --project pipeline python world/scripts/osm_to_json.py      # only if the OSM extract changes
uv run --project pipeline python world/scripts/design_layout.py    # only if the layout changes
uv run --project pipeline python world/scripts/fetch_polyhaven.py  # once: CC0 textures and models (~100 MB, not in git)
uv run --project pipeline python world/scripts/compile_world.py    # world.json, zone files, overview map (~4 s)
uv run --project pipeline python world/scripts/prepare_textures.py # web textures
cd world/tools && pnpm install && node build_plants.mjs && cd ../.. # plants.glb (~5 s)
uv run --project pipeline pytest world/tests -q
```

The dev server serves `publish/` under `/dev-assets`; open
`http://localhost:3000/explore?zone=elephant-care-centre`.

## Files

| | |
| --- | --- |
| `data/vantara_area.osm` | Raw OpenStreetMap extract, 6 x 6 km around Vantara (ODbL) |
| `data/site.json` | Outline, roads, water, rail in metres around Vantara's centre (x east, y north) |
| `data/layout.json` | Designed zone layout (artistic interpretation) |
| `scripts/osm_to_json.py` | `vantara_area.osm` -> `site.json` |
| `scripts/design_layout.py` | Writes `layout.json`; checks everything sits inside the outline |
| `scripts/fetch_polyhaven.py` | Downloads the CC0 Poly Haven textures and plant models into `assets/` |
| `scripts/compile_world.py` | The design rules: ground, buildings, water, planting, animals, places -> `world.json`, zone files, map |
| `scripts/worldgeo.py` | 2D geometry helpers (offsets, clipping, seeded scatter) |
| `scripts/overview_map.py` | The overview map as an SVG, from the same data |
| `scripts/prepare_textures.py` | Web-size textures (OpenCV) |
| `tools/build_plants.mjs` | Plant levels of detail with gltf-transform + meshoptimizer (leaf thinning for foliage) |
| `tests/` | Compiler checks: deterministic, plants inside the site and off buildings, water cut out, basins slope down, assets exist |
| `publish/`, `assets/` | Generated / downloaded (not in git) |

## What's in it

- Site: the mapped outline (1,104 x 324 m) on a 14 km ground, roads at real
  widths, the Kanalus railway, lakes and streams, a 2.2 m perimeter wall; sun
  for Jamnagar at 10:00 IST on 15 March (39.5 deg up, from the east-south-east).
- Zones in the blocks formed by the real internal roads: Elephant Care
  Centre (six shelters, sand yards and paddock, bathing pond, mud wallow,
  hydrotherapy pool with an elephant ramp, kitchen), Wildlife Hospital, Big
  Cat Rescue (ten enclosures and a large one), Herbivore Reserve (three
  paddocks), entrance plaza, and a woodland where nothing is published.
- Water as basins: sloped wet banks, a bed, a wet-mud shore band, water that is
  clear and light at the edges and dark in the middle.
- About 2,600 plants: a closed woodland canopy with understory, avenues along
  the internal roads, shade in every yard, planted shores, rocks.
- 9 CC0 placeholder animals (4 elephants, 3 tigers, 2 rhinos) walking short
  loops in their yards.
