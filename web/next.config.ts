import type { NextConfig } from "next";

/**
 * CORS fallback for the 3D assets on Vercel Blob. three.js loads textures and
 * models cross-origin, which needs Access-Control-Allow-Origin on the Blob
 * responses. If they don't send it (scripts/upload-assets.mjs checks), set
 * ASSET_ORIGIN to the Blob store's origin and NEXT_PUBLIC_ASSET_BASE to
 * /assets/<version>: this site then serves those files from its own origin.
 */
const ASSET_ORIGIN = (process.env.ASSET_ORIGIN ?? "").replace(/\/$/, "");
if (ASSET_ORIGIN && !/^https:\/\/[a-z0-9.-]+$/i.test(ASSET_ORIGIN)) {
  throw new Error(`ASSET_ORIGIN must be an https origin like https://abc.public.blob.vercel-storage.com (got ${ASSET_ORIGIN})`);
}

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return ASSET_ORIGIN ? [{ source: "/assets/:path*", destination: `${ASSET_ORIGIN}/:path*` }] : [];
  },
};

export default nextConfig;
