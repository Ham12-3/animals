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
 * Gentle ripples: a tileable height field (whole-number wave counts across the
 * tile, so it repeats seamlessly) turned into a normal map. It drifts slowly
 * (BuiltWorld.tick), which breaks up the mirror-flat reflection of the sky.
 */
function waterNormalTexture() {
  const n = 128;
  const waves = [[3, 1, 0.0, 1.0], [1, 4, 1.7, 0.8], [5, 3, 0.6, 0.45], [7, -2, 2.9, 0.35], [-4, 6, 4.2, 0.3], [11, 9, 1.1, 0.15]];
  const height = (x: number, y: number) =>
    waves.reduce((h, [fx, fy, ph, a]) => h + a * Math.sin(2 * Math.PI * (fx * x + fy * y) / n + ph), 0);
  const data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const dx = height(x + 1, y) - height(x - 1, y);
      const dy = height(x, y + 1) - height(x, y - 1);
      const len = Math.hypot(dx, dy, 2);
      const i = 4 * (y * n + x);
      data[i] = Math.round(((-dx / len) * 0.5 + 0.5) * 255);
      data[i + 1] = Math.round(((-dy / len) * 0.5 + 0.5) * 255);
      data[i + 2] = Math.round(((2 / len) * 0.5 + 0.5) * 255);
      data[i + 3] = 255;
    }
  }
  const t = new THREE.DataTexture(data, n, n, THREE.RGBAFormat);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
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
  const ripples = waterNormalTexture();
  for (const [name, m] of Object.entries(manifest.materials) as [string, WorldMaterial][]) {
    // Water: a physical material so its reflectance can be turned down (still water
    // under a hazy sky reflects far less than a standard material's ~100% at grazing angles).
    const mat = m.water
      ? new THREE.MeshPhysicalMaterial({ name, roughness: m.roughness ?? 0.15, specularIntensity: 0.35, envMapIntensity: 0.4 })
      : new THREE.MeshStandardMaterial({ name, roughness: m.roughness ?? 0.9, metalness: m.metalness ?? 0 });
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
    if (m.water && name !== "mud_water") {
      mat.normalMap = ripples;
      mat.normalScale.set(0.35, 0.35);
    }
    if (m.layer !== undefined) {
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = -m.layer;
      mat.polygonOffsetUnits = -m.layer * 2;
    }
    if (DOUBLE_SIDED.has(name)) mat.side = THREE.DoubleSide;
    out[name] = mat;
  }
  return { materials: out, ripples };
}
