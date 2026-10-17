// Development only: lists zones published locally, by `publish-splat`
// (pipeline/work/<zone>/publish/<zone>.json) or by the Blender world export
// (world/publish/<zone>/<zone>.json). Returns 404 in production.
import { readdir, stat } from "node:fs/promises";
import path from "node:path";

const ROOTS = [
  { dir: path.resolve(process.cwd(), "../pipeline/work"), sub: "publish" },
  { dir: path.resolve(process.cwd(), "../world/publish"), sub: "" },
];

export async function GET() {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  const zones = new Set<string>();
  for (const root of ROOTS) {
    let names: string[] = [];
    try {
      names = await readdir(root.dir);
    } catch {
      continue;
    }
    for (const name of names) {
      if (name === "world" && !root.sub) continue; // world/publish/world holds the shared world, not a zone
      try {
        await stat(path.join(root.dir, name, root.sub, `${name}.json`));
        zones.add(name);
      } catch {
        // not published yet
      }
    }
  }
  return Response.json({ zones: [...zones] }, { headers: { "Cache-Control": "no-store" } });
}
