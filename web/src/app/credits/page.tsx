import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Credits",
  description: "Map data, textures, plant and animal models, and software behind Vantara 3D.",
};

const TEXTURES = [
  "dry_ground_01", "sand_01", "withered_grass", "asphalt_02", "red_sandstone_pavement",
  "white_plaster_02", "yellow_plaster", "corrugated_iron_02", "clay_roof_tiles", "brown_mud_02",
]; // prettier-ignore
const PLANTS = ["island_tree_02", "searsia_lucida", "shrub_02", "wild_rooibos_bush", "boulder_01", "namaqualand_boulder_02"];

const ANIMALS = [
  { animal: "Elephant", model: "low poly elephant", author: "syncopika", url: "https://opengameart.org/node/92420" },
  { animal: "Tiger", model: "Tiger", author: "Micket", url: "https://opengameart.org/content/tiger" },
  { animal: "Rhino", model: "White Rhinoceros", author: "Micket", url: "https://opengameart.org/content/white-rhinoceros" },
];

const SOFTWARE = [
  ["three.js", "https://threejs.org", "MIT"],
  ["React Three Fiber and drei", "https://github.com/pmndrs/react-three-fiber", "MIT"],
  ["three-mesh-bvh", "https://github.com/gkjohnson/three-mesh-bvh", "MIT"],
  ["Next.js", "https://nextjs.org", "MIT"],
  ["glTF Transform", "https://gltf-transform.dev", "MIT"],
  ["meshoptimizer", "https://github.com/zeux/meshoptimizer", "MIT"],
  ["Geist font", "https://vercel.com/font", "SIL Open Font License"],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="flex flex-col gap-2 text-sm leading-relaxed text-neutral-600 dark:text-neutral-400">{children}</div>
    </section>
  );
}

const A = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} className="text-emerald-700 underline underline-offset-2 dark:text-emerald-400" target="_blank" rel="noreferrer">
    {children}
  </a>
);

export default function CreditsPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Credits</h1>
        <p className="text-neutral-500">
          Vantara 3D is an unofficial, fan-made artistic interpretation. It is not affiliated with or endorsed by
          Vantara. <Link href="/explore" className="text-emerald-700 underline dark:text-emerald-400">Open the explorer</Link>
        </p>
      </header>

      <Section title="What is real, what is designed">
        <p>
          Vantara&apos;s outline, the surrounding roads, lakes, streams and the railway come from OpenStreetMap, at real
          scale. Everything inside the site (enclosures, buildings, pools, planting) is designed from public
          descriptions, not surveyed. The sun is placed for Jamnagar at 10:00 IST on 15 March.
        </p>
      </Section>

      <Section title="Map data">
        <p>
          © <A href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</A>, available under the Open
          Database License (ODbL).
        </p>
      </Section>

      <Section title="Textures and plants">
        <p>
          From <A href="https://polyhaven.com">Poly Haven</A>, public domain (CC0). Resized and compressed for the web.
        </p>
        <p>
          Textures:{" "}
          {TEXTURES.map((t, i) => (
            <span key={t}>
              <A href={`https://polyhaven.com/a/${t}`}>{t}</A>
              {i < TEXTURES.length - 1 ? ", " : ""}
            </span>
          ))}
          .
        </p>
        <p>
          Plants and rocks:{" "}
          {PLANTS.map((t, i) => (
            <span key={t}>
              <A href={`https://polyhaven.com/a/${t}`}>{t}</A>
              {i < PLANTS.length - 1 ? ", " : ""}
            </span>
          ))}
          .
        </p>
      </Section>

      <Section title="Animals">
        <p>Low-poly placeholders, public domain (CC0), from OpenGameArt. Credited with thanks.</p>
        <ul className="list-disc pl-5">
          {ANIMALS.map((a) => (
            <li key={a.animal}>
              {a.animal}: <A href={a.url}>{a.model}</A> by {a.author}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Software">
        <ul className="list-disc pl-5">
          {SOFTWARE.map(([name, url, licence]) => (
            <li key={name}>
              <A href={url}>{name}</A> ({licence})
            </li>
          ))}
        </ul>
      </Section>
    </main>
  );
}
