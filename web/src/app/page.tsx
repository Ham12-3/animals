import Link from "next/link";
import { zones, zonesFile } from "@/lib/zones";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Vantara 3D</h1>
        <p className="max-w-2xl text-neutral-500">
          Walk through a 3D model of {zonesFile.site.name}, {zonesFile.site.location}: elephant shelters and pools, the
          wildlife hospital, big-cat enclosures and herbivore paddocks, built from open map data. An artistic
          interpretation, not a survey.
        </p>
        <div className="mt-2 flex flex-wrap gap-3">
          <Link
            href="/explore"
            className="w-fit rounded-full bg-emerald-600 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Open the explorer
          </Link>
          <Link href="/credits" className="w-fit rounded-full border border-neutral-500/40 px-5 py-2 text-sm hover:bg-neutral-500/10">
            Credits
          </Link>
        </div>
      </header>

      <section className="grid gap-6 md:grid-cols-[3fr_2fr]">
        <div
          className="relative overflow-hidden rounded-xl border border-neutral-500/30 bg-neutral-500/5 bg-cover bg-center"
          style={{ aspectRatio: `${zonesFile.map.width} / ${zonesFile.map.height}`, backgroundImage: `url(${zonesFile.map.image})` }}
        >
          {zones.map((z) => (
            <Link
              key={z.id}
              href={`/explore?zone=${z.id}`}
              className="group absolute -translate-x-1/2 -translate-y-1/2 text-center"
              style={{ left: `${z.map.x * 100}%`, top: `${z.map.y * 100}%` }}
              title={`Explore ${z.name}`}
            >
              <span className="mx-auto block size-3 rounded-full bg-emerald-400 ring-4 ring-emerald-400/30 transition group-hover:scale-125" />
              <span className="mt-1 block whitespace-nowrap rounded bg-black/55 px-1.5 py-0.5 text-[11px] text-white">{z.name}</span>
            </Link>
          ))}
        </div>

        <ul className="flex flex-col gap-3">
          {zones.map((z) => (
            <li key={z.id} className="rounded-xl border border-neutral-500/30 p-4">
              <h2 className="font-medium">{z.name}</h2>
              {z.description && <p className="mt-1 text-sm text-neutral-500">{z.description}</p>}
              <Link href={`/explore?zone=${z.id}`} className="mt-2 inline-block text-sm text-emerald-600 underline">
                Explore
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
