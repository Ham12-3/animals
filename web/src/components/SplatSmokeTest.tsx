"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { useEffect, useState } from "react";

// Spark's public sample splat. Only used to prove the Spark + R3F + Next stack
// renders before our own zone splats exist.
const SAMPLE_URL = "https://sparkjs.dev/assets/splats/butterfly.spz";

// Spark objects own GPU resources, so they are created and added to the scene
// in effects (not memos): Strict Mode's mount/unmount/mount would otherwise
// reuse an object that was already disposed.
function Spark() {
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

function Splat({ url, flip, onProgress }: { url: string; flip: boolean; onProgress: (p: number) => void }) {
  const scene = useThree((s) => s.scene);
  useEffect(() => {
    const mesh = new SplatMesh({
      url,
      onProgress: (e) => e.lengthComputable && onProgress(e.loaded / e.total),
      onLoad: () => onProgress(1),
    });
    // Raw trained splats are Y-down; flip to three.js Y-up. Published zones
    // (publish-splat) are already aligned Y-up.
    if (flip) mesh.quaternion.set(1, 0, 0, 0);
    scene.add(mesh);
    return () => {
      scene.remove(mesh);
      mesh.dispose();
    };
  }, [url, flip, onProgress, scene]);
  return null;
}

interface ZoneMeta {
  spawn: { position: [number, number, number]; yawDeg: number };
  fovY: number;
}

/** Stand where the walkthrough started, looking the way the camera looked. */
function SpawnCamera({ zone }: { zone: string }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: { set: (x: number, y: number, z: number) => void };
    update: () => void;
  } | null;
  useEffect(() => {
    if (!controls) return;
    let cancelled = false;
    fetch(`/dev-assets/${zone}/${zone}.json`)
      .then((r) => r.json() as Promise<ZoneMeta>)
      .then(({ spawn, fovY }) => {
        if (cancelled) return;
        const [x, y, z] = spawn.position;
        const yaw = (spawn.yawDeg * Math.PI) / 180;
        camera.position.set(x, y, z);
        if ("fov" in camera) {
          camera.fov = fovY;
          camera.updateProjectionMatrix();
        }
        // Orbit target 1 m ahead at eye level (forward is -Z rotated by yaw).
        controls.target.set(x - Math.sin(yaw), y, z - Math.cos(yaw));
        controls.update();
      });
    return () => {
      cancelled = true;
    };
  }, [zone, camera, controls]);
  return null;
}

export default function SplatSmokeTest({ zone }: { zone?: string }) {
  const [progress, setProgress] = useState(0);
  // ?zone=<name> loads a locally published zone through /dev-assets (dev only).
  const url = zone ? `/dev-assets/${zone}/${zone}.spz` : SAMPLE_URL;
  return (
    <div className="relative h-full w-full">
      <Canvas
        gl={{ antialias: false }}
        camera={{ position: [0, 0, 3], fov: 60, near: 0.01 }}
      >
        <Spark />
        <Splat url={url} flip={!zone} onProgress={setProgress} />
        <OrbitControls makeDefault />
        {zone && <SpawnCamera zone={zone} />}
      </Canvas>
      {progress < 1 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-neutral-300">
          Loading {zone ?? "sample splat"}… {Math.round(progress * 100)}%
        </div>
      )}
    </div>
  );
}
