/**
 * Where published zone files live (output of `publish-splat`):
 *   <base>/<zone>/<zone>.spz, <zone>.mobile.spz, <zone>.collision.glb, <zone>.json
 *
 * Production points NEXT_PUBLIC_ASSET_BASE at the CDN / Vercel Blob. In
 * development it falls back to /dev-assets, which serves pipeline/work.
 */
export const ASSET_BASE = (process.env.NEXT_PUBLIC_ASSET_BASE ?? "").replace(/\/$/, "") || "/dev-assets";

export const assetUrl = (zone: string, file: string) => `${ASSET_BASE}/${zone}/${file}`;

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
}

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
