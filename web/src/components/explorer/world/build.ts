import * as THREE from "three";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { type WorldManifest, worldBase } from "@/lib/world";
import { CollisionWorld } from "../collision";
import { basin, box, gable, GeometryBuilder, polygon, prism, ribbon, shoreWall, type V3 } from "./geometry";
import { createMaterials } from "./materials";
import { PlantField } from "./plants";

/** The world built in the browser from world.json (no Blender). */
export interface BuiltWorld {
  group: THREE.Group;
  collision: CollisionWorld;
  plants: PlantField;
  stats: { meshes: number; triangles: number; collisionTriangles: number; plants: number };
}

// Built once per session and shared by every zone of the world.
const worlds = new Map<string, Promise<BuiltWorld>>();

export function loadBuiltWorld(url: string, manifest: WorldManifest, onProgress: (p: number) => void): Promise<BuiltWorld> {
  let p = worlds.get(url);
  if (!p) {
    p = build(url, manifest, onProgress);
    p.catch(() => worlds.delete(url));
    worlds.set(url, p);
  } else {
    onProgress(1);
  }
  return p;
}

async function build(url: string, manifest: WorldManifest, onProgress: (p: number) => void): Promise<BuiltWorld> {
  const base = worldBase(url);
  const manager = new THREE.LoadingManager();
  manager.onProgress = (_u, loaded, total) => onProgress(total ? (0.9 * loaded) / total : -1);
  const allLoaded = new Promise<void>((resolve, reject) => {
    manager.onLoad = resolve;
    manager.onError = (u) => reject(new Error(`Could not load ${u}`));
  });
  const materials = createMaterials(manifest, base, manager);
  const loader = new GLTFLoader(manager).setMeshoptDecoder(MeshoptDecoder);
  const plantsGltf = loader.loadAsync(base + manifest.assets.plants);

  // Static world: one builder (so one mesh) per material.
  const builders = new Map<string, GeometryBuilder>();
  const get = (name: string) => {
    let b = builders.get(name);
    if (!b) {
      const m = manifest.materials[name];
      b = new GeometryBuilder(m.vertexColors ? [...(m.color ?? [1, 1, 1]), m.opacity ?? 1] as [number, number, number, number] : null);
      builders.set(name, b);
    }
    return b;
  };
  for (const s of manifest.surfaces) polygon(get(s.material), s.polygon, s.holes, s.y);
  for (const r of manifest.ribbons) ribbon(get(r.material), r.points, r.width, r.y);
  for (const p of manifest.prisms) prism(get(p.material), p.footprint, p.y0, p.y1);
  for (const g of manifest.gables) gable(get(g.material), g.eave, g.ridge, g.y, g.rise);
  for (const [material, boxes] of Object.entries(manifest.boxes)) for (const bx of boxes) box(get(material), bx);
  for (const b of manifest.basins) basin(get(b.bank.material), get(b.water.material), b);
  // The pool shell faces into the pool; its water faces up.
  const corners = Object.values(manifest.quads).flat(2);
  const poolCentre: V3 = [
    corners.reduce((s, c) => s + c[0], 0) / Math.max(1, corners.length),
    Math.max(...corners.map((c) => c[1])),
    corners.reduce((s, c) => s + c[2], 0) / Math.max(1, corners.length),
  ];
  for (const [material, quads] of Object.entries(manifest.quads)) {
    const water = !!manifest.materials[material].vertexColors;
    for (const [a, b, c, d] of quads) get(material).quad(a, b, c, d, water ? "up" : { toward: poolCentre });
  }

  const group = new THREE.Group();
  group.name = "vantara-world";
  let triangles = 0;
  const solid: number[][] = [];
  for (const [name, b] of builders) {
    if (!b.triangles) continue;
    const m = manifest.materials[name];
    const mesh = new THREE.Mesh(b.build(m.tile ?? 1), materials[name]);
    mesh.name = name;
    const flat = m.layer !== undefined;
    mesh.castShadow = !flat && !m.vertexColors && !m.chainlink;
    mesh.receiveShadow = !m.vertexColors;
    mesh.matrixAutoUpdate = false;
    if (m.vertexColors) mesh.renderOrder = 1;
    group.add(mesh);
    triangles += b.triangles;
    if (!m.vertexColors) solid.push(b.positions());
  }

  // Collision: everything solid, walls along every shore, tree trunks and rocks.
  const extra = new GeometryBuilder();
  for (const b of manifest.basins) {
    const [shore, y] = b.bank.rings[0];
    shoreWall(extra, shore, y - 0.6, y + 1.2);
  }
  for (const [x, y, z, half, h] of PlantField.obstacles(manifest)) box(extra, [x, z, 0, half * 2, half * 2, y, y + h]);
  solid.push(extra.positions());
  const collision = CollisionWorld.fromPositions(Float32Array.from(solid.flat()));

  const gltf = await plantsGltf;
  await allLoaded;
  const plants = new PlantField(gltf.scene, manifest);
  group.add(plants.group);
  onProgress(1);
  const plantCount = Object.values(manifest.plants.instances).reduce((n, r) => n + r.length, 0);
  return {
    group,
    collision,
    plants,
    stats: { meshes: builders.size, triangles, collisionTriangles: collision.geometry.getAttribute("position").count / 3, plants: plantCount },
  };
}
