// Copies the repo-level zones.json (shared with /pipeline) into the web app.
// Turbopack does not resolve files outside the project root, so the copy is
// regenerated before every dev/build run and is gitignored.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../zones.json");
const dest = resolve(here, "../src/data/zones.json");

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`synced ${src} -> ${dest}`);
