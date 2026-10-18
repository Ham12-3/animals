import type { AnimalPlacement } from "@/lib/animals";

type Vec3 = [number, number, number];
/** A point on the ground plane, three.js [x, z]. */
type XZ = [number, number];

/** A world material (world/scripts/compile_world.py MATERIALS). Colours are linear RGB. */
export interface WorldMaterial {
  /** Poly Haven set: textures/<texture>_diff.jpg and _nor.jpg. */
  texture?: string;
  /** Normal map only (flat colour). */
  normal?: string;
  /** Texture repeat (m); UVs are in world metres. */
  tile?: number;
  /** Multiplies the colour texture. */
  tint?: [number, number, number];
  color?: [number, number, number];
  /** Default opacity for vertex-coloured surfaces given no colours (the pool). */
  opacity?: number;
  roughness?: number;
  metalness?: number;
  /** Draw order of coplanar ground layers (higher wins). */
  layer?: number;
  transparent?: boolean;
  /** Colour and opacity come from the mesh (graded water). */
  vertexColors?: boolean;
  water?: boolean;
  /** Generated chain-link texture. */
  chainlink?: boolean;
}

export interface PlantVariant {
  asset: string;
  role: "tree" | "bush" | "shrub" | "rock";
  scale: [number, number];
}

/**
 * world/world.json, written by world/scripts/compile_world.py: the whole site as
 * simple primitives, built into meshes in the browser (see components/explorer/world).
 */
export interface WorldManifest {
  format: "vantara-world";
  version: 2;
  note: string;
  attribution: string[];
  units: "m";
  assets: { textures: string; plants: string };
  groundY: number;
  /** Towards the sun (three.js frame), elevation and azimuth in degrees. */
  sun: { direction: Vec3; elevationDeg: number; azimuthDeg: number };
  materials: Record<string, WorldMaterial>;
  surfaces: { material: string; y: number; polygon: XZ[]; holes: XZ[][] }[];
  ribbons: { material: string; width: number; y: number; points: XZ[] }[];
  prisms: { material: string; footprint: XZ[]; y0: number; y1: number }[];
  gables: { material: string; eave: XZ[]; ridge: XZ[]; y: number; rise: number }[];
  /** Per material: [cx, cz, rotation about y, length, depth, y0, y1]. */
  boxes: Record<string, [number, number, number, number, number, number, number][]>;
  basins: {
    name: string;
    /** Rings from the shoreline down to the bed (same vertex count). */
    bank: { material: string; rings: [XZ[], number][] };
    /** Rings from the shore inwards, each with a linear RGBA colour. */
    water: { material: string; y: number; rings: [XZ[], [number, number, number, number]][] };
  }[];
  /** Per material: quads of [x, y, z] corners. */
  quads: Record<string, Vec3[][]>;
  /** Nodes "<variant>|lod0" / "|lod1" in plants.glb; instances [x, y, z, yaw, scale]. */
  plants: { variants: Record<string, PlantVariant>; instances: Record<string, [number, number, number, number, number][]> };
  animals: AnimalPlacement[];
  places: Place[];
  /** Solid buildings: footprint [x, z] and top height (m). */
  occluders: Occluder[];
  map: WorldMap;
}

/**
 * A named part of the site (zone, building, enclosure, pond...), for labels,
 * click-to-zoom and the overview map. Positions in the three.js frame.
 */
export interface Place {
  id: string;
  name: string;
  /** 1: zone (always labelled), 2: main place, 3: small thing (labelled close up). */
  tier: 1 | 2 | 3;
  zone: string;
  kind: "zone" | "building" | "shed" | "surface" | "water";
  description: string;
  /** Label anchor, above the place. */
  position: Vec3;
  /** Rough width in metres (sets the zoom distance). */
  size: number;
  /** Walkable spot facing the place, outside buildings, fences and water. */
  stand: { position: Vec3; yawDeg: number } | null;
}

export interface Occluder {
  footprint: [number, number][];
  top: number;
}

/**
 * Does any building stand between `from` and `to`? Exact for vertical prisms:
 * the segment's crossing of each footprint edge is checked against the roof height.
 */
export function blockedByBuilding(occluders: Occluder[], from: Vec3, to: Vec3): boolean {
  const [ax, ay, az] = from;
  const dx = to[0] - ax;
  const dy = to[1] - ay;
  const dz = to[2] - az;
  for (const o of occluders) {
    const f = o.footprint;
    for (let i = 0; i < f.length; i++) {
      const [px, pz] = f[i];
      const [qx, qz] = f[(i + 1) % f.length];
      const ex = qx - px;
      const ez = qz - pz;
      const den = dx * ez - dz * ex;
      if (Math.abs(den) < 1e-9) continue;
      const t = ((px - ax) * ez - (pz - az) * ex) / den; // along the sight line
      const u = ((px - ax) * dz - (pz - az) * dx) / den; // along the edge
      if (t > 0.001 && t < 0.999 && u >= 0 && u <= 1 && ay + dy * t < o.top) return true;
    }
  }
  return false;
}

/** The overview image's frame: centre and span in local metres (x east, y north). */
export interface WorldMap {
  image: string;
  centre: [number, number];
  span: [number, number];
  size: [number, number];
}

/** Position on the overview map (0..1 from the top-left) of a three.js point. */
export function mapPoint(map: WorldMap, [x, , z]: Vec3) {
  return { x: 0.5 + (x - map.centre[0]) / map.span[0], y: 0.5 - (-z - map.centre[1]) / map.span[1] };
}

/** Folder of a manifest URL, for resolving the files it lists. */
export const worldBase = (manifestUrl: string) => manifestUrl.slice(0, manifestUrl.lastIndexOf("/") + 1);

// One world is shared by several zones: its manifest is loaded once per session.
const manifests = new Map<string, Promise<WorldManifest>>();

export function loadWorldManifest(url: string): Promise<WorldManifest> {
  let p = manifests.get(url);
  if (!p) {
    p = fetch(url).then(async (res) => {
      if (!res.ok) throw new Error(`World manifest missing (${res.status})`);
      const m = (await res.json()) as WorldManifest;
      if (m.format !== "vantara-world" || m.version !== 2) throw new Error("Not a version 2 world manifest");
      return m;
    });
    p.catch(() => manifests.delete(url));
    manifests.set(url, p);
  }
  return p;
}
