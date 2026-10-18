// Animal models for the web.
//
//   cd world/tools && node build_animals.mjs            # sources: web/public/models/source/sketchfab/<name>.glb
//   node build_animals.mjs --src <dir> --out <dir>      # other folders (e.g. a dry run)
//
// For each animal GLB: textures to at most 1024 px WebP (sharp), unused data
// removed, meshes meshopt-compressed (three.js decodes with MeshoptDecoder),
// written to web/public/models/<name>.glb. Rigging and animations are kept as
// they are. Sizing (real height, feet on the ground, facing +Z) is done by the
// explorer when the model loads (heightM / yawDeg in web/src/content/animals.json),
// which is safe for rigged meshes. Prints each model's clips and size.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, meshopt, prune, textureCompress } from "@gltf-transform/functions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";
import sharp from "sharp";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..");
const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const SRC = arg("--src", join(REPO, "web", "public", "models", "source", "sketchfab"));
const OUT = arg("--out", join(REPO, "web", "public", "models"));
const ANIMALS = ["elephant", "tiger", "rhino", "lion"];

await MeshoptEncoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder });

mkdirSync(OUT, { recursive: true });
const report = [];
for (const name of ANIMALS) {
  const src = join(SRC, `${name}.glb`);
  if (!existsSync(src)) {
    report.push({ name, status: "missing", src });
    continue;
  }
  const before = readFileSync(src).length;
  const doc = await io.read(src);
  const root = doc.getRoot();
  const faces = root.listMeshes().reduce(
    (n, m) => n + m.listPrimitives().reduce((k, p) => k + (p.getIndices()?.getCount() ?? p.getAttribute("POSITION").getCount()) / 3, 0),
    0,
  );
  await doc.transform(
    dedup(),
    prune(),
    textureCompress({ encoder: sharp, targetFormat: "webp", resize: [1024, 1024], quality: 82 }),
    meshopt({ encoder: MeshoptEncoder, level: "medium" }),
  );
  const out = join(OUT, `${name}.glb`);
  writeFileSync(out, await io.writeBinary(doc));
  const clips = root.listAnimations().map((a) => {
    const seconds = a.listChannels().reduce((t, c) => {
      const input = c.getSampler()?.getInput();
      return Math.max(t, input ? input.getMax([0])[0] : 0);
    }, 0);
    return { name: a.getName() || "clip", seconds: +seconds.toFixed(2) };
  });
  report.push({
    name,
    status: "ok",
    faces: Math.round(faces),
    skinned: root.listSkins().length > 0,
    textures: root.listTextures().length,
    clips: clips.map((c) => `${c.name} (${c.seconds}s)`).join(", ") || "none",
    MB: `${(before / 1e6).toFixed(1)} -> ${(readFileSync(out).length / 1e6).toFixed(1)}`,
  });
}
console.log(JSON.stringify(report, null, 1));
