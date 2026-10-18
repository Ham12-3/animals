"use client";

import dynamic from "next/dynamic";

// three.js / Spark need the browser (window, WebGL): client only.
const Explorer = dynamic(() => import("./Explorer"), { ssr: false });

export default Explorer;
