import Link from "next/link";
import { zones, zonesFile } from "@/lib/zones";

const STATUS_LABEL: Record<string, string> = {
  "awaiting-footage": "Awaiting footage",
  frames: "Frames extracted",
  posed: "Cameras solved",
  cleaned: "Cleaned",
  live: "Live",
};

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Vantara 3D</h1>
        <p className="text-neutral-500">
          A walkable 3D model of {zonesFile.site.name},{" "}
          {zonesFile.site.location}.
        </p>
        <Link
          href="/explore"
          className="mt-2 w-fit rounded-full bg-emerald-600 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Open the explorer
        </Link>
      </header>

      <section className="grid gap-6 md:grid-cols-[1fr_1fr]">
        {/* Placeholder overview map until a real aerial basemap exists. */}
        <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-neutral-500/30 bg-neutral-500/5">
          {zones.map((z) => (
            <div
              key={z.id}
              className="absolute -translate-x-1/2 -translate-y-1/2 text-center"
              style={{ left: `${z.map.x * 100}%`, top: `${z.map.y * 100}%` }}
            >
              <span className="mx-auto block h-3 w-3 rounded-full bg-emerald-500 ring-4 ring-emerald-500/20" />
              <span className="mt-1 block whitespace-nowrap text-xs">{z.name}</span>
            </div>
          ))}
        </div>

        <ul className="flex flex-col gap-3">
          {zones.map((z) => (
            <li key={z.id} className="rounded-xl border border-neutral-500/30 p-4">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="font-medium">{z.name}</h2>
                <span className="text-xs text-neutral-500">
                  {STATUS_LABEL[z.status ?? "awaiting-footage"]}
                </span>
              </div>
              {z.description && <p className="mt-1 text-sm text-neutral-500">{z.description}</p>}
              {z.status === "live" && (
                <Link href={`/explore?zone=${z.id}`} className="mt-2 inline-block text-sm text-emerald-600 underline">
                  Explore
                </Link>
              )}
            </li>
          ))}
        </ul>
      </section>

    </main>
  );
}
