// Copies the repo-level zones.json (shared with /pipeline) into the web app,
// and three.js's Draco decoder into public/draco (the world meshes are
// Draco-compressed). Turbopack does not resolve files outside the project
// root, so the copies are regenerated before every dev/build run and are
// gitignored.
import { copyFileSync, cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../zones.json");
const dest = resolve(here, "../src/data/zones.json");

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`synced ${src} -> ${dest}`);

const draco = resolve(here, "../node_modules/three/examples/jsm/libs/draco/gltf");
if (existsSync(draco)) {
  cpSync(draco, resolve(here, "../public/draco"), { recursive: true });
  console.log("synced draco decoder -> public/draco");
}
