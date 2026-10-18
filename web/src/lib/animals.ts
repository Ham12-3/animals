import manifest from "@/content/animals.json";
import placementsFile from "@/content/animal-placements.json";
import { assetUrl } from "@/lib/assets";
import type { AnimalKind } from "@/lib/zones";

/** One animal model in web/public/models (see content/animals.json). */
export interface AnimalSpec {
  file: string;
  heightM: number;
  lengthM: number;
  widthM: number;
  walkSpeed: number;
  clips: { name: string; seconds: number }[];
  idleClip: string | null;
  walkClip: string | null;
  extraClips: string[];
  placeholder: boolean;
  credit: string;
}

/** Where an animal lives in a zone: waypoints on the ground (x, z), in zone metres. */
export interface AnimalPlacement {
  animal: AnimalKind;
  path: [number, number][];
  /** Seconds to idle at each waypoint: [min, max]. */
  idleSeconds?: [number, number];
}

export const animalSpecs = (manifest as unknown as { animals: Record<string, AnimalSpec> }).animals;

/**
 * Animal GLBs: web/public/models in development; NEXT_PUBLIC_MODEL_BASE (CDN)
 * in production.
 */
const MODEL_BASE = (process.env.NEXT_PUBLIC_MODEL_BASE ?? "").replace(/\/$/, "") || "/models";
export const modelUrl = (file: string) => `${MODEL_BASE}/${file}`;

const bundled = (placementsFile as unknown as { zones: Record<string, AnimalPlacement[]> }).zones;

/** Placements for a zone: the content file, or (dev, local zones) animals.json beside its files. */
export async function loadPlacements(zone: string): Promise<AnimalPlacement[]> {
  const list = bundled[zone] ?? (await loadLocal(zone));
  return list.filter((p) => animalSpecs[p.animal] && p.path.length > 0);
}

async function loadLocal(zone: string): Promise<AnimalPlacement[]> {
  if (process.env.NODE_ENV !== "development") return [];
  try {
    const res = await fetch(assetUrl(zone, "animals.json"));
    return res.ok ? ((await res.json()) as AnimalPlacement[]) : [];
  } catch {
    return [];
  }
}
