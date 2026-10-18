import * as THREE from "three";
import type { WorldManifest } from "@/lib/world";

/** Hand-over distances (m) between levels: near model, far model, then (trees) a billboard. */
const LOD_DISTANCES: Record<string, number[]> = { tree: [35, 100], bush: [50], shrub: [40], rock: [60] };
/** Beyond this, small plants are a few pixels: not drawn at all (trees always are). */
const CULL_DISTANCE: Record<string, number> = { shrub: 130, rock: 150, bush: 220, tree: Infinity };
const BILLBOARD_PX = 512;

interface Part {
  batch: THREE.BatchedMesh;
  id: number;
  /** Geometry id per level of detail (null: this material isn't in that level). */
  geometry: (number | null)[];
}

interface Plant {
  x: number;
  z: number;
  role: string;
  level: number; // -1: culled
  parts: Part[];
  billboard: { batch: THREE.BatchedMesh; id: number } | null;
  matrix: THREE.Matrix4;
}

/** Float attributes (meshopt data is quantised), the node transform baked in, only what the batch needs. */
function bake(mesh: THREE.Mesh): THREE.BufferGeometry {
  const src = mesh.geometry as THREE.BufferGeometry;
  const g = new THREE.BufferGeometry();
  for (const name of ["position", "normal", "uv"] as const) {
    const a = src.getAttribute(name) as THREE.BufferAttribute | undefined;
    const size = name === "uv" ? 2 : 3;
    const out = new Float32Array(src.getAttribute("position").count * size);
    if (a) for (let i = 0; i < a.count; i++) for (let k = 0; k < size; k++) out[i * size + k] = a.getComponent(i, k);
    g.setAttribute(name, new THREE.BufferAttribute(out, size));
  }
  const n = g.getAttribute("position").count;
  g.setIndex(src.index ? Array.from(src.index.array as ArrayLike<number>) : [...Array(n).keys()]);
  if (!src.getAttribute("normal")) g.computeVertexNormals();
  g.applyMatrix4(mesh.matrixWorld);
  return g;
}

/** Leaf cards come alpha-blended: cut them out instead, so they sort, write depth and cast shadows. */
function prepareFoliage(m: THREE.Material) {
  const s = m as THREE.MeshStandardMaterial;
  if (s.transparent || s.alphaTest > 0 || /leaves|twigs/i.test(s.name)) {
    s.transparent = false;
    s.alphaTest = 0.5;
    s.depthWrite = true;
    s.side = THREE.DoubleSide;
  }
}

/**
 * Every plant of the world in a handful of BatchedMeshes (one per plant material):
 * one draw call each, per-plant frustum culling, and each plant switching its
 * level of detail in place (setGeometryIdAt) as the viewer moves. Distant trees
 * become billboards: two crossed quads showing renders of the near model, made
 * once on this machine (makeBillboards) so they match the scene's light.
 */
export class PlantField {
  readonly group = new THREE.Group();
  private plants: Plant[] = [];
  private batches: THREE.BatchedMesh[] = [];
  private nearModels = new Map<string, THREE.Mesh[]>(); // tree variant -> its lod0 meshes (for billboards)
  private billboardsMade = false;

  constructor(scene: THREE.Object3D, manifest: WorldManifest) {
    this.group.name = "plants";
    scene.updateMatrixWorld(true);
    const variants = manifest.plants.variants;
    // Pass 1: geometry per (material, variant, level).
    const perMaterial = new Map<THREE.Material, { variant: string; level: number; geometry: THREE.BufferGeometry }[]>();
    for (const name of Object.keys(manifest.plants.instances)) {
      for (let level = 0; level < 2; level++) {
        scene.getObjectByName(`${name}|lod${level}`)?.traverse((o) => {
          if (!(o instanceof THREE.Mesh)) return;
          const material = o.material as THREE.Material;
          prepareFoliage(material);
          const geometry = bake(o);
          if (!perMaterial.has(material)) perMaterial.set(material, []);
          perMaterial.get(material)!.push({ variant: name, level, geometry });
          if (level === 0 && variants[name].role === "tree") {
            if (!this.nearModels.has(name)) this.nearModels.set(name, []);
            // Own material copy: rendering the batch's material on a plain mesh first would leave it
            // compiled for non-batched drawing, and the batch would then draw nothing.
            this.nearModels.get(name)!.push(new THREE.Mesh(geometry, material.clone()));
          }
        });
      }
    }
    // Pass 2: one batch per material, sized to fit its geometries and instances.
    const partsOf = new Map<string, { batch: THREE.BatchedMesh; geometry: (number | null)[] }[]>();
    for (const [material, entries] of perMaterial) {
      const verts = entries.reduce((n, e) => n + e.geometry.getAttribute("position").count, 0);
      const index = entries.reduce((n, e) => n + (e.geometry.index?.count ?? 0), 0);
      const used = [...new Set(entries.map((e) => e.variant))];
      const instances = used.reduce((n, v) => n + manifest.plants.instances[v].length, 0);
      const batch = new THREE.BatchedMesh(instances, verts, index, material);
      batch.name = `plants: ${material.name}`;
      batch.perObjectFrustumCulled = true;
      batch.sortObjects = false; // opaque and cut-out only
      batch.frustumCulled = false; // the plants are spread over the whole site
      batch.castShadow = true;
      batch.receiveShadow = true;
      for (const v of used) {
        const ids: (number | null)[] = [null, null];
        for (const e of entries) if (e.variant === v) ids[e.level] = batch.addGeometry(e.geometry);
        if (!partsOf.has(v)) partsOf.set(v, []);
        partsOf.get(v)!.push({ batch, geometry: ids });
      }
      this.batches.push(batch);
      this.group.add(batch);
    }
    // Pass 3: every plant, hidden until the first update places its level.
    const q = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    for (const [name, rows] of Object.entries(manifest.plants.instances)) {
      for (const [x, y, z, yaw, s] of rows) {
        const matrix = new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), q.setFromAxisAngle(up, yaw), new THREE.Vector3(s, s, s));
        const parts = (partsOf.get(name) ?? []).map(({ batch, geometry }) => {
          const first = geometry.find((g) => g !== null)!;
          const id = batch.addInstance(first);
          batch.setMatrixAt(id, matrix);
          batch.setVisibleAt(id, false);
          return { batch, id, geometry };
        });
        this.plants.push({ x, z, role: variants[name].role, level: -2, parts, billboard: null, matrix });
      }
    }
  }

  /**
   * Render each tree variant's near model from the front and the side into one
   * atlas (front | side) and add crossed-quad billboards for every tree.
   */
  makeBillboards(renderer: THREE.WebGLRenderer, sunDir: THREE.Vector3) {
    if (this.billboardsMade) return;
    this.billboardsMade = true;
    for (const [name, meshes] of this.nearModels) {
      const model = new THREE.Group();
      for (const m of meshes) model.add(m);
      const box = new THREE.Box3().setFromObject(model);
      const height = box.max.y;
      const size = Math.max(box.max.x - box.min.x, box.max.z - box.min.z, height) * 1.04;
      const scene = new THREE.Scene();
      scene.add(model, new THREE.HemisphereLight(0xbfd8ff, 0x6b5a45, 1.1));
      const sun = new THREE.DirectionalLight(0xfff0dc, 2.6);
      sun.position.copy(sunDir).multiplyScalar(50);
      scene.add(sun);
      const camera = new THREE.OrthographicCamera(-size / 2, size / 2, size / 2, -size / 2, 0.1, 400);
      const target = new THREE.WebGLRenderTarget(BILLBOARD_PX * 2, BILLBOARD_PX, { generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter });
      const before = { target: renderer.getRenderTarget(), autoClear: renderer.autoClear, color: renderer.getClearColor(new THREE.Color()), alpha: renderer.getClearAlpha() };
      renderer.autoClear = false;
      renderer.setClearColor(0x000000, 0);
      renderer.setRenderTarget(target);
      renderer.clear();
      for (const [i, eye] of [[0, height / 2, 100], [100, height / 2, 0]].entries()) {
        target.viewport.set(i * BILLBOARD_PX, 0, BILLBOARD_PX, BILLBOARD_PX);
        renderer.setRenderTarget(target); // applies the viewport
        camera.position.set(eye[0], eye[1], eye[2]);
        camera.lookAt(0, height / 2, 0);
        renderer.render(scene, camera);
      }
      renderer.setRenderTarget(before.target);
      renderer.autoClear = before.autoClear;
      renderer.setClearColor(before.color, before.alpha);
      for (const m of meshes) {
        model.remove(m);
        (m.material as THREE.Material).dispose();
      }

      // Crossed quads: front (XY plane) shows the left half, side (ZY plane) the right half.
      const h = size / 2;
      const y0 = height / 2 - h;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute([
        -h, y0, 0, h, y0, 0, h, y0 + size, 0, -h, y0 + size, 0,
        0, y0, h, 0, y0, -h, 0, y0 + size, -h, 0, y0 + size, h,
      ], 3)); // prettier-ignore
      geometry.setAttribute("normal", new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0], 3));
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 0.5, 0, 0.5, 1, 0, 1, 0.5, 0, 1, 0, 1, 1, 0.5, 1], 2));
      geometry.setIndex([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
      const material = new THREE.MeshBasicMaterial({ name: `billboard: ${name}`, map: target.texture, alphaTest: 0.5, side: THREE.DoubleSide });
      const trees = this.plants.filter((p) => p.role === "tree");
      const batch = new THREE.BatchedMesh(trees.length, 8, 12, material);
      batch.name = `billboards: ${name}`;
      batch.perObjectFrustumCulled = true;
      batch.sortObjects = false;
      batch.frustumCulled = false;
      const gid = batch.addGeometry(geometry);
      for (const p of trees) {
        const id = batch.addInstance(gid);
        batch.setMatrixAt(id, p.matrix);
        batch.setVisibleAt(id, false);
        p.billboard = { batch, id };
        p.level = -2; // re-place on the next update
      }
      this.batches.push(batch);
      this.group.add(batch);
    }
  }

  /** Re-pick each plant's level for the viewer at `eye`; `detail` (0..1) shrinks every distance. */
  update(eye: THREE.Vector3, detail: number) {
    for (const p of this.plants) {
      const d = Math.hypot(p.x - eye.x, p.z - eye.z);
      let level = -1;
      if (d < CULL_DISTANCE[p.role] * detail) {
        const steps = LOD_DISTANCES[p.role];
        level = steps.findIndex((limit) => d < limit * detail);
        if (level < 0) level = p.billboard ? steps.length : steps.length - 1;
      }
      if (level === p.level) continue;
      p.level = level;
      for (const part of p.parts) {
        const g = level >= 0 && level < part.geometry.length ? part.geometry[level] : null;
        if (g === null) part.batch.setVisibleAt(part.id, false);
        else {
          part.batch.setGeometryIdAt(part.id, g);
          part.batch.setVisibleAt(part.id, true);
        }
      }
      if (p.billboard) p.billboard.batch.setVisibleAt(p.billboard.id, level === 2);
    }
  }

  /** Tree trunks and rocks, for the collision mesh: [x, z, half width, height] boxes. */
  static obstacles(manifest: WorldManifest) {
    const out: [number, number, number, number, number][] = [];
    for (const [name, rows] of Object.entries(manifest.plants.instances)) {
      const role = manifest.plants.variants[name].role;
      if (role !== "tree" && role !== "rock") continue;
      for (const [x, y, z, , s] of rows) out.push(role === "tree" ? [x, y, z, 0.35 * s, 4] : [x, y, z, 0.55 * s, 1.0 * s]);
    }
    return out;
  }
}
