import * as THREE from "three";
import type { WorldManifest, WorldMaterial } from "@/lib/world";

/** Materials whose surfaces you can see from both sides (roofs from under a shelter, fences). */
const DOUBLE_SIDED = new Set(["roof_gable", "shed_roof", "mesh"]);

/** Chain-link fence: diagonal wires on a transparent 32 px tile (5 cm of fence). */
function chainlinkTexture() {
  const n = 32;
  const c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(108,110,110,1)";
  g.lineWidth = 2.2;
  for (const [x0, y0, x1, y1] of [[0, 0, n, n], [0, n, n, 0], [-n, 0, n, 2 * n], [0, -n, 2 * n, n], [-n, n, n, -n], [0, 2 * n, 2 * n, 0]]) {
    g.beginPath();
    g.moveTo(x0, y0);
    g.lineTo(x1, y1);
    g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/**
 * three.js materials for every world material. Each texture is loaded once and
 * shared; the geometry's UVs carry the tiling (world metres / tile, see
 * GeometryBuilder.build). Ground layers get a polygon offset by
 * `layer` (they are a few cm apart and would flicker in the distance).
 */
export function createMaterials(manifest: WorldManifest, base: string, manager: THREE.LoadingManager) {
  const loader = new THREE.TextureLoader(manager);
  const images = new Map<string, THREE.Texture>();
  const texture = (file: string, colour: boolean) => {
    let t = images.get(file);
    if (!t) {
      t = loader.load(base + manifest.assets.textures + file);
      t.colorSpace = colour ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = 4;
      images.set(file, t);
    }
    return t;
  };

  const out: Record<string, THREE.Material> = {};
  for (const [name, m] of Object.entries(manifest.materials) as [string, WorldMaterial][]) {
    const mat = new THREE.MeshStandardMaterial({ name, roughness: m.roughness ?? 0.9, metalness: m.metalness ?? 0 });
    if (m.texture) {
      mat.map = texture(`${m.texture}_diff.jpg`, true);
      mat.normalMap = texture(`${m.texture}_nor.jpg`, false);
      mat.color.setRGB(...(m.tint ?? [1, 1, 1]));
    } else if (m.color) {
      mat.color.setRGB(...m.color);
    }
    if (m.normal) mat.normalMap = texture(`${m.normal}_nor.jpg`, false);
    if (m.chainlink) {
      mat.map = chainlinkTexture();
      mat.map.wrapS = mat.map.wrapT = THREE.RepeatWrapping;
      mat.color.set(0xffffff);
      mat.transparent = true;
      mat.depthWrite = false;
    }
    if (m.vertexColors) {
      // Graded water: colour and opacity per vertex (see the bank through the shallows).
      mat.vertexColors = true;
      mat.color.set(0xffffff);
      mat.transparent = true;
      mat.depthWrite = false;
    }
    if (m.layer !== undefined) {
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = -m.layer;
      mat.polygonOffsetUnits = -m.layer * 2;
    }
    if (DOUBLE_SIDED.has(name)) mat.side = THREE.DoubleSide;
    out[name] = mat;
  }
  return out;
}
