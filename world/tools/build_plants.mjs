// Plant models for the web world, without Blender.
//
//   cd world/tools && pnpm install && node build_plants.mjs
//   (run world/scripts/prepare_textures.py first: it stages the 512 px textures)
//
// For every plant variant in the CC0 Poly Haven downloads (world/assets/polyhaven/models)
// writes nodes "<variant>|lod0" (near) and "<variant>|lod1" (far) into one file,
// world/publish/world/plants.glb: moved so the base centre sits at the origin,
// simplified with meshoptimizer to the face budget of the plant's role, textures
// swapped for the staged 512 px copies, meshopt-compressed (three.js decodes it
// with MeshoptDecoder, no extra files). Distant trees become billboards in the
// browser, rendered from the near model when the page loads.

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Document, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { compactPrimitive, dedup, mergeDocuments, meshopt, prune, transformMesh, unpartition } from "@gltf-transform/functions";
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from "meshoptimizer";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORLD = join(HERE, "..");
const MODELS = join(WORLD, "assets", "polyhaven", "models");
const STAGING = join(WORLD, "publish", "_staging", "plants");
const OUT = join(WORLD, "publish", "world", "plants.glb");

// Same roles as compile_world.PLANTS; faces per level of detail (near, far).
const PLANTS = {
  island_tree_02: "tree",
  searsia_lucida: "bush",
  shrub_02: "shrub",
  wild_rooibos_bush: "shrub",
  boulder_01: "rock",
  namaqualand_boulder_02: "rock",
};
const BUDGET = { tree: [60000, 10000], bush: [6000, 1500], shrub: [3000, 1000], rock: [3000, 500] };
// Share of each budget for leaf cards (alpha-blended primitives); the rest goes to bark.
const FOLIAGE_SHARE = { tree: 0.75, bush: 0.6, shrub: 0.6, rock: 0 };
// Kept leaves grow by up to this much (about their own centre) so a thinned canopy stays full.
const MAX_LEAF_SCALE = [2.2, 3.0];

/** Small seeded random generator (mulberry32): the same leaves are kept on every run. */
function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Foliage: keep a random share of whole leaves (connected pieces of the leaf mesh) and
 * enlarge each kept leaf about its centre, so coverage drops much less than face count.
 */
function thinFoliage(prim, target, maxScale, rng) {
  const pos = prim.getAttribute("POSITION");
  const positions = Float32Array.from(pos.getArray());
  const indices = Uint32Array.from(prim.getIndices().getArray());
  const tris = indices.length / 3;
  if (tris <= target) return;
  const parent = new Int32Array(pos.getCount()).map((_, i) => i);
  const find = (v) => {
    while (parent[v] !== v) v = parent[v] = parent[parent[v]];
    return v;
  };
  for (let t = 0; t < indices.length; t += 3) {
    const a = find(indices[t]);
    parent[find(indices[t + 1])] = a;
    parent[find(indices[t + 2])] = a;
  }
  const keepShare = target / tris;
  const keep = new Map(); // leaf root -> kept?
  const out = [];
  for (let t = 0; t < indices.length; t += 3) {
    const r = find(indices[t]);
    if (!keep.has(r)) keep.set(r, rng() < keepShare);
    if (keep.get(r)) out.push(indices[t], indices[t + 1], indices[t + 2]);
  }
  // Grow each kept leaf about its centre.
  const scale = Math.min(maxScale, 1 / Math.sqrt(keepShare));
  const sum = new Map();
  const used = new Set(out);
  for (const v of used) {
    const r = find(v);
    const c = sum.get(r) ?? [0, 0, 0, 0];
    c[0] += positions[3 * v]; c[1] += positions[3 * v + 1]; c[2] += positions[3 * v + 2]; c[3]++;
    sum.set(r, c);
  }
  for (const v of used) {
    const c = sum.get(find(v));
    for (let k = 0; k < 3; k++) positions[3 * v + k] = c[k] / c[3] + (positions[3 * v + k] - c[k] / c[3]) * scale;
  }
  pos.setArray(positions);
  prim.getIndices().setArray(Uint32Array.from(out));
  compactPrimitive(prim);
}

/**
 * Bark and branches: shape-preserving simplification only (never "sloppy", which breaks trunks).
 * Rocks are single solid scans: they may use a looser error, then sloppy, to reach the budget.
 */
function simplifyShape(prim, target, lod, role) {
  const positions = Float32Array.from(prim.getAttribute("POSITION").getArray());
  const indices = Uint32Array.from(prim.getIndices().getArray());
  const want = Math.max(3, Math.floor(target) * 3);
  if (indices.length <= want) return;
  let [out] = MeshoptSimplifier.simplify(indices, positions, 3, want, lod === 0 ? 0.02 : 0.05, []);
  // Far level: twigs too small to see may go entirely.
  if (lod > 0 && out.length > want * 1.3) [out] = MeshoptSimplifier.simplify(indices, positions, 3, want, 0.08, ["Prune"]);
  if (role === "rock" && out.length > want * 1.3) [out] = MeshoptSimplifier.simplify(indices, positions, 3, want, 0.3, []);
  if (role === "rock" && out.length > want * 1.3) [out] = MeshoptSimplifier.simplifySloppy(indices, positions, 3, null, want, 0.3);
  prim.getIndices().setArray(out);
  compactPrimitive(prim);
}

await MeshoptSimplifier.ready;
await MeshoptEncoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder });

const faces = (mesh) =>
  mesh.listPrimitives().reduce((n, p) => n + (p.getIndices()?.getCount() ?? p.getAttribute("POSITION").getCount()) / 3, 0);


/** One level of one variant, as its own small document. */
async function level(gltfPath, asset, variant, lod, budget, role) {
  const doc = await io.read(gltfPath);
  const root = doc.getRoot();
  const src = root.listNodes().find((n) => n.getName() === variant);
  const mesh = src.getMesh();
  const before = faces(mesh);
  // Bake the node's placement, then put the base centre at the origin (glTF is +Y up).
  transformMesh(mesh, src.getWorldMatrix());
  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const p of mesh.listPrimitives()) {
    const a = p.getAttribute("POSITION").getArray();
    for (let i = 0; i < a.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        min[k] = Math.min(min[k], a[i + k]);
        max[k] = Math.max(max[k], a[i + k]);
      }
    }
  }
  const [cx, cz] = [(min[0] + max[0]) / 2, (min[2] + max[2]) / 2];
  transformMesh(mesh, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -cx, -min[1], -cz, 1]);
  // Split the budget: leaf cards (alpha) get FOLIAGE_SHARE, bark the rest, each in proportion to size.
  const isLeaf = (p) => (p.getMaterial()?.getAlphaMode() ?? "OPAQUE") !== "OPAQUE";
  const prims = mesh.listPrimitives();
  const count = (p) => faces({ listPrimitives: () => [p] });
  const leafFaces = prims.filter(isLeaf).reduce((n, p) => n + count(p), 0);
  const barkFaces = prims.filter((p) => !isLeaf(p)).reduce((n, p) => n + count(p), 0);
  const leafBudget = leafFaces ? budget * (barkFaces ? FOLIAGE_SHARE[role] : 1) : 0;
  const barkBudget = budget - leafBudget;
  const rng = seeded(lod * 7919 + variant.length * 104729);
  for (const p of prims) {
    if (isLeaf(p)) thinFoliage(p, (count(p) / leafFaces) * leafBudget, MAX_LEAF_SCALE[lod], rng);
    else simplifyShape(p, (count(p) / barkFaces) * barkBudget, lod, role);
  }
  const node = doc.createNode(`${variant}|lod${lod}`).setMesh(mesh);
  for (const s of root.listScenes()) for (const c of s.listChildren()) s.removeChild(c);
  root.listScenes()[0].addChild(node);
  // 512 px textures prepared by prepare_textures.py.
  for (const t of root.listTextures()) {
    const staged = join(STAGING, asset, basename(t.getURI()));
    if (existsSync(staged)) t.setImage(readFileSync(staged));
  }
  await doc.transform(prune());
  return { doc, before, after: faces(mesh), height: max[1] - min[1] };
}

const out = new Document();
out.createScene("plants");
const report = [];
for (const [asset, role] of Object.entries(PLANTS)) {
  const gltfPath = join(MODELS, asset, `${asset}_1k.gltf`);
  if (!existsSync(gltfPath)) throw new Error(`missing ${gltfPath} (run world/scripts/fetch_polyhaven.py)`);
  const variants = JSON.parse(readFileSync(gltfPath, "utf8")).nodes.filter((n) => "mesh" in n).map((n) => n.name);
  for (const variant of variants) {
    const row = { variant, role };
    for (const [lod, budget] of BUDGET[role].entries()) {
      const { doc, before, after, height } = await level(gltfPath, asset, variant, lod, budget, role);
      mergeDocuments(out, doc);
      row.source = Math.round(before);
      row[`lod${lod}`] = Math.round(after);
      row.height = +height.toFixed(2);
    }
    report.push(row);
  }
}
// One scene, one buffer, shared textures, compressed.
const [scene, ...extra] = out.getRoot().listScenes();
for (const s of extra) {
  for (const c of s.listChildren()) scene.addChild(c);
  s.dispose();
}
await out.transform(unpartition(), dedup(), prune(), meshopt({ encoder: MeshoptEncoder, level: "medium" }));
writeFileSync(OUT, await io.writeBinary(out));
console.table(report);
console.log(`plants.glb: ${(readFileSync(OUT).length / 1e6).toFixed(2)} MB -> ${OUT}`);
