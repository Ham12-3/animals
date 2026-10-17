# Vantara 3D – web

Next.js (App Router) + TypeScript + React Three Fiber + [Spark](https://sparkjs.dev) for Gaussian splats.

```bash
pnpm install
pnpm dev        # http://localhost:3000
pnpm typecheck
pnpm build
```

`src/data/zones.json` is generated from the repo-level `zones.json` by
`scripts/sync-data.mjs` (runs before `dev` and `build`); edit the root file.

`/dev/spark` renders Spark's public sample splat to check the renderer stack.
