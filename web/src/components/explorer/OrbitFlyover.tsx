"use client";

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { type ComponentRef, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { ZoneMeta } from "@/lib/assets";
import type { CollisionWorld } from "./collision";

const FLY_HEIGHT = 2.5; // metres above the filmed path
const FLY_SPEED = 2.2; // m/s
const ZOOM_SECONDS = 1.4; // camera flight to a clicked place
const ZOOM_PITCH = THREE.MathUtils.degToRad(38); // look down on the place at this angle

/** Fly the orbit camera to look at `target` from `distance` metres (new `seq` = new flight). */
export interface CameraFocus {
  target: [number, number, number];
  distance: number;
  seq: number;
}

interface Flight {
  fromPos: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toPos: THREE.Vector3;
  toTarget: THREE.Vector3;
  t: number;
}

/**
 * Orbit around the zone, or fly along the path the footage was filmed on.
 * Any pointer input on the scene stops the flyover. A `focus` flies the camera
 * to a place; double-clicking the scene zooms to the point under the pointer.
 */
export default function OrbitFlyover({
  meta,
  enabled,
  flying,
  onStopFlying,
  focus = null,
  world = null,
  onPick,
}: {
  meta: ZoneMeta;
  enabled: boolean;
  flying: boolean;
  onStopFlying: () => void;
  focus?: CameraFocus | null;
  world?: CollisionWorld | null;
  /** Double-click on the scene: the point hit (after the camera starts zooming to it). */
  onPick?: (point: THREE.Vector3) => void;
}) {
  const get = useThree((s) => s.get);
  const gl = useThree((s) => s.gl);
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  const progress = useRef(0);
  const flightRef = useRef<Flight | null>(null);
  const focusRef = useRef(focus);
  const pickRef = useRef(onPick);
  useEffect(() => {
    focusRef.current = focus;
    pickRef.current = onPick;
  });

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
    if (focusRef.current) {
      // A place was clicked from walk mode: keep this view and fly from it.
      ctl.target.copy(camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(10).add(camera.position));
      ctl.update();
      return;
    }
    ctl.target.copy(center);
    const dir = camera.position.clone().sub(center).setY(0);
    if (dir.lengthSq() < 1) dir.set(0, 0, 1);
    dir.setLength(Math.min(radius, 25));
    camera.position.copy(center).add(dir).setY(center.y + Math.min(radius * 0.6, 15));
    ctl.update();
  }, [enabled, get, center, radius]);

  // Fly to a place: keep the current compass direction, look down at ZOOM_PITCH.
  useEffect(() => {
    if (!enabled || !focus || !controls.current) return;
    const camera = get().camera;
    const toTarget = new THREE.Vector3(...focus.target);
    const dir = camera.position.clone().sub(toTarget).setY(0);
    if (dir.lengthSq() < 1) dir.set(0, 0, 1);
    dir.normalize().multiplyScalar(Math.cos(ZOOM_PITCH) * focus.distance);
    const toPos = toTarget.clone().add(dir).setY(toTarget.y + Math.sin(ZOOM_PITCH) * focus.distance);
    flightRef.current = {
      fromPos: camera.position.clone(),
      fromTarget: controls.current.target.clone(),
      toPos,
      toTarget,
      t: 0,
    };
    // `seq` changes on every click, even on the same place.
  }, [enabled, focus, get]);

  // Double-click: zoom to the point under the pointer.
  useEffect(() => {
    if (!enabled || flying || !world) return;
    const el = gl.domElement;
    const onDbl = (e: MouseEvent) => {
      const { camera } = get();
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, camera);
      const hit = world.raycast(ray.ray.origin, ray.ray.direction, 3000);
      if (!hit || !controls.current) return;
      const distance = Math.max(12, Math.min(camera.position.distanceTo(hit.point) * 0.45, 120));
      const dir = camera.position.clone().sub(hit.point).setLength(distance);
      flightRef.current = {
        fromPos: camera.position.clone(),
        fromTarget: controls.current.target.clone(),
        toPos: hit.point.clone().add(dir),
        toTarget: hit.point.clone(),
        t: 0,
      };
      pickRef.current?.(hit.point.clone());
    };
    el.addEventListener("dblclick", onDbl);
    return () => el.removeEventListener("dblclick", onDbl);
  }, [enabled, flying, world, gl, get]);

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
    const f = flightRef.current;
    if (enabled && f && controls.current) {
      f.t = Math.min(1, f.t + dt / ZOOM_SECONDS);
      const k = f.t * f.t * (3 - 2 * f.t); // ease in-out
      camera.position.lerpVectors(f.fromPos, f.toPos, k);
      // Arc up a little on long flights so the camera doesn't skim the ground.
      camera.position.y += Math.sin(Math.PI * k) * Math.min(80, f.fromPos.distanceTo(f.toPos) * 0.25);
      controls.current.target.lerpVectors(f.fromTarget, f.toTarget, k);
      controls.current.update();
      if (f.t >= 1) flightRef.current = null;
      return;
    }
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
