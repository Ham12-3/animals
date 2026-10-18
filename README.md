# Vantara 3D

A walkable web explorer of Vantara (animal rescue and reserve, Jamnagar, India),
compiled from open map data and a designed layout, and built into 3D in the
browser. No Blender. Runs on an integrated-graphics laptop (60 fps on an
Iris Xe).

> **Unofficial fan-made model.** An artistic interpretation, not surveyed. Not
> affiliated with or endorsed by Vantara.

Gaussian splatting was dropped: the splat code and dependency are removed from
the web app. `pipeline/` (video to splat) is kept for reference only and is not
used by the explorer.

## Layout

```
zones.json          every zone: id, name, overview-map position
zones.schema.json   schema for zones.json (editors validate against it)
world/              the world: map data, layout, compiler, asset tools
  publish/          world.json, textures, plants.glb (generated, not committed)
web/                Next.js + TypeScript + React Three Fiber explorer
pipeline/           retired video -> splat tooling (unused)
```

Large files (textures, models, generated world files) never go in git; they
ship from a CDN / Vercel Blob.

## Status

| Step | What | State |
| --- | --- | --- |
| 1 | Project setup, web explorer (walk, orbit, flyover) | done |
| 2 | World from map data: 6 zones, water basins, ~2,600 plants (first in Blender, now compiled without it) | done |
| 3 | Built in the browser (batched plants with levels of detail, billboards, collision) | done |
| 4 | Place labels, click to fly, overview map | done |
| 5 | Animated animals | done with CC0 placeholders (realistic models to swap in) |
| 6 | Polish and deploy | |

## Quick start

```bash
# world (see world/README.md)
uv run --project pipeline python world/scripts/compile_world.py
uv run --project pipeline python world/scripts/prepare_textures.py
cd world/tools && pnpm install && node build_plants.mjs && cd ../..
# web
cd web && pnpm install && pnpm dev   # http://localhost:3000, explorer at /explore
```
