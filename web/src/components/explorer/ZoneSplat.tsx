"use client";

import { useThree } from "@react-three/fiber";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { useEffect, useRef } from "react";

// Spark objects own GPU resources, so they are created and added to the scene
// in effects (not memos): Strict Mode's mount/unmount/mount would otherwise
// reuse an object that was already disposed.

export function SparkRendererObject() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  useEffect(() => {
    const spark = new SparkRenderer({ renderer: gl });
    scene.add(spark);
    return () => {
      scene.remove(spark);
      spark.dispose();
    };
  }, [gl, scene]);
  return null;
}

/**
 * One zone's splat. Streams it in with byte progress, reports when Spark has
 * decoded it, and frees GPU memory when the zone changes (only one zone is
 * ever resident).
 */
export default function ZoneSplat({
  url,
  onProgress,
  onReady,
  onError,
}: {
  url: string;
  onProgress: (p: number) => void;
  onReady: () => void;
  onError: (message: string) => void;
}) {
  const scene = useThree((s) => s.scene);
  const cb = useRef({ onProgress, onReady, onError });
  useEffect(() => {
    cb.current = { onProgress, onReady, onError };
  });

  useEffect(() => {
    let alive = true;
    const mesh = new SplatMesh({
      url,
      onProgress: (e) => alive && cb.current.onProgress(e.lengthComputable ? e.loaded / e.total : -1),
    });
    scene.add(mesh);
    mesh.initialized
      .then(() => alive && cb.current.onReady())
      .catch((e: unknown) => alive && cb.current.onError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
      scene.remove(mesh);
      mesh.dispose();
    };
  }, [url, scene]);

  return null;
}
