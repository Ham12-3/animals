# Vantara 3D – web

Next.js (App Router) + TypeScript + React Three Fiber, building the world from `../world` (world.json, textures, plants.glb) in the browser.

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

The 3D assets (~7 MB: `world/world.json`, `world/plants.glb`,
`world/textures/*`, `<zone>/<zone>.json`, `models/*.glb`) are not part of the
app. In production they come from a public Vercel Blob store:
`NEXT_PUBLIC_ASSET_BASE` points at the folder holding `world/` and the zone
folders, `NEXT_PUBLIC_MODEL_BASE` at the one holding the animal GLBs. A zone
appears on the map once its `status` in zones.json is `"live"`.

In development, without those variables, assets are served from
`../world/publish/` (and `../pipeline/work/<zone>/publish/`) by the dev-only
`/dev-assets` route, and models from `public/models`. The route returns 404 in
production builds.

## Deploy (Vercel + Vercel Blob)

1. Build the world (`../world/README.md`): `world/publish/` must be current.
2. Vercel project: import the repo, Root Directory `web` (the build copies
   `../zones.json`, so keep "include files outside the root directory" on).
3. Create a Blob store connected to the project, then in `web/`:

   ```bash
   vercel env pull                                # writes BLOB_READ_WRITE_TOKEN to .env.local
   pnpm assets:upload -- --dry-run                # what would go up
   node --env-file=.env.local scripts/upload-assets.mjs --version v1
   ```

   The script uploads only what the explorer loads (an allow-list built from
   world.json, zones.json and animals.json; nothing outside `world/publish`
   and `public/models`), at fixed paths under `v1/`, cached for a year. Use
   `v2/` next time instead of overwriting.
4. Set the variables it prints in Vercel (Preview and Production). It checks
   whether Blob allows cross-origin loads (three.js needs it for textures):
   - if yes: `NEXT_PUBLIC_ASSET_BASE=https://<store>.public.blob.vercel-storage.com/v1`,
     `NEXT_PUBLIC_MODEL_BASE=…/v1/models`;
   - if not: `ASSET_ORIGIN=https://<store>.public.blob.vercel-storage.com`,
     `NEXT_PUBLIC_ASSET_BASE=/assets/v1`, `NEXT_PUBLIC_MODEL_BASE=/assets/v1/models`
     (next.config.ts then serves the Blob files from this site's own origin).
5. Deploy a preview (a pull request), check the explorer, then promote.

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
(CDN) in production; `src/content/animals.json` lists them (sizes, clips,
credits) and is edited by hand when a model is added or swapped. Animals are lit by the world's sun and sky and cast real shadows.
