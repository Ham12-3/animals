// Upload the world and animal assets to Vercel Blob (public, fixed paths, long cache).
//
//   pnpm assets:upload -- --dry-run              # list what would go up (no token needed)
//   pnpm assets:upload -- --version v1           # upload under v1/ (needs BLOB_READ_WRITE_TOKEN)
//   pnpm assets:upload -- --check-cors <url>     # only check a public blob URL's CORS headers
//
// Only an allow-list is ever uploaded, derived from what the explorer loads:
//   world/publish/world/world.json, plants.glb, and the textures world.json names
//   world/publish/<zone>/<zone>.json for every zone in zones.json
//   web/public/models/<file> for every animal in src/content/animals.json
// Anything else (notably pipeline/work, which holds private test footage) can't be
// uploaded: paths must resolve inside world/publish or web/public/models.
//
// The token is read from the environment (`vercel env pull` writes it to
// .env.local); it is never printed. Blob paths are fixed (no random suffix) and
// versioned: a rebuild goes to v2/, so long caching never mixes old and new files.
import { existsSync, lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, "..");
const REPO = path.resolve(WEB, "..");
const PUBLISH = path.join(REPO, "world", "publish");
const MODELS = path.join(WEB, "public", "models");
const ALLOWED_ROOTS = [PUBLISH, MODELS];
const ONE_YEAR = 31536000;
const TYPES = { ".json": "application/json", ".glb": "model/gltf-binary", ".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp" };

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

/** Every file the explorer loads, as [local path, blob pathname under the version prefix]. */
function allowList() {
  const files = [];
  const world = JSON.parse(readFileSync(path.join(PUBLISH, "world", "world.json"), "utf8"));
  files.push([path.join(PUBLISH, "world", "world.json"), "world/world.json"]);
  files.push([path.join(PUBLISH, "world", world.assets.plants), `world/${world.assets.plants}`]);
  const textures = new Set();
  for (const m of Object.values(world.materials)) {
    if (m.texture) textures.add(`${m.texture}_diff.jpg`).add(`${m.texture}_nor.jpg`);
    if (m.normal) textures.add(`${m.normal}_nor.jpg`);
  }
  for (const t of [...textures].sort()) files.push([path.join(PUBLISH, "world", world.assets.textures, t), `world/${world.assets.textures}${t}`]);
  const zones = JSON.parse(readFileSync(path.join(REPO, "zones.json"), "utf8")).zones;
  for (const z of zones) files.push([path.join(PUBLISH, z.id, `${z.id}.json`), `${z.id}/${z.id}.json`]);
  const animals = JSON.parse(readFileSync(path.join(WEB, "src", "content", "animals.json"), "utf8")).animals;
  for (const a of Object.values(animals)) files.push([path.join(MODELS, a.file), `models/${a.file}`]);
  return files;
}

/** Refuse anything outside the allowed folders, symlinks, and missing files. */
function check([local, pathname]) {
  const resolved = path.resolve(local);
  if (!ALLOWED_ROOTS.some((root) => resolved.startsWith(root + path.sep))) throw new Error(`not in an allowed folder: ${resolved}`);
  if (/[\\/](pipeline|_private|_staging)[\\/]/.test(resolved)) throw new Error(`refusing ${resolved}`);
  if (!existsSync(resolved)) throw new Error(`missing (build it first, see world/README.md): ${resolved}`);
  if (lstatSync(resolved).isSymbolicLink()) throw new Error(`refusing a symlink: ${resolved}`);
  if (!TYPES[path.extname(resolved)]) throw new Error(`unexpected file type: ${resolved}`);
  if (pathname.includes("..")) throw new Error(`bad blob path: ${pathname}`);
  return { local: resolved, pathname, bytes: lstatSync(resolved).size, type: TYPES[path.extname(resolved)] };
}

/** Do textures and models load cross-origin? three.js needs Access-Control-Allow-Origin for them. */
async function checkCors(url) {
  const res = await fetch(url, { method: "GET", headers: { Origin: "https://vantara-3d.vercel.app" } });
  const allow = res.headers.get("access-control-allow-origin");
  const ok = res.ok && (allow === "*" || allow === "https://vantara-3d.vercel.app");
  console.log(`CORS check ${url}: HTTP ${res.status}, access-control-allow-origin: ${allow ?? "(none)"} -> ${ok ? "OK" : "NOT OK"}`);
  return ok;
}

async function main() {
  if (flag("--check-cors")) {
    const ok = await checkCors(option("--check-cors"));
    process.exit(ok ? 0 : 1);
  }
  const version = option("--version", "v1");
  if (!/^v[0-9]+$/.test(version)) throw new Error(`--version must look like v1, v2, ... (got ${version})`);
  const files = allowList().map(check);
  const total = files.reduce((n, f) => n + f.bytes, 0);
  for (const f of files) console.log(`${(f.bytes / 1e6).toFixed(2).padStart(6)} MB  ${version}/${f.pathname}`);
  console.log(`${files.length} files, ${(total / 1e6).toFixed(1)} MB`);
  if (flag("--dry-run")) return;

  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    throw new Error("BLOB_READ_WRITE_TOKEN is not set: run `vercel env pull` in web/ (or export it) and try again");
  }
  const { put } = await import("@vercel/blob");
  let origin = null;
  for (const f of files) {
    const blob = await put(`${version}/${f.pathname}`, readFileSync(f.local), {
      access: "public",
      addRandomSuffix: false,
      allowOverwrite: flag("--overwrite"),
      contentType: f.type,
      cacheControlMaxAge: ONE_YEAR,
    });
    origin ??= new URL(blob.url).origin;
    console.log(`uploaded ${blob.pathname}`);
  }
  console.log("\nSet these in Vercel (Preview and Production):");
  const texture = files.find((f) => f.pathname.endsWith(".jpg"));
  const corsOk = await checkCors(`${origin}/${version}/${texture.pathname}`);
  if (corsOk) {
    console.log(`  NEXT_PUBLIC_ASSET_BASE=${origin}/${version}`);
    console.log(`  NEXT_PUBLIC_MODEL_BASE=${origin}/${version}/models`);
  } else {
    console.log("  Blob doesn't allow cross-origin loads here: serve it through this site instead (next.config.ts rewrite):");
    console.log(`  ASSET_ORIGIN=${origin}`);
    console.log(`  NEXT_PUBLIC_ASSET_BASE=/assets/${version}`);
    console.log(`  NEXT_PUBLIC_MODEL_BASE=/assets/${version}/models`);
  }
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
