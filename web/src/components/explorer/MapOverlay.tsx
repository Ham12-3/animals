"use client";

import { mapPoint, type Place, type WorldMap } from "@/lib/world";
import { zonesFile } from "@/lib/zones";

export interface ZoneEntry {
  id: string;
  name: string;
  description?: string;
  map?: { x: number; y: number };
  available: boolean;
  /** Published only on this machine (dev), not part of zones.json. */
  local?: boolean;
}

/** Overview map: jump to any zone that has been published. */
export default function MapOverlay({
  zones,
  current,
  onPick,
  onClose,
  places,
  worldMap,
  onPickPlace,
}: {
  zones: ZoneEntry[];
  current: string | null;
  onPick: (id: string) => void;
  onClose: () => void;
  /** Mesh world: every main place is on the map; click one to fly there. */
  places?: Place[];
  worldMap?: WorldMap;
  onPickPlace?: (p: Place) => void;
}) {
  const placed = zones.filter((z) => z.map);
  const local = zones.filter((z) => z.local);
  return (
    <div
      className="absolute inset-0 z-30 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-label="Overview map"
    >
      <div
        className="w-full max-w-3xl rounded-2xl border border-white/15 bg-neutral-950/90 p-5 text-neutral-100 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Vantara overview</h2>
          <button onClick={onClose} className="rounded-full px-3 py-1 text-sm text-neutral-300 hover:bg-white/10">
            Close <kbd className="ml-1 text-xs text-neutral-500">M</kbd>
          </button>
        </div>

        <div
          className="relative w-full overflow-hidden rounded-xl border border-white/10 bg-[radial-gradient(circle_at_30%_30%,#1f2a1f,#0b0f0b)] bg-cover bg-center"
          style={{
            aspectRatio: `${zonesFile.map.width} / ${zonesFile.map.height}`,
            backgroundImage: `url(${zonesFile.map.image}), radial-gradient(circle at 30% 30%, #1f2a1f, #0b0f0b)`,
          }}
        >
          {places &&
            worldMap &&
            places
              .filter((p) => p.tier === 2)
              .map((p) => {
                const pt = mapPoint(worldMap, p.position);
                return (
                  <button
                    key={p.id}
                    onClick={() => onPickPlace?.(p)}
                    className="group absolute z-0 -translate-x-1/2 -translate-y-1/2 hover:z-20"
                    style={{ left: `${pt.x * 100}%`, top: `${pt.y * 100}%` }}
                    title={`${p.name}: fly there`}
                  >
                    <span className="block size-2 rounded-full bg-white/80 ring-2 ring-black/40 transition group-hover:scale-150 group-hover:bg-amber-300" />
                    <span className="pointer-events-none absolute left-1/2 top-3 hidden -translate-x-1/2 whitespace-nowrap rounded bg-black/80 px-1.5 py-0.5 text-[10px] text-white group-hover:block">
                      {p.name}
                    </span>
                  </button>
                );
              })}
          {placed.map((z) => {
            const isCurrent = z.id === current;
            return (
              <button
                key={z.id}
                disabled={!z.available}
                onClick={() => onPick(z.id)}
                className="group absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center disabled:cursor-not-allowed"
                style={{ left: `${z.map!.x * 100}%`, top: `${z.map!.y * 100}%` }}
                title={z.available ? `Go to ${z.name}` : `${z.name}: not reconstructed yet`}
              >
                <span
                  className={`mx-auto block size-3.5 rounded-full ring-4 transition ${
                    isCurrent
                      ? "bg-amber-400 ring-amber-400/30"
                      : z.available
                        ? "bg-emerald-400 ring-emerald-400/20 group-hover:scale-125"
                        : "bg-neutral-600 ring-neutral-600/20"
                  }`}
                />
                <span className={`mt-1.5 block whitespace-nowrap text-xs ${z.available ? "text-white" : "text-neutral-500"}`}>
                  {z.name}
                  {!z.available && " · soon"}
                </span>
              </button>
            );
          })}
        </div>

        <p className="mt-2 text-[11px] text-neutral-500">
          Top-down render of the 3D model (artistic interpretation). Outline, roads and water: © OpenStreetMap contributors.
        </p>

        {local.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
              Published on this machine (dev only)
            </h3>
            <div className="flex flex-wrap gap-2">
              {local.map((z) => (
                <button
                  key={z.id}
                  onClick={() => onPick(z.id)}
                  className={`rounded-full border px-3 py-1 text-xs ${
                    z.id === current ? "border-amber-400 text-amber-300" : "border-white/20 hover:bg-white/10"
                  }`}
                >
                  {z.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
