"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { blockedByBuilding, type Occluder, type Place } from "@/lib/world";

const CHECK_EVERY = 0.2; // seconds between visibility updates
/** Distance band (m) in which each tier is labelled. Zones hide once you're inside them. */
const RANGE: Record<Place["tier"], [number, number]> = { 1: [70, 3000], 2: [0, 350], 3: [0, 90] };
const FADE = 0.15; // fraction of the band's far end used to fade out

const STYLE: Record<Place["tier"], string> = {
  1: "px-3.5 py-1.5 text-sm font-semibold tracking-wide uppercase bg-black/60 border-white/40",
  2: "px-2.5 py-1 text-xs font-medium bg-black/50 border-white/25",
  3: "px-2 py-0.5 text-[11px] bg-black/40 border-white/15",
};
const DOT: Record<Place["kind"], string> = {
  zone: "bg-amber-400",
  building: "bg-sky-300",
  shed: "bg-sky-300",
  surface: "bg-emerald-400",
  water: "bg-cyan-300",
};

/**
 * A name label on every part of the site. Zones are labelled from afar, main
 * places within a few hundred metres, small things only close up, so the view
 * never fills with text. Labels behind the viewer or behind a wall are hidden.
 * Clicking a label selects the place.
 */
export default function PlaceLabels({
  places,
  occluders,
  selected,
  onSelect,
}: {
  places: Place[];
  occluders: Occluder[];
  selected: string | null;
  onSelect: (p: Place) => void;
}) {
  const elsRef = useRef<(HTMLButtonElement | null)[]>([]);
  const timerRef = useRef(CHECK_EVERY);
  const fwdRef = useRef(new THREE.Vector3());
  const dirRef = useRef(new THREE.Vector3());

  useFrame(({ camera }, dt) => {
    timerRef.current += dt;
    if (timerRef.current < CHECK_EVERY) return;
    timerRef.current = 0;
    camera.getWorldDirection(fwdRef.current);
    places.forEach((p, i) => {
      const el = elsRef.current[i];
      if (!el) return;
      const dir = dirRef.current.set(...p.position).sub(camera.position);
      const d = dir.length();
      const [near, far] = RANGE[p.tier];
      let a = d < near || d > far ? 0 : Math.min(1, (far - d) / (far * FADE));
      if (p.id === selected) a = 1;
      if (dir.dot(fwdRef.current) <= 0) a = 0; // behind the viewer
      if (a > 0 && p.tier > 1 && blockedByBuilding(occluders, camera.position.toArray(), p.position)) a = 0;
      el.style.opacity = a.toFixed(2);
      el.style.pointerEvents = a > 0.3 ? "auto" : "none";
    });
  });

  return (
    <>
      {places.map((p, i) => (
        <Html key={p.id} position={p.position} center zIndexRange={[15, 5]}>
          <button
            ref={(el) => {
              elsRef.current[i] = el;
            }}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(p);
            }}
            title={p.description || p.name}
            style={{ opacity: 0 }}
            className={`flex items-center gap-1.5 whitespace-nowrap rounded-full border text-white shadow-lg backdrop-blur-md transition-[opacity,background-color] duration-300 hover:bg-black/80 ${STYLE[p.tier]} ${
              p.id === selected ? "ring-2 ring-amber-400" : ""
            }`}
          >
            <span className={`size-1.5 shrink-0 rounded-full ${DOT[p.kind]}`} />
            {p.name}
          </button>
        </Html>
      ))}
    </>
  );
}
