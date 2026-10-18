// Development only: serves pipeline outputs (pipeline/work/<zone>/publish/*)
// and the world build (world/publish/<zone>/**, e.g. world/textures/*.jpg)
// to the local app so zones can be checked before they are uploaded to the
// CDN. Returns 404 in production builds, so nothing under pipeline/work or
// world/publish can ship with a deployment.
import { readFile } from "node:fs/promises";
import path from "node:path";

const ROOTS = [
  (zone: string) => path.resolve(process.cwd(), "../pipeline/work", zone, "publish"),
  (zone: string) => path.resolve(process.cwd(), "../world/publish", zone),
];
const SAFE_ZONE = /^[a-z0-9][a-z0-9-]*$/;
const SAFE_DIR = /^[a-z0-9][a-z0-9_-]*$/;
const SAFE_FILE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const TYPES: Record<string, string> = {
  ".spz": "application/octet-stream",
  ".json": "application/json",
  ".webp": "image/webp",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".bin": "application/octet-stream",
  ".jpg": "image/jpeg",
  ".png": "image/png",
};

export async function GET(_req: Request, ctx: RouteContext<"/dev-assets/[zone]/[...path]">) {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  const { zone, path: parts } = await ctx.params;
  const file = parts[parts.length - 1];
  const ext = path.extname(file);
  const dirsOk = parts.slice(0, -1).every((d) => SAFE_DIR.test(d));
  if (!SAFE_ZONE.test(zone) || !dirsOk || !SAFE_FILE.test(path.basename(file, ext).replace(/\./g, "-")) || !(ext in TYPES)) {
    return new Response("Bad request", { status: 400 });
  }
  for (const root of ROOTS) {
    try {
      const body = await readFile(path.join(root(zone), ...parts));
      return new Response(body, {
        headers: {
          "Content-Type": TYPES[ext],
          "Content-Length": String(body.length), // lets the loading screen show real progress
          "Cache-Control": "no-store",
        },
      });
    } catch {
      // try the next root
    }
  }
  return new Response("Not found", { status: 404 });
}
