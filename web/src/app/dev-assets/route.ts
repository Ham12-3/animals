// Development only: lists zones published locally by `publish-splat`
// (pipeline/work/<zone>/publish/<zone>.json). Returns 404 in production.
import { readdir, stat } from "node:fs/promises";
import path from "node:path";

const WORK_DIR = path.resolve(process.cwd(), "../pipeline/work");

export async function GET() {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  let names: string[] = [];
  try {
    names = await readdir(WORK_DIR);
  } catch {
    return Response.json({ zones: [] });
  }
  const zones: string[] = [];
  for (const name of names) {
    try {
      await stat(path.join(WORK_DIR, name, "publish", `${name}.json`));
      zones.push(name);
    } catch {
      // not published yet
    }
  }
  return Response.json({ zones }, { headers: { "Cache-Control": "no-store" } });
}
