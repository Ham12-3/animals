# Vantara 3D

A walkable web explorer of Vantara (animal rescue and reserve, Jamnagar, India),
reconstructed from video with Gaussian splatting.

> **Unofficial fan reconstruction.** Not affiliated with or endorsed by Vantara.

## Layout

```
zones.json          every zone: id, name, source videos, overview-map position
zones.schema.json   schema for zones.json (editors validate against it)
pipeline/           Python: video -> frames -> COLMAP -> splat -> cleanup
  input/<zone>/     drop each zone's videos here (not committed)
  work/<zone>/      pipeline outputs (not committed)
web/                Next.js + TypeScript + React Three Fiber + Spark
```

Large files (videos, `.ply`, `.spz`) never go in git; they ship from a CDN /
Vercel Blob.

## Status

| Phase | What | State |
| --- | --- | --- |
| 1 | Project setup | done |
| 2 | Frame extraction | done |
| 3 | Camera poses (COLMAP) | done (tested on private sample) |
| 4 | Splat training (Brush, Colab fallback) | tooling done, waiting for footage |
| 5 | Cleanup, alignment, SPZ + mobile LOD | done (tested on private sample) |
| 6 | Web explorer | done (tested on private sample) |
| 7 | Animated animals | |
| 8 | Polish and deploy | |

## Quick start

```bash
# pipeline (needs FFmpeg on PATH, and uv)
cd pipeline && uv sync
uv run extract-frames elephant-care-centre

# web
cd web && pnpm install && pnpm dev   # http://localhost:3000, explorer at /explore
```

## Shooting footage that reconstructs well

Splats are only as good as the video. Per zone:

- **3-6 minutes** of continuous footage, ideally walking a loop that ends where it started.
- **Walk slowly and steadily**, camera at chest height, small sideways steps around
  key objects. Don't spin on the spot and don't zoom.
- **Bright, even daylight**; avoid strong backlight. Lock exposure/focus if you can.
- **4K or 1080p, 30/60 fps**, stabilisation on. HDR iPhone footage is fine (tone-mapped automatically).
- **No captions, titles, or edits**: original clips, not downloaded edits. A fixed
  watermark is masked automatically but costs a little quality.
- Animals and people moving through the shot become ghosts in the splat. Some is
  fine; static scenery is what reconstructs.
