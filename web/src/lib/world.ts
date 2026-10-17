import { CollisionWorld } from "@/components/explorer/collision";
import type { AnimalPlacement } from "@/lib/animals";
import { fetchWithProgress } from "@/lib/assets";

type Vec3 = [number, number, number];

/** One plant model (Poly Haven, CC0) and where it grows: [x, y, z, yaw, scale] in metres / radians. */
export interface PlantVariant {
  role: "tree" | "bush" | "shrub" | "rock";
  faces: [number, number];
  instances: [number, number, number, number, number][];
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
  /** Plant models: nodes "<variant>|lod0" / "<variant>|lod1"; LOD1 beyond lodDistance. */
  plants: { file: string; lodDistance: number; variants: Record<string, PlantVariant> } | null;
  collision: string;
  /** Polygon-offset order for coplanar ground layers, by material name (higher draws on top). */
  depthLayers: Record<string, number>;
  /** Unit vector towards the sun (three.js frame). */
  sun: { direction: Vec3; elevationDeg: number };
  animals: AnimalPlacement[];
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
