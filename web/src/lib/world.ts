import { CollisionWorld } from "@/components/explorer/collision";
import type { AnimalPlacement } from "@/lib/animals";
import { fetchWithProgress } from "@/lib/assets";

type Vec3 = [number, number, number];

/** One plant model (Poly Haven, CC0) and where it grows: [x, y, z, yaw, scale] in metres / radians. */
export interface PlantVariant {
  role: "tree" | "bush" | "shrub" | "rock";
  /** Faces per level of detail (a billboard level has 2). */
  faces: number[];
  /** Distance (m) where level i hands over to level i + 1. */
  lodDistances: number[];
  instances: [number, number, number, number, number][];
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

/** The overview image's frame: centre and span in Blender metres (x east, y north). */
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

/** world/world.json, written by world/scripts/export_web.py. */
export interface WorldManifest {
  format: "vantara-world";
  version: 1;
  note: string;
  attribution: string[];
  units: "m";
  groundY: number;
  /** Static scene parts (glTF with shared external textures), relative to the manifest. */
  parts: { id: string; file: string }[];
  /** Plant models: nodes "<variant>|lod<i>", the last level being a billboard for trees. */
  plants: { file: string; variants: Record<string, PlantVariant> } | null;
  collision: string;
  /** Polygon-offset order for coplanar ground layers, by material name (higher draws on top). */
  depthLayers: Record<string, number>;
  /** Unit vector towards the sun (three.js frame). */
  sun: { direction: Vec3; elevationDeg: number };
  animals: AnimalPlacement[];
  places: Place[];
  /** Solid buildings: footprint [x, z] and top height (m). */
  occluders: Occluder[];
  map: WorldMap;
  bytes: number;
}

/** Folder of a manifest URL, for resolving the files it lists. */
export const worldBase = (manifestUrl: string) => manifestUrl.slice(0, manifestUrl.lastIndexOf("/") + 1);

// One world is shared by several zones: its manifest and collision mesh are
// loaded once and kept for the session, so switching zones inside it is instant.
const manifests = new Map<string, Promise<WorldManifest>>();
const collisions = new Map<string, Promise<CollisionWorld>>();

export function loadWorldManifest(url: string): Promise<WorldManifest> {
  let p = manifests.get(url);
  if (!p) {
    p = fetch(url).then(async (res) => {
      if (!res.ok) throw new Error(`World manifest missing (${res.status})`);
      const m = (await res.json()) as WorldManifest;
      if (m.format !== "vantara-world") throw new Error("Not a world manifest");
      return m;
    });
    p.catch(() => manifests.delete(url));
    manifests.set(url, p);
  }
  return p;
}

export function loadWorldCollision(url: string, onProgress: (p: number) => void): Promise<CollisionWorld> {
  let p = collisions.get(url);
  if (!p) {
    p = fetchWithProgress(url, onProgress).then((buf) => CollisionWorld.fromGlb(buf));
    p.catch(() => collisions.delete(url));
    collisions.set(url, p);
  } else {
    onProgress(1);
  }
  return p;
}
