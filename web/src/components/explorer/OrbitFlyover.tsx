"use client";

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { type ComponentRef, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { ZoneMeta } from "@/lib/assets";

const FLY_HEIGHT = 2.5; // metres above the filmed path
const FLY_SPEED = 2.2; // m/s

/**
 * Orbit around the zone, or fly along the path the footage was filmed on.
 * Any pointer input on the scene stops the flyover.
 */
export default function OrbitFlyover({
  meta,
  enabled,
  flying,
  onStopFlying,
}: {
  meta: ZoneMeta;
  enabled: boolean;
  flying: boolean;
  onStopFlying: () => void;
}) {
  const get = useThree((s) => s.get);
  const gl = useThree((s) => s.gl);
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  const progress = useRef(0);

  const { curve, length, center, radius } = useMemo(() => {
    const pts = meta.cameraPath.map(([x, y, z]) => new THREE.Vector3(x, y + FLY_HEIGHT, z));
    if (pts.length < 2) pts.push(pts[0].clone().add(new THREE.Vector3(0.1, 0, 0)));
    const c = new THREE.CatmullRomCurve3(pts, false, "centripetal");
    const lo = new THREE.Vector3(...meta.bounds.min);
    const hi = new THREE.Vector3(...meta.bounds.max);
    const ctr = new THREE.Vector3(...meta.cameraPath.reduce((a, p) => [a[0] + p[0], 0, a[2] + p[2]], [0, 0, 0]));
    ctr.multiplyScalar(1 / Math.max(1, meta.cameraPath.length)).setY(1);
    return { curve: c, length: c.getLength(), center: ctr, radius: hi.sub(lo).setY(0).length() / 2 };
  }, [meta]);

  // Entering orbit: look at the zone from above and behind the current view.
  useEffect(() => {
    if (!enabled || !controls.current) return;
    const ctl = controls.current;
    const camera = get().camera;
    ctl.target.copy(center);
    const dir = camera.position.clone().sub(center).setY(0);
    if (dir.lengthSq() < 1) dir.set(0, 0, 1);
    dir.setLength(Math.min(radius, 25));
    camera.position.copy(center).add(dir).setY(center.y + Math.min(radius * 0.6, 15));
    ctl.update();
  }, [enabled, get, center, radius]);

  // Stop the flyover on any direct interaction.
  useEffect(() => {
    if (!flying) return;
    const stop = () => onStopFlying();
    gl.domElement.addEventListener("pointerdown", stop);
    gl.domElement.addEventListener("wheel", stop);
    return () => {
      gl.domElement.removeEventListener("pointerdown", stop);
      gl.domElement.removeEventListener("wheel", stop);
    };
  }, [flying, gl, onStopFlying]);

  const look = useRef(new THREE.Vector3());
  useFrame(({ camera }, dt) => {
    if (!enabled || !flying) return;
    progress.current = (progress.current + (Math.min(dt, 0.05) * FLY_SPEED) / Math.max(length, 1)) % 1;
    const t = progress.current;
    camera.position.copy(curve.getPointAt(t));
    const ahead = look.current.copy(curve.getPointAt(Math.min(t + 0.02, 1)));
    ahead.y -= 0.6; // tilt slightly down
    camera.lookAt(ahead);
    if (controls.current) controls.current.target.copy(ahead);
  });

  return (
    <OrbitControls
      ref={controls}
      enabled={enabled && !flying}
      enableDamping
      maxPolarAngle={Math.PI * 0.47}
      minDistance={1}
      maxDistance={Math.max(10, radius * 2.5)}
      makeDefault={enabled}
    />
  );
}
