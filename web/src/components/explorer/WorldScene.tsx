"use client";

import { Environment, Sky } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { WorldManifest } from "@/lib/world";
import type { BuiltWorld } from "./world/build";

const SHADOW_RANGE = 70; // metres of sun shadow around the viewer
const LOD_INTERVAL = 0.25; // seconds between plant level-of-detail checks
const SHADOW_EVERY = 3; // redraw the sun shadow every n frames (animals move); at once when its area moves
const SUN_INTENSITY = 3.0;
const FOG = { color: new THREE.Color(0.74, 0.81, 0.88), near: 350, far: 2600 };

/**
 * The world built in the browser (world/build.ts) on screen: sky, sun with
 * shadows that follow the viewer, Khronos PBR Neutral tone mapping, and plant
 * levels of detail. Stays mounted while the viewer moves between zones.
 */
export default function WorldScene({
  built,
  manifest,
  detail,
  shadowSize,
  onReady,
  onError,
}: {
  built: BuiltWorld;
  manifest: WorldManifest;
  /** Adaptive quality: plant distance scale (1 = full) and sun-shadow map size (0 = no shadows). */
  detail: number;
  shadowSize: number;
  onReady: () => void;
  onError: (message: string) => void;
}) {
  const get = useThree((s) => s.get);
  const cbRef = useRef({ onReady, onError });
  useEffect(() => {
    cbRef.current = { onReady, onError };
  });
  const lodTimerRef = useRef(0);
  const detailRef = useRef(detail);
  const sunRef = useRef<THREE.DirectionalLight | null>(null);
  const shadowRef = useRef({ x: NaN, z: NaN, frame: 0 });
  const sunDir = useMemo(() => new THREE.Vector3(...manifest.sun.direction).normalize(), [manifest]);
  const skySun = useMemo(() => sunDir.clone().multiplyScalar(100).toArray(), [sunDir]);

  // Renderer for a lit mesh world.
  useEffect(() => {
    const { gl, scene, camera } = get();
    const before = {
      toneMapping: gl.toneMapping,
      exposure: gl.toneMappingExposure,
      shadows: gl.shadowMap.enabled,
      fog: scene.fog,
      near: camera instanceof THREE.PerspectiveCamera ? camera.near : 0.05,
      far: camera instanceof THREE.PerspectiveCamera ? camera.far : 1000,
    };
    gl.toneMapping = THREE.NeutralToneMapping;
    gl.toneMappingExposure = 0.9;
    gl.shadowMap.enabled = true;
    gl.shadowMap.type = THREE.PCFSoftShadowMap;
    scene.fog = new THREE.Fog(FOG.color, FOG.near, FOG.far);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.near = 0.1; // ground layers are cm apart; keep depth precision
      camera.far = 3000;
      camera.updateProjectionMatrix();
    }

    const sun = new THREE.DirectionalLight(new THREE.Color(1, 0.93, 0.84), SUN_INTENSITY);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -SHADOW_RANGE, right: SHADOW_RANGE, top: SHADOW_RANGE, bottom: -SHADOW_RANGE, near: 1, far: 500 });
    sun.shadow.camera.updateProjectionMatrix();
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.04;
    // The world and the sun are still: the shadow map is redrawn only when needed (see useFrame).
    sun.shadow.autoUpdate = false;
    scene.add(sun, sun.target);
    sunRef.current = sun;

    return () => {
      scene.remove(sun, sun.target);
      sun.dispose();
      sunRef.current = null;
      gl.toneMapping = before.toneMapping;
      gl.toneMappingExposure = before.exposure;
      gl.shadowMap.enabled = before.shadows;
      scene.fog = before.fog;
      if (camera instanceof THREE.PerspectiveCamera) {
        camera.near = before.near;
        camera.far = before.far;
        camera.updateProjectionMatrix();
      }
    };
  }, [get]);

  // Adaptive quality: redo the plant levels at once, resize or drop the sun shadows.
  useEffect(() => {
    detailRef.current = detail;
    lodTimerRef.current = LOD_INTERVAL;
  }, [detail]);
  useEffect(() => {
    const sun = sunRef.current;
    if (!sun) return;
    sun.castShadow = shadowSize > 0;
    if (shadowSize > 0 && sun.shadow.mapSize.x !== shadowSize) {
      sun.shadow.mapSize.set(shadowSize, shadowSize);
      sun.shadow.map?.dispose(); // re-created at the new size on the next frame
      sun.shadow.map = null;
    }
    sun.shadow.needsUpdate = true;
  }, [shadowSize]);

  // Put the built world in the scene (billboards are rendered here: they need the renderer).
  useEffect(() => {
    let alive = true;
    const { scene, gl, camera } = get();
    scene.add(built.group);
    (async () => {
      try {
        built.plants.makeBillboards(gl, sunDir);
        built.plants.update(camera.position, detailRef.current);
        await gl.compileAsync(scene, camera);
        if (alive) cbRef.current.onReady();
      } catch (e) {
        if (alive) cbRef.current.onError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
      scene.remove(built.group); // kept for the session (shared by every zone)
    };
  }, [get, built, sunDir]);

  useFrame(({ camera }, dt) => {
    // Sun shadow box centred under the viewer, snapped to 2 m to avoid shimmer.
    const sun = sunRef.current;
    if (sun) {
      const x = Math.round(camera.position.x / 2) * 2;
      const z = Math.round(camera.position.z / 2) * 2;
      const s = shadowRef.current;
      s.frame++;
      if (x !== s.x || z !== s.z) {
        s.x = x;
        s.z = z;
        sun.target.position.set(x, manifest.groundY, z);
        sun.position.set(x, manifest.groundY, z).addScaledVector(sunDir, 200);
        sun.target.updateMatrixWorld();
        sun.shadow.needsUpdate = true;
      } else if (s.frame % SHADOW_EVERY === 0) {
        sun.shadow.needsUpdate = true;
      }
    }
    built.tick(dt);
    lodTimerRef.current += dt;
    if (lodTimerRef.current > LOD_INTERVAL) {
      lodTimerRef.current = 0;
      built.plants.update(camera.position, detailRef.current);
    }
  });

  return (
    <>
      <Sky sunPosition={skySun} distance={2000} turbidity={4} rayleigh={1.2} mieCoefficient={0.004} mieDirectionalG={0.85} />
      <Environment frames={1} resolution={128} environmentIntensity={0.45}>
        <Sky sunPosition={skySun} turbidity={4} rayleigh={1.2} mieCoefficient={0.004} mieDirectionalG={0.85} />
      </Environment>
    </>
  );
}
