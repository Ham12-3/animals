"""Convert an OpenStreetMap extract around Vantara into local-metre geometry.

    uv run --project pipeline python world/scripts/osm_to_json.py

Reads world/data/vantara_area.osm (© OpenStreetMap contributors, ODbL) and
writes world/data/site.json: the Vantara outline, roads, water and buildings
in metres around the outline's centre (X = east, Y = north), cropped to a
square of +-RADIUS metres.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "data" / "vantara_area.osm"
OUT = HERE / "data" / "site.json"
VANTARA_WAY = "1159186268"  # amenity=animal_shelter, name=Vantara
RADIUS = 1500.0

ROAD_WIDTH = {"tertiary": 7.0, "unclassified": 5.5, "residential": 5.0, "service": 4.0, "track": 3.0}
WATERWAY_WIDTH = {"river": 12.0, "stream": 4.0, "ditch": 2.0}


def load():
    root = ET.parse(SRC).getroot()
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.findall("node")}
    ways = {}
    for w in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
        refs = [nd.get("ref") for nd in w.findall("nd")]
        ways[w.get("id")] = (tags, [nodes[r] for r in refs if r in nodes])
    rels = []
    for r in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in r.findall("tag")}
        members = [(m.get("type"), m.get("ref"), m.get("role")) for m in r.findall("member")]
        rels.append((r.get("id"), tags, members))
    return ways, rels


def projector(lon0: float, lat0: float):
    kx = 111_320.0 * math.cos(math.radians(lat0))
    ky = 110_540.0

    def proj(pts):
        return [[round((lon - lon0) * kx, 2), round((lat - lat0) * ky, 2)] for lon, lat in pts]

    return proj


def clip_polyline(pts, r):
    """Keep the parts of a polyline inside the square |x|,|y| <= r (Liang-Barsky per segment)."""
    out, cur = [], []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        t0, t1, dx, dy = 0.0, 1.0, x1 - x0, y1 - y0
        ok = True
        for p, q in ((-dx, x0 + r), (dx, r - x0), (-dy, y0 + r), (dy, r - y0)):
            if p == 0:
                if q < 0:
                    ok = False
                    break
            else:
                t = q / p
                if p < 0:
                    t0 = max(t0, t)
                else:
                    t1 = min(t1, t)
        if not ok or t0 > t1:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        a = [round(x0 + t0 * dx, 2), round(y0 + t0 * dy, 2)]
        b = [round(x0 + t1 * dx, 2), round(y0 + t1 * dy, 2)]
        if not cur or cur[-1] != a:
            if len(cur) > 1:
                out.append(cur)
            cur = [a]
        cur.append(b)
        if t1 < 1.0:
            out.append(cur)
            cur = []
    if len(cur) > 1:
        out.append(cur)
    return out


def inside(pts, r):
    return any(abs(x) <= r and abs(y) <= r for x, y in pts)


def main() -> None:
    ways, rels = load()
    outline_ll = ways[VANTARA_WAY][1]
    lon0 = sum(p[0] for p in outline_ll) / len(outline_ll)
    lat0 = sum(p[1] for p in outline_ll) / len(outline_ll)
    proj = projector(lon0, lat0)

    site = {
        "attribution": "Map data © OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
        "note": "Artistic interpretation: only the outline, roads, water and generic buildings come from map data.",
        "origin": {"lon": lon0, "lat": lat0},
        "radius": RADIUS,
        "outline": proj(outline_ll[:-1] if outline_ll[0] == outline_ll[-1] else outline_ll),  # open ring
        "roads": [], "waterways": [], "water": [], "buildings": [], "rail": [],
    }  # fmt: skip

    for wid, (tags, pts) in ways.items():
        if len(pts) < 2 or wid == VANTARA_WAY:
            continue
        xy = proj(pts)
        if "highway" in tags and tags["highway"] in ROAD_WIDTH:
            for part in clip_polyline(xy, RADIUS):
                site["roads"].append({"kind": tags["highway"], "width": ROAD_WIDTH[tags["highway"]], "points": part})
        elif tags.get("waterway") in WATERWAY_WIDTH:
            for part in clip_polyline(xy, RADIUS):
                site["waterways"].append({"kind": tags["waterway"], "width": WATERWAY_WIDTH[tags["waterway"]], "points": part})
        elif tags.get("natural") == "water" and xy[0] == xy[-1] and inside(xy, RADIUS * 1.5):
            site["water"].append(xy[:-1])
        elif "building" in tags and xy[0] == xy[-1] and inside(xy, RADIUS):
            levels = float(tags.get("building:levels", 0) or 0)
            site["buildings"].append({
                "kind": tags["building"],
                "height": float(tags.get("height", 0) or 0) or (3.2 * levels if levels else 6.0),
                "points": xy[:-1],
            })  # fmt: skip

    for rid, tags, members in rels:
        if tags.get("natural") == "water":
            for mtype, ref, role in members:
                if mtype == "way" and role == "outer" and ref in ways:
                    xy = proj(ways[ref][1])
                    if len(xy) > 3 and xy[0] == xy[-1] and inside(xy, RADIUS * 1.5):
                        site["water"].append(xy[:-1])
        if tags.get("railway") or tags.get("route") == "railway" or "railway" in tags.get("name", "").lower():
            for mtype, ref, role in members:
                if mtype == "way" and ref in ways and len(ways[ref][1]) > 1:
                    site["rail"] += clip_polyline(proj(ways[ref][1]), RADIUS)

    OUT.write_text(json.dumps(site), encoding="utf-8")
    xs = [p[0] for p in site["outline"]]
    ys = [p[1] for p in site["outline"]]
    print(f"origin {lat0:.6f}N {lon0:.6f}E | outline {len(site['outline'])} pts, "
          f"{max(xs) - min(xs):.0f} m E-W x {max(ys) - min(ys):.0f} m N-S")  # fmt: skip
    for k in ("roads", "waterways", "water", "buildings", "rail"):
        print(f"  {k}: {len(site[k])}")
    print("->", OUT)


if __name__ == "__main__":
    main()
