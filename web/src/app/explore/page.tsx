import { Suspense } from "react";
import Explorer from "@/components/explorer/ExplorerLoader";

export const metadata = { title: "Explore", description: "Walk, orbit or fly over the Vantara 3D model; click any name to fly there." };

async function ExploreRoute({ searchParams }: { searchParams: PageProps<"/explore">["searchParams"] }) {
  const { zone, debug } = await searchParams;
  return <Explorer initialZone={typeof zone === "string" ? zone : undefined} debug={debug !== undefined} />;
}

export default function ExplorePage({ searchParams }: PageProps<"/explore">) {
  return (
    <main className="relative h-[calc(100dvh-3rem)] w-full overflow-hidden bg-black">
      <Suspense>
        <ExploreRoute searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
