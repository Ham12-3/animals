/**
 * Where published zone files live (output of world/scripts/export_web.py):
 *   <base>/<zone>/<zone>.json, and <base>/world/ for the shared mesh world
 *
 * Production points NEXT_PUBLIC_ASSET_BASE at the CDN / Vercel Blob. In
 * development it falls back to /dev-assets, which serves pipeline/work.
 */
export const ASSET_BASE = (process.env.NEXT_PUBLIC_ASSET_BASE ?? "").replace(/\/$/, "") || "/dev-assets";

export const assetUrl = (zone: string, file: string) => `${ASSET_BASE}/${zone}/${file}`;

/** Any published file by its path under the asset base, e.g. "world/world.json". */
export const assetPath = (p: string) => `${ASSET_BASE}/${p.replace(/^\//, "")}`;

type Vec3 = [number, number, number];

/** Metadata written by `publish-splat` next to each zone's splats. */
export interface ZoneMeta {
  zone: string;
  units: "m";
  groundY: number;
  files: { desktop: string; mobile: string; collision?: string };
  sizesMB: Record<string, number>;
  splats: Record<string, number>;
  bounds: { min: Vec3; max: Vec3 };
  spawn: { position: Vec3; yawDeg: number };
  eyeHeight: number;
  cameraPath: Vec3[];
  fovY: number;
  north: { deg: number | null; known: boolean };
  /** Ambient + sun fitted to the splats (irradiance, linear RGB); lights meshes such as animals. */
  lighting?: ZoneLighting;
  /**
   * "world": the zone is part of the world compiled by world/scripts/compile_world.py
   * instead of a splat; `world.manifest` is its manifest's path under the asset base.
   */
  kind?: "splat" | "world";
  world?: { manifest: string };
}

export interface ZoneLighting {
  ambient: Vec3;
  sun: { direction: Vec3; color: Vec3 };
  estimated: boolean;
}

/** Neutral daylight for zones published before lighting estimates existed. */
export const DEFAULT_LIGHTING: ZoneLighting = {
  ambient: [0.9, 0.9, 0.9],
  sun: { direction: [0.3, 0.9, 0.3], color: [1.6, 1.55, 1.45] },
  estimated: false,
};

export async function fetchZoneMeta(zone: string, signal?: AbortSignal): Promise<ZoneMeta> {
  const res = await fetch(assetUrl(zone, `${zone}.json`), { signal });
  if (!res.ok) throw new Error(`No published data for zone "${zone}" (${res.status})`);
  return res.json();
}

/**
 * Download with byte progress. `onProgress` gets 0..1, or -1 when the server
 * sends no Content-Length.
 */
export async function fetchWithProgress(
  url: string,
  onProgress: (p: number) => void,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const res = await fetch(url, { signal });
  if (!res.ok || !res.body) throw new Error(`Failed to load ${url} (${res.status})`);
  const total = Number(res.headers.get("Content-Length")) || 0;
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(total ? loaded / total : -1);
  }
  const out = new Uint8Array(loaded);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  onProgress(1);
  return out.buffer;
}
