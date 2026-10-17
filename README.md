# Vantara 3D

A walkable web explorer of Vantara (animal rescue and reserve, Jamnagar, India),
built as a 3D mesh world in Blender and shown in the browser. Runs on an
integrated-graphics laptop (about 1.6M triangles at 60 fps on an Iris Xe).

> **Unofficial fan-made model.** An artistic interpretation, not surveyed. Not
> affiliated with or endorsed by Vantara.

Gaussian splatting was dropped: the splat code and dependency are removed from
the web app. `pipeline/` (video to splat) is kept for reference only and is not
used by the explorer.

## Layout

```
zones.json          every zone: id, name, overview-map position
zones.schema.json   schema for zones.json (editors validate against it)
world/              Blender world: scripts that build, dress and export it
  publish/          web export (not committed)
web/                Next.js + TypeScript + React Three Fiber explorer
pipeline/           retired video -> splat tooling (unused)
```

Large files (`.blend`, textures, exports) never go in git; they ship from a
CDN / Vercel Blob.

## Status

| Step | What | State |
| --- | --- | --- |
| 1 | Project setup, web explorer (walk, orbit, flyover) | done |
| 2 | Blender world: site from map data, 6 zones, dressing, plants | done |
| 3 | Web export (Draco meshes, instanced plants, collision) | done |
| 4 | Place labels, click to fly, overview map | done |
| 5 | Animated animals | done with CC0 placeholders (realistic models to swap in) |
| 6 | Polish and deploy | |

## Quick start

```bash
# web
cd web && pnpm install && pnpm dev   # http://localhost:3000, explorer at /explore
```
