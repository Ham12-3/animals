import data from "@/content/hotspots.json";
import { assetUrl } from "@/lib/assets";
import type { AnimalKind } from "@/lib/zones";

export interface Hotspot {
  id: string;
  title: string;
  kind: "animal" | "area";
  animal?: AnimalKind;
  body: string;
  position: [number, number, number];
}

const bundled = (data as unknown as { zones: Record<string, Hotspot[]> }).zones;

/**
 * Hotspots for a zone: the bundled content file, or, for zones only published
 * locally, an optional hotspots.json beside the zone's files (dev only).
 */
export async function loadHotspots(zone: string): Promise<Hotspot[]> {
  if (bundled[zone]) return bundled[zone];
  if (process.env.NODE_ENV !== "development") return [];
  try {
    const res = await fetch(assetUrl(zone, "hotspots.json"));
    return res.ok ? ((await res.json()) as Hotspot[]) : [];
  } catch {
    return [];
  }
}
