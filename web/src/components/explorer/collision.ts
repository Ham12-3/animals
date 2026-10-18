import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { type ExtendedTriangle, MeshBVH } from "three-mesh-bvh";

/**
 * The zone's invisible collision mesh (a GLB, or triangles built in the
 * browser) with a BVH for fast capsule and ray queries.
 */
export class CollisionWorld {
  readonly bvh: MeshBVH;

  private constructor(readonly geometry: THREE.BufferGeometry) {
    this.bvh = new MeshBVH(geometry);
  }

  static async fromGlb(buffer: ArrayBuffer): Promise<CollisionWorld> {
    const gltf = await new GLTFLoader().parseAsync(buffer, "");
    let parts: THREE.BufferGeometry[] = [];
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        const g = (o.geometry as THREE.BufferGeometry).clone();
        g.applyMatrix4(o.matrixWorld);
        for (const name of Object.keys(g.attributes)) if (name !== "position") g.deleteAttribute(name);
        parts.push(g);
      }
    });
    if (!parts.length) throw new Error("collision mesh is empty");
    // mergeGeometries needs all-indexed or all-non-indexed input.
    if (parts.some((g) => !g.index)) parts = parts.map((g) => (g.index ? g.toNonIndexed() : g));
    const merged = parts.length === 1 ? parts[0] : mergeGeometries(parts, false);
    if (!merged) throw new Error("could not merge collision meshes");
    return new CollisionWorld(merged);
  }

  /** From a triangle soup (x, y, z per vertex), e.g. the world built in the browser. */
  static fromPositions(positions: Float32Array): CollisionWorld {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return new CollisionWorld(g);
  }

  /** First hit along a ray, or null. */
  raycast(origin: THREE.Vector3, dir: THREE.Vector3, far: number): THREE.Intersection | null {
    _ray.origin.copy(origin);
    _ray.direction.copy(dir);
    return this.bvh.raycastFirst(_ray, THREE.DoubleSide, 0, far);
  }

  /** Height of the ground under ``p`` within ``maxDrop`` below ``p.y + lift``, or null. */
  groundBelow(p: THREE.Vector3, lift: number, maxDrop: number): number | null {
    _v1.set(p.x, p.y + lift, p.z);
    const hit = this.raycast(_v1, DOWN, lift + maxDrop);
    return hit ? hit.point.y : null;
  }

  /**
   * Push a capsule (segment ``start``-``end``, radius ``r``) out of the mesh.
   * Moves the segment in place; returns true if anything was touched.
   */
  resolveCapsule(segment: THREE.Line3, r: number): boolean {
    _box.makeEmpty();
    _box.expandByPoint(segment.start);
    _box.expandByPoint(segment.end);
    _box.min.addScalar(-r);
    _box.max.addScalar(r);
    let touched = false;
    this.bvh.shapecast({
      intersectsBounds: (box) => box.intersectsBox(_box),
      intersectsTriangle: (tri: ExtendedTriangle) => {
        const dist = tri.closestPointToSegment(segment, _triPoint, _capPoint);
        if (dist < r) {
          const push = _capPoint.sub(_triPoint).normalize().multiplyScalar(r - dist);
          segment.start.add(push);
          segment.end.add(push);
          touched = true;
        }
      },
    });
    return touched;
  }

  dispose() {
    this.geometry.dispose();
  }
}

const DOWN = new THREE.Vector3(0, -1, 0);
const _ray = new THREE.Ray();
const _box = new THREE.Box3();
const _v1 = new THREE.Vector3();
const _triPoint = new THREE.Vector3();
const _capPoint = new THREE.Vector3();
