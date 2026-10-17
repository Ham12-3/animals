// Development only: serves pipeline outputs (pipeline/work/<zone>/publish/*)
// to the local app so zones can be checked before they are uploaded to the
// CDN. Returns 404 in production builds, so nothing under pipeline/work can
// ship with a deployment.
import { readFile } from "node:fs/promises";
import path from "node:path";

const WORK_DIR = path.resolve(process.cwd(), "../pipeline/work");
const SAFE = /^[a-z0-9][a-z0-9-]*$/;
const TYPES: Record<string, string> = {
  ".spz": "application/octet-stream",
  ".json": "application/json",
  ".webp": "image/webp",
  ".glb": "model/gltf-binary",
};

export async function GET(_req: Request, ctx: RouteContext<"/dev-assets/[zone]/[file]">) {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  const { zone, file } = await ctx.params;
  const ext = path.extname(file);
  if (!SAFE.test(zone) || !SAFE.test(path.basename(file, ext).replace(/\./g, "-")) || !(ext in TYPES)) {
    return new Response("Bad request", { status: 400 });
  }
  try {
    const body = await readFile(path.join(WORK_DIR, zone, "publish", file));
    return new Response(body, { headers: { "Content-Type": TYPES[ext], "Cache-Control": "no-store" } });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
