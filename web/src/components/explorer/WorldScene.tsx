"use client";

import { Environment, Sky } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { type WorldManifest, worldBase } from "@/lib/world";

const SHADOW_RANGE = 70; // metres of sun shadow around the viewer
const LOD_INTERVAL = 0.4; // seconds between plant level-of-detail updates
const SUN_INTENSITY = 3.0;
const FOG = { color: new THREE.Color(0.74, 0.81, 0.88), near: 350, far: 2600 };
/** Beyond this, small plants are a few pixels: not drawn at all (trees always are). */
const CULL_DISTANCE: Record<string, number> = { shrub: 130, rock: 150, bush: 220, tree: Infinity };

interface PlantSet {
  /** Instanced meshes per level of detail (one per primitive). */
  levels: THREE.InstancedMesh[][];
  matrices: THREE.Matrix4[];
  xz: Float32Array;
  /** Squared hand-over distances between levels. */
  lodDistanceSq: number[];
  cullDistanceSq: number;
}

/** Billboards are pre-lit renders of the plant: show them as they are, cut out. */
function billboardMaterial(m: THREE.MeshStandardMaterial) {
  return new THREE.MeshBasicMaterial({
    name: m.name,
    map: m.map,
    alphaTest: 0.5,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
}

/** Plant leaves are alpha cards: cut out (not blended) so they sort and cast shadows. */
function prepareFoliage(material: THREE.Material) {
  const m = material as THREE.MeshStandardMaterial;
  if (m.transparent || m.alphaTest > 0 || /leaves|twigs/i.test(m.name)) {
    m.transparent = false;
    m.alphaTest = 0.5;
    m.depthWrite = true;
    m.side = THREE.DoubleSide;
  }
}

/** Shadows, draw order of coplanar ground layers, and the see-through chain-link fences. */
function prepareStatic(root: THREE.Object3D, manifest: WorldManifest, doubleSided: boolean) {
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    o.castShadow = true;
    o.receiveShadow = true;
    for (const material of Array.isArray(o.material) ? o.material : [o.material]) {
      const m = material as THREE.MeshStandardMaterial;
      const layer = manifest.depthLayers[m.name];
      if (layer !== undefined) {
        // Ground layers sit 1-6 cm apart: offset them so distant ones don't flicker.
        m.polygonOffset = true;
        m.polygonOffsetFactor = -layer;
        m.polygonOffsetUnits = -layer * 2;
        o.castShadow = false;
      }
      if (/water$/.test(m.name)) {
        // Graded water (vertex colour + alpha): see the bank through the shallows.
        m.transparent = true;
        m.depthWrite = false;
        o.castShadow = false;
        o.renderOrder = 1;
      } else if (m.name.endsWith("Blockout: mesh")) {
        m.transparent = true;
        m.depthWrite = false;
        m.side = THREE.DoubleSide;
        o.castShadow = false;
      } else if (doubleSided) {
        m.side = THREE.DoubleSide;
      }
    }
  });
}

/** One InstancedMesh per plant variant, primitive and level of detail. */
function buildPlants(root: THREE.Object3D, plants: NonNullable<WorldManifest["plants"]>) {
  root.updateMatrixWorld(true);
  const group = new THREE.Group();
  const sets: PlantSet[] = [];
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  for (const [name, variant] of Object.entries(plants.variants)) {
    const n = variant.instances.length;
    const matrices = variant.instances.map(([x, y, z, yaw, s]) =>
      new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), q.setFromAxisAngle(up, yaw).clone(), new THREE.Vector3(s, s, s)),
    );
    const xz = new Float32Array(variant.instances.flatMap(([x, , z]) => [x, z]));
    const lod = (level: number) => {
      const node = root.getObjectByName(`${name}|lod${level}`);
      const out: THREE.InstancedMesh[] = [];
      node?.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        const geometry = (o.geometry as THREE.BufferGeometry).clone().applyMatrix4(o.matrixWorld);
        const source = Array.isArray(o.material) ? o.material : [o.material];
        const billboard = source.some((m) => m.name.startsWith("Billboard"));
        const material = billboard
          ? source.map((m) => billboardMaterial(m as THREE.MeshStandardMaterial))
          : (source.forEach(prepareFoliage), o.material);
        const im = new THREE.InstancedMesh(geometry, Array.isArray(o.material) || billboard ? material : o.material, n);
        im.count = 0;
        im.frustumCulled = false;
        im.castShadow = level < 2 && !billboard; // the shadow range covers the two nearer levels
        im.receiveShadow = !billboard;
        out.push(im);
        group.add(im);
      });
      return out;
    };
    sets.push({
      levels: variant.faces.map((_, i) => lod(i)),
      matrices,
      xz,
      lodDistanceSq: variant.lodDistances.map((d) => d * d),
      cullDistanceSq: (CULL_DISTANCE[variant.role] ?? Infinity) ** 2,
    });
  }
  return { group, sets };
}

function updateLods(sets: PlantSet[], eye: THREE.Vector3) {
  for (const s of sets) {
    const counts = s.levels.map(() => 0);
    for (let i = 0; i < s.matrices.length; i++) {
      const dx = s.xz[2 * i] - eye.x;
      const dz = s.xz[2 * i + 1] - eye.z;
      const d2 = dx * dx + dz * dz;
      if (d2 > s.cullDistanceSq) continue;
      let level = s.lodDistanceSq.findIndex((limit) => d2 < limit);
      if (level < 0) level = s.levels.length - 1;
      for (const m of s.levels[level]) m.setMatrixAt(counts[level], s.matrices[i]);
      counts[level]++;
    }
    s.levels.forEach((meshes, level) => {
      for (const m of meshes) {
        m.count = counts[level];
        m.instanceMatrix.needsUpdate = true;
      }
    });
  }
}

function disposeTree(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((o) => {
    if (o instanceof THREE.Mesh) {
      geometries.add(o.geometry);
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) materials.add(m);
    }
  });
  for (const g of geometries) g.dispose();
  for (const m of materials) {
    for (const v of Object.values(m)) if (v instanceof THREE.Texture) v.dispose();
    m.dispose();
  }
}

/**
 * The Blender-built world (world/scripts/export_web.py): static parts, instanced
 * plants with two levels of detail, sky, sun with shadows that follow the viewer,
 * and Khronos PBR Neutral tone mapping like the Blender renders. Stays mounted
 * while the viewer moves between zones of the same world.
 */
export default function WorldScene({
  url,
  manifest,
  onProgress,
  onReady,
  onError,
}: {
  url: string;
  manifest: WorldManifest;
  onProgress: (p: number) => void;
  onReady: () => void;
  onError: (message: string) => void;
}) {
  const get = useThree((s) => s.get);
  const cbRef = useRef({ onProgress, onReady, onError });
  useEffect(() => {
    cbRef.current = { onProgress, onReady, onError };
  });
  const plantsRef = useRef<PlantSet[]>([]);
  const lodTimerRef = useRef(0);
  const sunRef = useRef<THREE.DirectionalLight | null>(null);
  const sunDir = useMemo(() => new THREE.Vector3(...manifest.sun.direction).normalize(), [manifest]);
  const skySun = useMemo(() => sunDir.clone().multiplyScalar(100).toArray(), [sunDir]);

  // Renderer for a lit mesh world (splat zones use flat, untone-mapped output).
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

  // Load every part (they share texture files, so the browser fetches each once).
  useEffect(() => {
    let alive = true;
    const { scene, gl, camera } = get();
    const manager = new THREE.LoadingManager();
    manager.onProgress = (_url, loaded, total) => {
      if (alive) cbRef.current.onProgress(total ? loaded / total : -1);
    };
    const draco = new DRACOLoader(manager).setDecoderPath("/draco/");
    const loader = new GLTFLoader(manager).setDRACOLoader(draco);
    const base = worldBase(url);
    const group = new THREE.Group();
    group.name = "vantara-world";
    const files = manifest.parts.map((p) => p.file);
    if (manifest.plants) files.push(manifest.plants.file);

    Promise.all(files.map((f) => loader.loadAsync(base + f)))
      .then(async (gltfs) => {
        if (!alive) {
          for (const g of gltfs) disposeTree(g.scene);
          return;
        }
        manifest.parts.forEach((p, i) => {
          prepareStatic(gltfs[i].scene, manifest, p.id !== "site");
          group.add(gltfs[i].scene);
        });
        if (manifest.plants) {
          const plantGltf = gltfs[gltfs.length - 1];
          const { group: plantGroup, sets } = buildPlants(plantGltf.scene, manifest.plants);
          // The instances use cloned geometry (materials are shared): free the source buffers.
          plantGltf.scene.traverse((o) => {
            if (o instanceof THREE.Mesh) (o.geometry as THREE.BufferGeometry).dispose();
          });
          group.add(plantGroup);
          plantsRef.current = sets;
          updateLods(sets, camera.position);
        }
        scene.add(group);
        await gl.compileAsync(scene, camera);
        if (alive) cbRef.current.onReady();
      })
      .catch((e: unknown) => {
        if (alive) cbRef.current.onError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      alive = false;
      scene.remove(group);
      disposeTree(group);
      plantsRef.current = [];
      draco.dispose();
    };
  }, [get, url, manifest]);

  useFrame(({ camera }, dt) => {
    // Sun shadow box centred under the viewer, snapped to 2 m to avoid shimmer.
    const sun = sunRef.current;
    if (sun) {
      const x = Math.round(camera.position.x / 2) * 2;
      const z = Math.round(camera.position.z / 2) * 2;
      sun.target.position.set(x, manifest.groundY, z);
      sun.position.set(x, manifest.groundY, z).addScaledVector(sunDir, 200);
      sun.target.updateMatrixWorld();
    }
    lodTimerRef.current += dt;
    if (lodTimerRef.current > LOD_INTERVAL && plantsRef.current.length) {
      lodTimerRef.current = 0;
      updateLods(plantsRef.current, camera.position);
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
