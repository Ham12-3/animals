"use client";

import { useRef, useState } from "react";
import type { InputState } from "./input";

const RADIUS = 48;

/** Left-thumb movement stick for touch screens; writes into ``input.move``. */
export default function TouchJoystick({ inputRef }: { inputRef: React.RefObject<InputState> }) {
  const origin = useRef<{ x: number; y: number; id: number } | null>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });

  const release = () => {
    origin.current = null;
    const input = inputRef.current;
    input.move.x = 0;
    input.move.y = 0;
    input.run = false;
    setKnob({ x: 0, y: 0 });
  };

  return (
    <div
      className="pointer-events-auto absolute bottom-6 left-6 grid size-32 touch-none place-items-center rounded-full border border-white/25 bg-black/25 backdrop-blur-sm"
      onPointerDown={(e) => {
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        const r = e.currentTarget.getBoundingClientRect();
        origin.current = { x: r.left + r.width / 2, y: r.top + r.height / 2, id: e.pointerId };
      }}
      onPointerMove={(e) => {
        const o = origin.current;
        if (!o || o.id !== e.pointerId) return;
        e.stopPropagation();
        let dx = e.clientX - o.x;
        let dy = e.clientY - o.y;
        const len = Math.hypot(dx, dy);
        if (len > RADIUS) {
          dx = (dx / len) * RADIUS;
          dy = (dy / len) * RADIUS;
        }
        const input = inputRef.current;
        input.move.x = dx / RADIUS;
        input.move.y = -dy / RADIUS;
        input.run = len > RADIUS * 1.4; // push past the rim to jog
        setKnob({ x: dx, y: dy });
      }}
      onPointerUp={release}
      onPointerCancel={release}
      aria-label="Move"
    >
      <div
        className="size-12 rounded-full bg-white/70 shadow"
        style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }}
      />
    </div>
  );
}
