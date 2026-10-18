import * as THREE from "three";
import type { WorldManifest } from "@/lib/world";

export type V3 = [number, number, number];
type XZ = [number, number];
type RGBA = [number, number, number, number];

/** Which way a face should point: up, away from a point, or towards a point. */
export type Orient = "up" | { away: V3 } | { toward: V3 };

/**
 * Collects flat-shaded triangles for one material. Each face is turned to point
 * the way `orient` says (data from the compiler carries no winding guarantees),
 * and gets world-space UVs (box projection on its normal) divided by the
 * material's tile size, so every texture repeats at its real size however the
 * surface is cut.
 */
export class GeometryBuilder {
  private pos: number[] = [];
  private nrm: number[] = [];
  private col: number[] | null;

  /** `color`: give every vertex a colour attribute (RGBA), this one unless a face brings its own. */
  constructor(private color: RGBA | null = null) {
    this.col = color ? [] : null;
  }

  get triangles() {
    return this.pos.length / 9;
  }

  tri(a: V3, b: V3, c: V3, orient?: Orient, colors?: [RGBA, RGBA, RGBA]) {
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]; // prettier-ignore
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]; // prettier-ignore
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz);
    if (len < 1e-10) return;
    nx /= len;
    ny /= len;
    nz /= len;
    let flip = false;
    if (orient === "up") flip = ny < 0;
    else if (orient) {
      const p = "away" in orient ? orient.away : orient.toward;
      const dot = ((a[0] + b[0] + c[0]) / 3 - p[0]) * nx + ((a[1] + b[1] + c[1]) / 3 - p[1]) * ny + ((a[2] + b[2] + c[2]) / 3 - p[2]) * nz;
      flip = "away" in orient ? dot < 0 : dot > 0;
    }
    const verts = flip ? [a, c, b] : [a, b, c];
    const cols = colors && (flip ? [colors[0], colors[2], colors[1]] : colors);
    if (flip) {
      nx = -nx;
      ny = -ny;
      nz = -nz;
    }
    verts.forEach((v, i) => {
      this.pos.push(v[0], v[1], v[2]);
      this.nrm.push(nx, ny, nz);
      if (this.col) this.col.push(...(cols?.[i] ?? this.color!));
    });
  }

  quad(a: V3, b: V3, c: V3, d: V3, orient?: Orient, colors?: [RGBA, RGBA, RGBA, RGBA]) {
    this.tri(a, b, c, orient, colors && [colors[0], colors[1], colors[2]]);
    this.tri(a, c, d, orient, colors && [colors[0], colors[2], colors[3]]);
  }

  /** Positions only (collision). */
  positions() {
    return this.pos;
  }

  build(tile = 1): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    const n = this.pos.length / 3;
    const uv = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
      const [x, y, z] = [this.pos[3 * i], this.pos[3 * i + 1], this.pos[3 * i + 2]];
      const [ax, ay, az] = [Math.abs(this.nrm[3 * i]), Math.abs(this.nrm[3 * i + 1]), Math.abs(this.nrm[3 * i + 2])];
      const [u, v] = ay >= ax && ay >= az ? [x, -z] : ax >= az ? [z, y] : [x, y];
      uv[2 * i] = u / tile;
      uv[2 * i + 1] = v / tile;
    }
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(this.nrm, 3));
    g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    if (this.col) g.setAttribute("color", new THREE.Float32BufferAttribute(this.col, 4));
    g.computeBoundingSphere();
    return g;
  }
}

const v2 = (p: XZ) => new THREE.Vector2(p[0], p[1]);
const centre = (pts: XZ[]): XZ => [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];

/** Flat polygon with holes at height y (Earcut via ShapeUtils), facing up. */
export function polygon(b: GeometryBuilder, outer: XZ[], holes: XZ[][], y: number, color?: RGBA) {
  const all = [outer, ...holes].flat();
  const faces = THREE.ShapeUtils.triangulateShape(outer.map(v2), holes.map((h) => h.map(v2)));
  for (const [i, j, k] of faces) {
    const p = (q: XZ): V3 => [q[0], y, q[1]];
    b.tri(p(all[i]), p(all[j]), p(all[k]), "up", color && [color, color, color]);
  }
}

/** Flat strip of a width along a polyline (mitred joints, limited at sharp turns). */
export function ribbon(b: GeometryBuilder, points: XZ[], width: number, y: number) {
  if (points.length < 2) return;
  const half = width / 2;
  const left: V3[] = [];
  const right: V3[] = [];
  points.forEach((cur, i) => {
    const dIn = i > 0 ? norm([cur[0] - points[i - 1][0], cur[1] - points[i - 1][1]]) : null;
    const dOut = i < points.length - 1 ? norm([points[i + 1][0] - cur[0], points[i + 1][1] - cur[1]]) : null;
    let d = dIn && dOut ? norm([dIn[0] + dOut[0], dIn[1] + dOut[1]]) : (dIn ?? dOut)!;
    if (!d) d = (dOut ?? dIn)!;
    const n: XZ = [-d[1], d[0]];
    let scale = 1;
    if (dIn && dOut) scale = Math.min(3, 1 / Math.max(0.2, n[0] * -dIn[1] + n[1] * dIn[0]));
    left.push([cur[0] + n[0] * half * scale, y, cur[1] + n[1] * half * scale]);
    right.push([cur[0] - n[0] * half * scale, y, cur[1] - n[1] * half * scale]);
  });
  for (let i = 0; i < points.length - 1; i++) b.quad(left[i], right[i], right[i + 1], left[i + 1], "up");
}

function norm(v: XZ): XZ {
  const l = Math.hypot(v[0], v[1]);
  return l < 1e-9 ? [1, 0] : [v[0] / l, v[1] / l];
}

/** Vertical extrusion of a footprint: walls facing out, a top cap. */
export function prism(b: GeometryBuilder, footprint: XZ[], y0: number, y1: number) {
  const c = centre(footprint);
  const mid: V3 = [c[0], (y0 + y1) / 2, c[1]];
  footprint.forEach((p, i) => {
    const q = footprint[(i + 1) % footprint.length];
    b.quad([p[0], y0, p[1]], [q[0], y0, q[1]], [q[0], y1, q[1]], [p[0], y1, p[1]], { away: mid });
  });
  polygon(b, footprint, [], y1);
}

/** Pitched roof: two slopes and two gable ends. */
export function gable(b: GeometryBuilder, eave: XZ[], ridge: XZ[], y: number, rise: number) {
  const [e0, e1, e2, e3] = eave.map((p): V3 => [p[0], y, p[1]]);
  const [r0, r1] = ridge.map((p): V3 => [p[0], y + rise, p[1]]);
  const c = centre(eave);
  const inside: V3 = [c[0], y - rise, c[1]];
  b.quad(e0, e1, r1, r0, { away: inside });
  b.quad(e3, r0, r1, e2, { away: inside });
  b.tri(e0, r0, e3, { away: inside });
  b.tri(e1, e2, r1, { away: inside });
}

/** Box [cx, cz, rot, length, depth, y0, y1] (rotation about y, length along the rotated x axis). */
export function box(b: GeometryBuilder, [cx, cz, rot, w, d, y0, y1]: number[]) {
  const ax: XZ = [Math.cos(rot), -Math.sin(rot)]; // local x
  const az: XZ = [Math.sin(rot), Math.cos(rot)]; // local z
  const corner = (sx: number, sz: number, y: number): V3 => [
    cx + ax[0] * sx * (w / 2) + az[0] * sz * (d / 2),
    y,
    cz + ax[1] * sx * (w / 2) + az[1] * sz * (d / 2),
  ];
  const mid: V3 = [cx, (y0 + y1) / 2, cz];
  const ring = [corner(-1, -1, 0), corner(1, -1, 0), corner(1, 1, 0), corner(-1, 1, 0)];
  const at = (p: V3, y: number): V3 => [p[0], y, p[2]];
  for (let i = 0; i < 4; i++) {
    const p = ring[i];
    const q = ring[(i + 1) % 4];
    b.quad(at(p, y0), at(q, y0), at(q, y1), at(p, y1), { away: mid });
  }
  b.quad(at(ring[0], y1), at(ring[1], y1), at(ring[2], y1), at(ring[3], y1), { away: mid });
  b.quad(at(ring[0], y0), at(ring[1], y0), at(ring[2], y0), at(ring[3], y0), { away: mid });
}

/** Pond or lake: bank rings sloping to a flat bed, and the water surface graded shallow -> deep. */
export function basin(bank: GeometryBuilder, water: GeometryBuilder, data: WorldManifest["basins"][number]) {
  const rings = data.bank.rings;
  for (let r = 0; r < rings.length - 1; r++) {
    const [a, ya] = rings[r];
    const [c, yc] = rings[r + 1];
    for (let i = 0; i < a.length; i++) {
      const j = (i + 1) % a.length;
      bank.quad([a[i][0], ya, a[i][1]], [a[j][0], ya, a[j][1]], [c[j][0], yc, c[j][1]], [c[i][0], yc, c[i][1]], "up");
    }
  }
  const [bed, yb] = rings[rings.length - 1];
  polygon(bank, bed, [], yb);
  const w = data.water.rings;
  const y = data.water.y;
  for (let r = 0; r < w.length - 1; r++) {
    const [a, ca] = w[r];
    const [c, cc] = w[r + 1];
    for (let i = 0; i < a.length; i++) {
      const j = (i + 1) % a.length;
      water.quad([a[i][0], y, a[i][1]], [a[j][0], y, a[j][1]], [c[j][0], y, c[j][1]], [c[i][0], y, c[i][1]], "up", [ca, ca, cc, cc]);
    }
  }
  const [inner, ci] = w[w.length - 1];
  polygon(water, inner, [], y, ci);
}

/** Collision only: a wall along a shoreline so nobody walks into the water. */
export function shoreWall(b: GeometryBuilder, ring: XZ[], y0: number, y1: number) {
  ring.forEach((p, i) => {
    const q = ring[(i + 1) % ring.length];
    b.quad([p[0], y0, p[1]], [q[0], y0, q[1]], [q[0], y1, q[1]], [p[0], y1, p[1]]);
  });
}
