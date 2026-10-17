"use client";

import dynamic from "next/dynamic";

// three.js / Spark touch `window` and WebGL at import time: client only.
const SplatSmokeTest = dynamic(() => import("./SplatSmokeTest"), { ssr: false });

export default SplatSmokeTest;
