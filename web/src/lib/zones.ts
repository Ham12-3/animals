import data from "@/data/zones.json";

export type AnimalKind = "elephant" | "tiger" | "lion" | "rhino";

export type ZoneStatus =
  | "awaiting-footage"
  | "frames"
  | "posed"
  | "trained"
  | "cleaned"
  | "live";

export interface Zone {
  id: string;
  name: string;
  description?: string;
  videos: string[];
  /** Position on the overview map, 0..1 from the top-left corner. */
  map: { x: number; y: number };
  animals?: AnimalKind[];
  status?: ZoneStatus;
  /** Phase 5 alignment overrides (publish-splat). */
  align?: { northDeg?: number; eyeHeight?: number; scale?: number };
}

export interface ZonesFile {
  version: 1;
  site: { name: string; location: string; disclaimer: string };
  map: { image: string; width: number; height: number };
  zones: Zone[];
}

export const zonesFile = data as ZonesFile;
export const zones = zonesFile.zones;
