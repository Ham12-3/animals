import { Suspense } from "react";
import SplatSmokeTest from "@/components/SplatSmokeTestLoader";

export const metadata = { title: "Spark smoke test · Vantara 3D" };

async function Viewer({ searchParams }: { searchParams: PageProps<"/dev/spark">["searchParams"] }) {
  const { zone } = await searchParams;
  return <SplatSmokeTest zone={typeof zone === "string" ? zone : undefined} />;
}

export default function SparkSmokeTestPage({ searchParams }: PageProps<"/dev/spark">) {
  return (
    <main className="h-[calc(100dvh-3rem)] w-full bg-black">
      <Suspense>
        <Viewer searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
