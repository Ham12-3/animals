# Vantara 3D – web

Next.js (App Router) + TypeScript + React Three Fiber, rendering the Blender-built mesh world (`../world`).

```bash
pnpm install
pnpm dev        # http://localhost:3000
pnpm typecheck
pnpm build
```

`src/data/zones.json` is generated from the repo-level `zones.json` by
`scripts/sync-data.mjs` (runs before `dev` and `build`); edit the root file.

## Explorer (`/explore`)

`/explore?zone=<id>` opens a zone; without `zone` it opens the overview map.

| | |
| --- | --- |
| **Walk** | Click the scene to capture the mouse, move it to look, WASD/arrows to move, Shift to run, Esc to release. Phones: left stick to move, drag elsewhere to look. |
| **Orbit** | Drag to rotate, scroll/pinch to zoom. |
| **Flyover** | Flies along the path the footage was filmed on; any touch stops it. |
| Keys | `V` walk/orbit · `F` flyover · `M` map · `Esc` close panels |

How it fits together (`src/components/explorer/`):

- **World assets** come from `world/scripts/export_web.py`: draco-compressed
  meshes, textures, instanced plants and a collision mesh, shared by all zones
  and kept loaded while you move between them.
- **Quality**: phones, tablets and low-memory machines start in "Lite" (lower
  render resolution); the HD/Lite button switches. Resolution also adapts
  to hold frame rate.
- **Collision** (`collision.ts`, `WalkControls.tsx`): a capsule is pushed out of
  the zone's collision mesh (BVH via three-mesh-bvh). Floors are the mesh where
  it has one and the fitted ground plane elsewhere; the walker won't step off
  drops deeper than 1.2 m and is kept inside the zone bounds.
- **Hotspots**: `src/content/hotspots.json`, per zone, positions in the zone's
  published frame. They hide behind walls and beyond 30 m.

### Asset hosting

Set `NEXT_PUBLIC_ASSET_BASE` to the CDN / Vercel Blob folder that holds
`<zone>/<files>` (Phase 8). A zone appears on the map once its `status` in
zones.json is `"live"`.

In development, without that variable, assets are served from
`../pipeline/work/<zone>/publish/` by the dev-only `/dev-assets` route (it
returns 404 in production builds). Zones published only on your machine show up
on the map under "Published on this machine". They can carry their own
`hotspots.json` beside the published files.

### Debug (`?debug`)

FPS meter, `window.__vantara` (player, input, collision), `N` noclip, and `H` to
copy the point under the crosshair: aim at a spot and paste the position into
`hotspots.json`.

## Animals

`src/content/animal-placements.json` places animals per zone: waypoints `[x, z]`
on the ground; each animal idles at a waypoint (its idle clip, sometimes an
extra such as eating), turns, and walks to the next, feet snapped to the zone's
floor. Locally published zones can carry their own `animals.json` beside their
files.

Models come from `web/public/models` in development, `NEXT_PUBLIC_MODEL_BASE`
(CDN) in production; `src/content/animals.json` is written by the Blender
script. Animals are lit by the world's sun and sky and cast real shadows.
