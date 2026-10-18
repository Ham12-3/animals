"""2D geometry helpers for the world compiler (plain Python).

Coordinates are local metres around Vantara's centre, x east and y north (the
frame of site.json and layout.json). compile_world.py converts to the
three.js frame only when it writes world.json.
"""

from __future__ import annotations

import math
import random

Point = tuple[float, float]
Poly = list[Point]


def inside(p: Point, poly: Poly) -> bool:
    x, y = p
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def seg_dist(p: Point, a: Point, b: Point) -> float:
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / l2))
    return math.hypot(p[0] - (a[0] + abx * t), p[1] - (a[1] + aby * t))


def edge_dist(p: Point, poly: Poly, closed: bool = True) -> float:
    pts = poly + poly[:1] if closed else poly
    return min(seg_dist(p, a, b) for a, b in zip(pts, pts[1:]))


def line_dist(p: Point, line: Poly) -> float:
    return edge_dist(p, line, closed=False)


def area(poly: Poly) -> float:
    return abs(signed_area(poly))


def signed_area(poly: Poly) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1])) / 2


def centroid(poly: Poly) -> Point:
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def ccw(poly: Poly) -> Poly:
    poly = [tuple(p) for p in poly]
    return poly if signed_area(poly) > 0 else list(reversed(poly))


def bbox(poly: Poly) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def half_width(poly: Poly) -> float:
    x0, y0, x1, y1 = bbox(poly)
    return min(x1 - x0, y1 - y0) / 2


def offset_polygon(poly: Poly, d: float) -> Poly:
    """Shrink a counter-clockwise polygon by d metres (grow if d < 0); mitred, same vertex count."""
    n = len(poly)
    out = []
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = poly[i - 1], poly[i], poly[(i + 1) % n]
        e1 = _unit(bx - ax, by - ay)
        e2 = _unit(cx - bx, cy - by)
        n1 = (-e1[1], e1[0])  # inward (left) normals
        n2 = (-e2[1], e2[0])
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        ml = math.hypot(mx, my)
        m = n1 if ml < 1e-6 else (mx / ml, my / ml)
        k = d / max(0.35, m[0] * n1[0] + m[1] * n1[1])
        out.append((bx + m[0] * k, by + m[1] * k))
    return out


def clip_polygon(subject: Poly, clip: Poly) -> Poly:
    """Sutherland-Hodgman: subject (any simple polygon) clipped to a convex counter-clockwise polygon."""
    out = list(subject)
    for (ax, ay), (bx, by) in zip(clip, clip[1:] + clip[:1]):
        def side(p):
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        src, out = out, []
        for i, cur in enumerate(src):
            prev = src[i - 1]
            sc, sp = side(cur), side(prev)
            if (sc >= 0) != (sp >= 0):
                t = sp / (sp - sc)
                out.append((prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t))
            if sc >= 0:
                out.append(cur)
        if not out:
            break
    return out


def rect_axes(pts: Poly):
    """Centre, long-axis unit vector, long length, short length of a 4-point rectangle."""
    a, b, _, d = pts
    e1 = (b[0] - a[0], b[1] - a[1])
    e2 = (d[0] - a[0], d[1] - a[1])
    c = ((a[0] + pts[2][0]) / 2, (a[1] + pts[2][1]) / 2)
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if l1 >= l2:
        return c, (e1[0] / l1, e1[1] / l1), l1, l2
    return c, (e2[0] / l2, e2[1] / l2), l2, l1


def scatter(rng: random.Random, region: Poly, spacing: float, count: int, keep_out) -> list[Point]:
    """Seeded dart throwing inside `region`, at least `spacing` apart, rejected by keep_out(p)."""
    x0, y0, x1, y1 = bbox(region)
    pts: list[Point] = []
    tries = 0
    s2 = spacing * spacing
    while len(pts) < count and tries < count * 60:
        tries += 1
        p = (rng.uniform(x0, x1), rng.uniform(y0, y1))
        if not inside(p, region) or keep_out(p):
            continue
        if any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < s2 for q in pts):
            continue
        pts.append(p)
    return pts


class Obstacles:
    """Polygons with clearances, with a bounding-box pre-check (the scatter calls this a lot)."""

    def __init__(self, items: list[tuple[Poly, float]], solid: bool = True):
        self.items = [(poly, clear, bbox(poly)) for poly, clear in items]
        self.solid = solid  # points inside the polygon count as blocked

    def hit(self, p: Point, extra: float = 0.0) -> bool:
        for poly, clear, (x0, y0, x1, y1) in self.items:
            c = clear + extra
            if p[0] < x0 - c or p[0] > x1 + c or p[1] < y0 - c or p[1] > y1 + c:
                continue
            if (self.solid and inside(p, poly)) or edge_dist(p, poly) < c:
                return True
        return False


class Lines:
    """Polylines with clearances (roads), with a bounding-box pre-check."""

    def __init__(self, items: list[tuple[Poly, float]]):
        self.items = [(line, clear, bbox(line)) for line, clear in items]

    def hit(self, p: Point) -> bool:
        for line, clear, (x0, y0, x1, y1) in self.items:
            if p[0] < x0 - clear or p[0] > x1 + clear or p[1] < y0 - clear or p[1] > y1 + clear:
                continue
            if line_dist(p, line) < clear:
                return True
        return False


def _unit(x: float, y: float) -> Point:
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-9 else (0.0, 0.0)
