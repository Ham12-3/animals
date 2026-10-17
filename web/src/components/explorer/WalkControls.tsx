"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { ZoneMeta } from "@/lib/assets";
import type { CollisionWorld } from "./collision";
import { bindLook, type InputState } from "./input";

const RADIUS = 0.3; // capsule radius (m)
const HEIGHT = 1.75; // capsule height, feet to head
const STEP = 0.35; // highest ledge we step onto / drop we snap down
const MAX_DROP = 1.2; // never walk off anything deeper than this
const WALK = 1.6; // m/s
const RUN = 3.6;
const GRAVITY = 9.8;
const SUBSTEPS = 4;

export interface Player {
  feet: THREE.Vector3;
  velY: number;
  yaw: number;
  pitch: number;
  onGround: boolean;
  lastSafe: THREE.Vector3;
}

/**
 * Floor height under ``p``: the collision mesh where it has a floor, else the
 * zone's fitted ground plane. Splat-derived meshes have holes wherever the
 * floor was rarely filmed (under the camera, under people), and the plane
 * keeps those walkable.
 */
export function groundAt(
  world: CollisionWorld | null,
  p: THREE.Vector3,
  lift: number,
  maxDrop: number,
  planeY: number,
): number | null {
  const mesh = world?.groundBelow(p, lift, maxDrop) ?? null;
  const planeInRange = planeY <= p.y + lift && planeY >= p.y - maxDrop;
  // Mesh surfaces below the fitted plane are reconstruction noise, not floor.
  if (mesh !== null) return planeInRange ? Math.max(mesh, planeY) : mesh;
  return planeInRange ? planeY : null;
}

/** Place the player on the ground under the zone's spawn camera. */
export function spawnPlayer(meta: ZoneMeta, world: CollisionWorld | null): Player {
  const [x, y, z] = meta.spawn.position;
  const feet = new THREE.Vector3(x, y - meta.eyeHeight, z);
  const g = groundAt(world, new THREE.Vector3(x, y, z), 0.2, 4, meta.groundY);
  if (g !== null) feet.y = g;
  return {
    feet,
    velY: 0,
    yaw: THREE.MathUtils.degToRad(meta.spawn.yawDeg),
    pitch: 0,
    onGround: true,
    lastSafe: feet.clone(),
  };
}

/**
 * First-person walking: WASD / joystick to move, mouse (pointer lock) or touch
 * drag to look. A capsule is pushed out of the zone's collision mesh, can't
 * step off ledges deeper than MAX_DROP, and is reset if it ever falls out.
 */
export default function WalkControls({
  playerRef,
  world,
  meta,
  inputRef,
  enabled,
  noclip,
  eyeHeight,
}: {
  playerRef: React.RefObject<Player | null>;
  world: CollisionWorld | null;
  meta: ZoneMeta;
  inputRef: React.RefObject<InputState>;
  enabled: boolean;
  noclip: boolean;
  eyeHeight: number;
}) {
  const gl = useThree((s) => s.gl);
  const tmp = useRef({
    seg: new THREE.Line3(),
    move: new THREE.Vector3(),
    probe: new THREE.Vector3(),
    before: new THREE.Vector3(),
  });

  useEffect(() => (enabled ? bindLook(gl.domElement, inputRef.current) : undefined), [enabled, gl, inputRef]);

  useFrame(({ camera }, rawDt) => {
    const p = playerRef.current;
    const input = inputRef.current;
    if (!enabled || !p) return;
    const dt = Math.min(rawDt, 0.05);
    const t = tmp.current;

    p.yaw += input.look.yaw;
    p.pitch = THREE.MathUtils.clamp(p.pitch + input.look.pitch, -1.45, 1.45);
    input.look.yaw = 0;
    input.look.pitch = 0;

    const speed = input.run ? RUN : WALK;
    const sin = Math.sin(p.yaw);
    const cos = Math.cos(p.yaw);
    // Forward is -Z rotated by yaw; right is +X rotated by yaw.
    t.move.set(-sin * input.move.y + cos * input.move.x, 0, -cos * input.move.y - sin * input.move.x);
    t.move.multiplyScalar(speed);

    if (noclip || !world) {
      // Free movement in the look direction (debug), or no collision data.
      const fly = new THREE.Vector3(0, 0, -input.move.y).applyEuler(new THREE.Euler(p.pitch, p.yaw, 0, "YXZ"));
      fly.add(new THREE.Vector3(cos * input.move.x, 0, -sin * input.move.x)).multiplyScalar(speed * dt * 2);
      p.feet.add(noclip ? fly : t.move.clone().multiplyScalar(dt));
    } else {
      const h = dt / SUBSTEPS;
      for (let i = 0; i < SUBSTEPS; i++) {
        p.velY = p.onGround ? 0 : p.velY - GRAVITY * h;
        const dx = t.move.x * h;
        const dz = t.move.z * h;
        // Ledge guard: only step where there is floor within MAX_DROP.
        t.probe.set(p.feet.x + dx * 4, p.feet.y, p.feet.z + dz * 4);
        const floorAhead = (dx || dz) && p.onGround ? groundAt(world, t.probe, STEP, MAX_DROP, meta.groundY) : 0;
        if (floorAhead !== null) {
          p.feet.x += dx;
          p.feet.z += dz;
        }
        p.feet.y += p.velY * h;

        // Push the capsule out of walls and floor.
        t.seg.start.set(p.feet.x, p.feet.y + RADIUS + STEP * 0.5, p.feet.z);
        t.seg.end.set(p.feet.x, p.feet.y + HEIGHT - RADIUS, p.feet.z);
        t.before.copy(t.seg.start);
        world.resolveCapsule(t.seg, RADIUS);
        p.feet.x += t.seg.start.x - t.before.x;
        p.feet.z += t.seg.start.z - t.before.z;
        p.feet.y += Math.max(0, t.seg.start.y - t.before.y);

        // Ground: snap onto floor within STEP below (walking down slopes/steps).
        const g = groundAt(world, p.feet, STEP, p.onGround ? STEP : 0.05, meta.groundY);
        if (g !== null && p.velY <= 0) {
          p.feet.y = g;
          p.velY = 0;
          p.onGround = true;
        } else {
          p.onGround = false;
        }
      }
      if (p.onGround) p.lastSafe.copy(p.feet);
      if (p.feet.y < meta.bounds.min[1] - 3) {
        p.feet.copy(p.lastSafe);
        p.velY = 0;
      }
    }
    // Stay inside the reconstructed area.
    p.feet.x = THREE.MathUtils.clamp(p.feet.x, meta.bounds.min[0], meta.bounds.max[0]);
    p.feet.z = THREE.MathUtils.clamp(p.feet.z, meta.bounds.min[2], meta.bounds.max[2]);
    if (noclip) p.feet.y = THREE.MathUtils.clamp(p.feet.y, meta.bounds.min[1], meta.bounds.max[1]);

    camera.position.set(p.feet.x, p.feet.y + eyeHeight, p.feet.z);
    camera.rotation.set(p.pitch, p.yaw, 0, "YXZ");
  });

  return null;
}
