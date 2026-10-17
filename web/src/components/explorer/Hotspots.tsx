"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import type { Hotspot } from "@/lib/hotspots";
import type { CollisionWorld } from "./collision";

const MAX_DISTANCE = 30; // metres; farther hotspots are hidden
const CHECK_EVERY = 0.15; // seconds between occlusion checks

/**
 * Info markers anchored in the zone. Each one hides when it is too far away
 * or when the collision mesh (walls) is between it and the camera.
 */
export default function Hotspots({
  hotspots,
  world,
  onOpen,
}: {
  hotspots: Hotspot[];
  world: CollisionWorld | null;
  onOpen: (h: Hotspot) => void;
}) {
  const els = useRef<(HTMLButtonElement | null)[]>([]);
  const timer = useRef(0);
  const dir = useRef(new THREE.Vector3());
  const pos = useRef(new THREE.Vector3());

  useFrame(({ camera }, dt) => {
    timer.current += dt;
    if (timer.current < CHECK_EVERY) return;
    timer.current = 0;
    hotspots.forEach((h, i) => {
      const el = els.current[i];
      if (!el) return;
      pos.current.set(...h.position);
      const dist = camera.position.distanceTo(pos.current);
      let visible = dist < MAX_DISTANCE;
      if (visible && world) {
        dir.current.subVectors(pos.current, camera.position).normalize();
        const hit = world.raycast(camera.position, dir.current, dist);
        visible = !hit || hit.distance > dist - 0.4;
      }
      el.style.opacity = visible ? "1" : "0";
      el.style.pointerEvents = visible ? "auto" : "none";
    });
  });

  return (
    <>
      {hotspots.map((h, i) => (
        <Html key={h.id} position={h.position} center zIndexRange={[20, 10]}>
          <button
            ref={(el) => {
              els.current[i] = el;
            }}
            onClick={() => onOpen(h)}
            className="flex items-center gap-2 whitespace-nowrap rounded-full border border-white/30 bg-black/55 px-3 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur-md transition-opacity duration-300 hover:bg-black/75"
          >
            <span className={`size-2 rounded-full ${h.kind === "animal" ? "bg-amber-400" : "bg-emerald-400"}`} />
            {h.title}
          </button>
        </Html>
      ))}
    </>
  );
}
