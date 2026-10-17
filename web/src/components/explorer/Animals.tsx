"use client";

import { useGLTF } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";
import { type AnimalPlacement, type AnimalSpec, animalSpecs, modelUrl } from "@/lib/animals";
import type { ZoneLighting } from "@/lib/assets";
import type { CollisionWorld } from "./collision";
import { groundAt } from "./WalkControls";

const TURN_RATE = THREE.MathUtils.degToRad(55); // rad/s
const FADE = 0.4; // clip cross-fade, seconds

/**
 * The zone's lighting as three.js lights. Values are irradiance in linear RGB
 * (see pipeline/vantara_pipeline/lighting.py), so meshes pick up the same
 * light the splats show.
 */
export function ZoneLights({ lighting }: { lighting: ZoneLighting }) {
  const { ambient, sun, sunPos } = useMemo(() => {
    const split = (rgb: number[]) => {
      const i = Math.max(...rgb, 1e-4);
      return { color: new THREE.Color().setRGB(rgb[0] / i, rgb[1] / i, rgb[2] / i, THREE.LinearSRGBColorSpace), i };
    };
    const d = new THREE.Vector3(...lighting.sun.direction).normalize();
    return { ambient: split(lighting.ambient), sun: split(lighting.sun.color), sunPos: d.multiplyScalar(40) };
  }, [lighting]);
  return (
    <>
      <ambientLight color={ambient.color} intensity={ambient.i} />
      <directionalLight color={sun.color} intensity={sun.i} position={sunPos} />
    </>
  );
}

/** Soft, darkened ellipse under an animal: grounds it on the splat floor. */
function shadowTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
  grad.addColorStop(0, "rgba(0,0,0,0.85)");
  grad.addColorStop(0.55, "rgba(0,0,0,0.45)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

interface Actor {
  root: THREE.Group;
  model: THREE.Object3D;
  shadow: THREE.Mesh;
  mixer: THREE.AnimationMixer;
  actions: Map<string, THREE.AnimationAction>;
  playing: THREE.AnimationAction | null;
  mode: "idle" | "walk";
  timer: number;
  target: number;
  yaw: number;
  phase: number;
  clock: number;
  rng: () => number;
}

function seeded(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function AnimalActor({
  spec,
  placement,
  world,
  groundY,
  sunDirection,
  seed,
  sceneLit,
}: {
  spec: AnimalSpec;
  placement: AnimalPlacement;
  world: CollisionWorld | null;
  groundY: number;
  sunDirection: THREE.Vector3;
  seed: number;
  sceneLit: boolean;
}) {
  const scene = useThree((s) => s.scene);
  const gltf = useGLTF(modelUrl(spec.file));
  const actorRef = useRef<Actor | null>(null);

  useEffect(() => {
    const model = cloneSkinned(gltf.scene);
    model.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.frustumCulled = false; // skinned bounds lag behind poses
        o.castShadow = sceneLit; // a lit mesh world has real sun shadows
      }
    });
    const root = new THREE.Group();
    root.add(model);
    const [x, z] = placement.path[0];
    const next = placement.path[1] ?? placement.path[0];
    root.position.set(x, groundY, z);
    const yaw = Math.atan2(next[0] - x, next[1] - z);
    root.rotation.y = yaw;

    const shadowMat = new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false });
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.scale.set(spec.widthM * 1.5, spec.lengthM * 1.15, 1);
    shadow.renderOrder = 1;
    shadow.visible = !sceneLit;
    scene.add(root, shadow);

    const mixer = new THREE.AnimationMixer(model);
    const actions = new Map(gltf.animations.map((clip) => [clip.name, mixer.clipAction(clip)]));
    const rng = seeded(seed);
    actorRef.current = {
      root, model, shadow, mixer, actions, playing: null, mode: "idle",
      timer: 1 + rng() * 3, target: 1 % placement.path.length, yaw, phase: rng() * 6, clock: 0, rng,
    };  // fmt: skip
    return () => {
      scene.remove(root, shadow);
      mixer.stopAllAction();
      mixer.uncacheRoot(model);
      shadow.geometry.dispose();
      shadowMat.map?.dispose();
      shadowMat.dispose();
      actorRef.current = null;
    };
  }, [gltf, scene, spec, placement, groundY, seed, sceneLit]);

  useFrame((_, rawDt) => {
    const a = actorRef.current;
    if (!a) return;
    const dt = Math.min(rawDt, 0.05);
    a.clock += dt;

    const play = (name: string | null, timeScale = 1) => {
      const next = name ? (a.actions.get(name) ?? null) : null;
      if (next === a.playing) {
        if (next) next.timeScale = timeScale;
        return;
      }
      a.playing?.fadeOut(FADE);
      if (next) next.reset().setEffectiveTimeScale(timeScale).fadeIn(FADE).play();
      a.playing = next;
    };

    const moving = a.mode === "walk";
    if (a.mode === "idle") {
      a.timer -= dt;
      if (!a.playing && a.actions.size) {
        // Mostly the idle clip; sometimes one of the extras (eating, ...).
        const extra = spec.extraClips.length && a.rng() < 0.3;
        play(extra ? spec.extraClips[Math.floor(a.rng() * spec.extraClips.length)] : spec.idleClip);
      }
      if (a.timer <= 0 && placement.path.length > 1) {
        a.mode = "walk";
        play(spec.walkClip ?? spec.idleClip);
      }
    } else {
      const [tx, tz] = placement.path[a.target];
      const dx = tx - a.root.position.x;
      const dz = tz - a.root.position.z;
      const dist = Math.hypot(dx, dz);
      const want = Math.atan2(dx, dz);
      let diff = want - a.yaw;
      diff = Math.atan2(Math.sin(diff), Math.cos(diff));
      a.yaw += THREE.MathUtils.clamp(diff, -TURN_RATE * dt, TURN_RATE * dt);
      if (Math.abs(diff) < THREE.MathUtils.degToRad(35)) {
        const step = Math.min(dist, spec.walkSpeed * dt * Math.cos(diff));
        a.root.position.x += Math.sin(a.yaw) * step;
        a.root.position.z += Math.cos(a.yaw) * step;
      }
      if (dist < 0.3) {
        a.mode = "idle";
        a.target = (a.target + 1) % placement.path.length;
        const [lo, hi] = placement.idleSeconds ?? [4, 10];
        a.timer = lo + a.rng() * (hi - lo);
        a.playing?.fadeOut(FADE);
        a.playing = null;
      }
    }
    a.root.rotation.y = a.yaw;

    // Feet on the floor: collision mesh where it has one, else the ground plane.
    const g = groundAt(world, a.root.position, 0.6, 1.5, groundY) ?? groundY;
    a.root.position.y += (g - a.root.position.y) * Math.min(1, dt * 8);

    // No walk clip (placeholders): a simple gait so movement isn't a slide.
    // No clips at all: slow breathing while idle.
    if (moving && !spec.walkClip) {
      a.phase += dt * (2 * Math.PI * spec.walkSpeed) / Math.max(0.6, spec.lengthM * 0.45);
      a.model.position.y = Math.abs(Math.sin(a.phase)) * 0.02 * spec.heightM;
      a.model.rotation.z = Math.sin(a.phase) * 0.025;
    } else {
      a.model.position.y += (0 - a.model.position.y) * Math.min(1, dt * 6);
      a.model.rotation.z *= 1 - Math.min(1, dt * 6);
    }
    if (!a.actions.size) a.model.scale.y = 1 + Math.sin(a.clock * 1.7) * 0.006;

    // Shadow: on the floor, pushed away from the sun.
    const flat = Math.hypot(sunDirection.x, sunDirection.z);
    const lean = Math.min(1.2, (flat / Math.max(sunDirection.y, 0.2)) * 0.25) * spec.heightM;
    a.shadow.position.set(
      a.root.position.x - (sunDirection.x / (flat || 1)) * lean,
      g + 0.02,
      a.root.position.z - (sunDirection.z / (flat || 1)) * lean,
    );
    a.shadow.rotation.z = a.yaw;

    a.mixer.update(dt);
  });

  return null;
}

/**
 * All animals placed in the current zone. In a splat zone they bring their own
 * lights (fitted to the splat) and a blob shadow; in the lit mesh world
 * (`sceneLit`) the scene's sun and sky light them and cast real shadows.
 */
export default function Animals({
  placements,
  world,
  groundY,
  lighting,
  sceneLit = false,
}: {
  placements: AnimalPlacement[];
  world: CollisionWorld | null;
  groundY: number;
  lighting: ZoneLighting;
  sceneLit?: boolean;
}) {
  const sunDirection = useMemo(() => new THREE.Vector3(...lighting.sun.direction).normalize(), [lighting]);
  return (
    <>
      {!sceneLit && <ZoneLights lighting={lighting} />}
      {placements.map((p, i) => (
        <AnimalActor
          key={`${p.animal}-${i}`}
          spec={animalSpecs[p.animal]}
          placement={p}
          world={world}
          groundY={groundY}
          sunDirection={sunDirection}
          seed={i * 7919 + 17}
          sceneLit={sceneLit}
        />
      ))}
    </>
  );
}
