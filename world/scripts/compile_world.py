"""Compile Vantara's world (artistic interpretation) into one data file for the browser.

    uv run --project pipeline python world/scripts/compile_world.py

Reads world/data/site.json (OpenStreetMap outline, roads, water, railway) and
world/data/layout.json (the designed zones) and writes:

    world/publish/world/world.json      every surface, building, fence, water
                                        basin, plant and animal as simple
                                        primitives the explorer turns into meshes
    world/publish/<zone>/<zone>.json    per-zone metadata (spawn, bounds, flyover)
    web/public/map/overview.svg         the overview map, drawn from the same data
    zones.json                          zone positions on that map (map.image too)

Everything is deterministic (seeded). Positions in world.json use the three.js
frame: x east, y up, z south (z = -north); 2D outlines are [x, z] pairs.

Primitives (all metres):
  surfaces  flat polygons at height y, with holes (ground layers, yards, paths)
  ribbons   strips of a width along a polyline (roads, railway, streams)
  prisms    vertical extrusions of a footprint (building walls, flat roofs)
  gables    pitched roofs: four eave corners, two ridge ends, eave height, rise
  boxes     per material, [cx, cz, rot, w, d, y0, y1]: centre, rotation about
            y (radians), length along the rotated x axis, depth, bottom, top
  basins    ponds and lakes: bank rings from the shore down, a bed, a water
            surface graded shallow -> deep (vertex colour + opacity)
  quads     per material, [[x, y, z] x 4] (the hydrotherapy pool shell)
  plants    model variants and their instances [x, y, z, yaw, scale]
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import overview_map  # noqa: E402
from worldgeo import (  # noqa: E402
    Lines,
    Obstacles,
    area,
    bbox,
    ccw,
    centroid,
    clip_polygon,
    edge_dist,
    half_width,
    inside,
    offset_polygon,
    rect_axes,
    scatter,
)

WORLD = HERE.parent
REPO = WORLD.parent
SITE = json.loads((WORLD / "data" / "site.json").read_text(encoding="utf-8"))
LAYOUT = json.loads((WORLD / "data" / "layout.json").read_text(encoding="utf-8"))
MODELS = WORLD / "assets" / "polyhaven" / "models"
OUT = WORLD / "publish"
MAP_SVG = REPO / "web" / "public" / "map" / "overview.svg"
ZONES_JSON = REPO / "zones.json"

SEED = 17
STOREY = 3.6
EYE_HEIGHT = 1.6
GROUND_SIZE = 14_000.0  # past every mapped lake (the eastern one reaches 5.8 km), so each gets its hole
WHEN = datetime(2026, 3, 15, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))  # sun: 10:00 IST, 15 March

# Layer heights (m). The ground layers sit a few cm apart; the explorer also
# offsets their depth by material "layer" so distant ones don't flicker.
GROUND_Y, SITE_Y = 0.0, 0.12
WATER_Y, ROAD_Y, RAIL_Y = 0.10, 0.18, 0.22
SURFACE_Y = {"grass_wild": 0.135, "sand": 0.14, "asphalt": 0.145, "paving": 0.15}
WALL_HEIGHT, WALL_THICKNESS = 2.2, 0.3

# Materials. color is linear RGB; texture is a Poly Haven set (colour, normal maps)
# tiled every `tile` metres in world space; tint multiplies the texture.
MATERIALS = {
    "ground_scrub": dict(texture="dry_ground_01", tile=5.0, tint=[0.86, 0.84, 0.8], color=[0.36, 0.29, 0.2], roughness=0.95, layer=0),
    "site_ground": dict(texture="dry_ground_01", tile=4.0, tint=[1.0, 0.97, 0.92], color=[0.4, 0.32, 0.22], roughness=0.95, layer=1),
    "woodland_floor": dict(texture="dry_ground_01", tile=4.0, tint=[0.66, 0.57, 0.48], color=[0.26, 0.19, 0.12], roughness=0.95, layer=2),
    "sand": dict(texture="sand_01", tile=3.0, tint=[1.0, 1.0, 1.0], color=[0.66, 0.55, 0.38], roughness=0.95, layer=2),
    "grass_wild": dict(texture="withered_grass", tile=3.0, tint=[1.0, 1.0, 1.0], color=[0.3, 0.3, 0.14], roughness=0.95, layer=2),
    "asphalt": dict(texture="asphalt_02", tile=6.0, tint=[1.0, 1.0, 1.0], color=[0.09, 0.09, 0.09], roughness=0.85, layer=3),
    "paving": dict(texture="red_sandstone_pavement", tile=3.0, tint=[1.0, 1.0, 1.0], color=[0.6, 0.5, 0.42], roughness=0.85, layer=4),
    "wet_bank": dict(texture="brown_mud_02", tile=3.0, tint=[0.75, 0.72, 0.7], color=[0.18, 0.13, 0.09], roughness=0.5, layer=3),
    "mud": dict(texture="brown_mud_02", tile=3.0, tint=[0.8, 0.8, 0.8], color=[0.22, 0.16, 0.11], roughness=0.45, layer=5),
    "road_asphalt": dict(texture="asphalt_02", tile=6.0, tint=[1.0, 1.0, 1.0], color=[0.09, 0.09, 0.09], roughness=0.85, layer=6),
    "road_concrete": dict(color=[0.5, 0.48, 0.44], roughness=0.85, layer=6),
    "road_dirt": dict(color=[0.4, 0.31, 0.21], roughness=0.95, layer=6),
    "rail": dict(color=[0.22, 0.21, 0.2], roughness=0.95, layer=6),
    "stream": dict(color=[0.05, 0.09, 0.08], roughness=0.1, layer=1),
    "building": dict(texture="yellow_plaster", tile=2.5, tint=[1.0, 1.0, 1.0], color=[0.62, 0.57, 0.48], roughness=0.85),
    "hospital": dict(normal="white_plaster_02", tile=4.0, color=[0.78, 0.78, 0.76], roughness=0.8),
    "wall": dict(texture="yellow_plaster", tile=2.5, tint=[0.95, 0.95, 0.95], color=[0.62, 0.57, 0.48], roughness=0.85),
    "roof_gable": dict(texture="clay_roof_tiles", tile=2.0, tint=[1.0, 1.0, 1.0], color=[0.42, 0.24, 0.17], roughness=0.8),
    "roof_flat": dict(color=[0.45, 0.45, 0.44], roughness=0.9),
    "shed_roof": dict(texture="corrugated_iron_02", tile=2.0, tint=[1.0, 1.0, 1.0], color=[0.3, 0.38, 0.33], roughness=0.55, metalness=0.3),
    "steel": dict(color=[0.18, 0.18, 0.18], roughness=0.5, metalness=0.6),
    "post": dict(color=[0.33, 0.27, 0.2], roughness=0.9),
    "mesh": dict(chainlink=True, tile=0.05, color=[0.42, 0.43, 0.43], roughness=0.45, metalness=0.6, transparent=True),
    "glass": dict(color=[0.035, 0.05, 0.06], roughness=0.06),
    "door": dict(color=[0.22, 0.24, 0.25], roughness=0.45, metalness=0.6),
    "rooftop_plant": dict(color=[0.55, 0.56, 0.55], roughness=0.5, metalness=0.3),
    "trim": dict(color=[0.55, 0.53, 0.5], roughness=0.8),
    "pool_shell": dict(color=[0.58, 0.72, 0.76], roughness=0.35),
    # Water: rippled (normal map every `tile` m), matt enough that the sky doesn't mirror in it.
    "pond_water": dict(vertexColors=True, transparent=True, roughness=0.16, water=True, tile=6.0),
    "mud_water": dict(vertexColors=True, transparent=True, roughness=0.3, water=True, tile=6.0),
    "lake_water": dict(vertexColors=True, transparent=True, roughness=0.14, water=True, tile=9.0),
    "pool_water": dict(vertexColors=True, transparent=True, roughness=0.06, water=True, tile=3.0, color=[0.30, 0.62, 0.66], opacity=0.55),
}  # fmt: skip

# Water bodies: level below the ground, bed depth, bank width, shore band (m),
# shallow/deep colour + opacity (linear RGBA).
WATER = {
    "pond": dict(drop=0.3, depth=1.6, bank=3.5, band=1.8, shallow=(0.26, 0.24, 0.14, 0.62), deep=(0.06, 0.09, 0.05, 0.97)),
    "bathing": dict(drop=0.3, depth=2.2, bank=6.0, band=1.8, shallow=(0.28, 0.25, 0.15, 0.6), deep=(0.07, 0.09, 0.05, 0.97)),
    "mud": dict(drop=0.12, depth=0.45, bank=2.5, band=1.8, shallow=(0.17, 0.12, 0.08, 1.0), deep=(0.13, 0.09, 0.06, 1.0)),
    "lake": dict(drop=0.35, depth=3.0, bank=8.0, band=4.0, shallow=(0.24, 0.26, 0.17, 0.62), deep=(0.03, 0.07, 0.07, 0.97)),
}  # fmt: skip
POOL = dict(drop=0.25, depth=2.0, ramp=12.0, water=(0.30, 0.62, 0.66, 0.5))

# Poly Haven plant models (CC0) -> role and scale range. island_tree_02 is a
# 3.4 m tree, scaled to a 6-8 m shade tree. grass_bermuda_01 (10 cm tufts) is
# too small to read at site scale and isn't used.
PLANTS = {
    "island_tree_02": ("tree", (1.8, 2.4)),
    "searsia_lucida": ("bush", (1.0, 1.6)),
    "shrub_02": ("shrub", (0.8, 1.3)),
    "wild_rooibos_bush": ("shrub", (1.6, 2.6)),
    "boulder_01": ("rock", (0.7, 1.4)),
    "namaqualand_boulder_02": ("rock", (0.6, 1.2)),
}

# The CC0 placeholder animals: (animal, x, y, heading deg clockwise from north).
ANIMAL_SPOTS = [
    ("elephant", -275, -60, 200), ("elephant", -250, -35, 120),
    ("elephant", -225, 64, 170), ("elephant", -192, 82, 230),
    ("tiger", 190, -100, 250), ("tiger", 248, 5, 300), ("tiger", 296, -110, 80),
    ("rhino", 372, -108, 70), ("rhino", 380, 12, 200),
]  # fmt: skip
WALK_RADIUS = {"elephant": 18.0, "rhino": 14.0, "tiger": 9.0}

# Explorer zones (zones.json ids) -> layout zone, spawn (x, y), heading (deg clockwise from north).
EXPLORER_ZONES = {
    "elephant-care-centre": ("elephant-care-centre", (-215, 22), 0),
    "big-cat-rescue": ("big-cat-rescue", (206, -112), 0),
    "herbivore-reserve": ("herbivore-reserve", (343, -87), 90),
    "wildlife-hospital": ("wildlife-hospital", (100, -60), -10),
}

# Label text for designed places (artistic interpretation), matched on the item name.
DESCRIPTIONS = [
    ("elephant shelter", "Open-sided shelter on deep sand where elephants rest out of the sun."),
    ("shelter yards", "Sand yards beside the shelters, where elephants are fed and checked."),
    ("elephant paddock", "Large sand paddock for exercise and for elephants to socialise."),
    ("bathing pond", "Elephants bathe and cool off here."),
    ("mud wallow", "Mud protects elephant skin from sun and insects."),
    ("hydrotherapy pool", "Warm-water pool for elephants with joint and foot problems."),
    ("elephant kitchen", "Prepares the elephants' daily diets of fodder, fruit and vegetables."),
    ("elephant care office", "Keepers' and vets' office for the elephant centre."),
    ("hospital main block", "Multi-speciality veterinary hospital: diagnostics, labs and treatment rooms."),
    ("surgery and icu", "Operating theatres and intensive care."),
    ("recovery ward", "Wards where animals recover after treatment."),
    ("ambulance bay", "Where animal ambulances unload."),
    ("hospital parking", "Staff and ambulance parking."),
    ("hospital forecourt", "Entrance forecourt of the hospital."),
    ("night house", "Indoor den where the cat sleeps and is fed."),
    ("big cat enclosure", "Grassed enclosure with shade trees, rocks and a night house for a rescued big cat."),
    ("large enclosure pool", "Pool in the large enclosure."),
    ("large enclosure", "The largest cat enclosure, with its own pool."),
    ("visitor path", "Paved path between the big-cat enclosures."),
    ("shade shelter", "Shade for the herbivores in the heat of the day."),
    ("pond", "Watering pond."),
    ("paddock", "Open paddock for rhinos and other large herbivores, with a pond and shade."),
    ("entrance plaza", "Paved plaza at the south gate."),
    ("gatehouse", "Gate and security post."),
    ("visitor centre", "Reception for visitors."),
]
ZONE_DESCRIPTIONS = {
    "elephant-care-centre": "Shelters, yards, pools and a kitchen for rescued elephants.",
    "wildlife-hospital": "Veterinary hospital and recovery wards.",
    "entrance": "South gate, gatehouse and visitor centre.",
    "big-cat-rescue": "Ten enclosures and a large one for rescued tigers, lions and leopards.",
    "herbivore-reserve": "Three open paddocks for rhinos and other large herbivores.",
    "woodland": "Not described publicly: shown as native woodland.",
}


# ---------------------------------------------------------------- frame


def xz(p):
    """(x east, y north) -> three.js ground-plane [x, z]."""
    return [round(p[0], 3), round(-p[1], 3)]


def xyz(p, h):
    return [round(p[0], 3), round(h, 3), round(-p[1], 3)]


def poly_xz(poly):
    return [xz(p) for p in poly]


def items(kind=None):
    for z in LAYOUT["zones"]:
        for it in z["items"]:
            if kind is None or it["type"] == kind:
                yield z, it


# ---------------------------------------------------------------- builder


class World:
    def __init__(self):
        self.surfaces = []
        self.ribbons = []
        self.prisms = []
        self.gables = []
        self.boxes: dict[str, list] = {}
        self.basins = []
        self.quads: dict[str, list] = {}

    def surface(self, material, poly, y, holes=()):
        self.surfaces.append({"material": material, "y": round(y, 3), "polygon": poly_xz(poly),
                              "holes": [poly_xz(h) for h in holes]})  # fmt: skip

    def box(self, material, centre, along, w, d, y0, y1):
        rot = math.atan2(along[1], along[0])  # rotation about the vertical (three.js y)
        self.boxes.setdefault(material, []).append(
            [round(centre[0], 3), round(-centre[1], 3), round(rot, 4), round(w, 3), round(d, 3), round(y0, 3), round(y1, 3)]
        )

    def prism(self, material, footprint, y0, y1):
        self.prisms.append({"material": material, "footprint": poly_xz(footprint), "y0": round(y0, 3), "y1": round(y1, 3)})

    def gable(self, material, footprint, y, pitch=0.28, overhang=0.6):
        """Ridge along the long axis, rise = pitch * short side."""
        c, axis, long_len, short_len = rect_axes(footprint)
        side = (-axis[1], axis[0])
        hl, hs = long_len / 2 + overhang, short_len / 2 + overhang
        eave = [(c[0] + axis[0] * sx * hl + side[0] * sy * hs, c[1] + axis[1] * sx * hl + side[1] * sy * hs)
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]  # fmt: skip
        ridge = [(c[0] - axis[0] * hl, c[1] - axis[1] * hl), (c[0] + axis[0] * hl, c[1] + axis[1] * hl)]
        self.gables.append({"material": material, "eave": poly_xz(eave), "ridge": poly_xz(ridge),
                            "y": round(y, 3), "rise": round(pitch * short_len, 3)})  # fmt: skip

    def quad(self, material, corners):
        self.quads.setdefault(material, []).append(corners)


def unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length), length


# ---------------------------------------------------------------- water


def water_bodies():
    """Every pond, wallow, pool (layout) and lake (OSM), with the ground height around it."""
    surfaces = [it for _, it in items("surface")]
    out = []
    for _, it in items("water"):
        poly = ccw(it["polygon"])
        c = centroid(poly)
        under = [sf for sf in surfaces if inside(c, sf["polygon"]) and sf["name"] != "Pool deck"]
        zg = max([SURFACE_Y.get(sf["material"], SITE_Y) for sf in under] + [SITE_Y])
        if it["kind"] == "pool":
            kind, zg = "pool", SURFACE_Y["paving"]
        elif it["kind"] == "mud":
            kind = "mud"
        else:
            kind = "bathing" if "bathing" in it["name"].lower() else "pond"
        out.append({"name": it["name"], "kind": kind, "poly": poly, "y": zg})
    for poly in SITE["water"]:
        out.append({"name": "Lake", "kind": "lake", "poly": ccw(poly), "y": GROUND_Y})
    return out


def basin(w: World, body):
    """Sloped bank from the shoreline to a flat bed, a wet shore band, and graded water."""
    spec = WATER[body["kind"]]
    poly, zg = body["poly"], body["y"]
    bank = min(spec["bank"], half_width(poly) * 0.55)
    zw, zb = zg - spec["drop"], zg - spec["depth"]
    rings = [(poly, zg), (offset_polygon(poly, min(1.2, bank * 0.4)), zw - 0.08), (offset_polygon(poly, bank), zb)]

    def lerp(t):
        return [round(a + (b - a) * t, 3) for a, b in zip(spec["shallow"], spec["deep"])]

    water = [(offset_polygon(poly, 0.5), lerp(0.0)), (offset_polygon(poly, bank * 0.5), lerp(0.6)),
             (offset_polygon(poly, bank), lerp(1.0))]  # fmt: skip
    w.basins.append({
        "name": body["name"],
        "bank": {"material": "wet_bank", "rings": [[poly_xz(r), round(y, 3)] for r, y in rings]},
        "water": {"material": f"{'mud' if body['kind'] == 'mud' else 'lake' if body['kind'] == 'lake' else 'pond'}_water",
                  "y": round(zw, 3), "rings": [[poly_xz(r), c] for r, c in water]},
    })  # fmt: skip
    w.surface("wet_bank", offset_polygon(poly, -spec["band"]), zg + 0.006, holes=[poly])


def pool_basin(w: World, body):
    """Hydrotherapy pool: vertical walls, a flat floor and a ramp up one short end for elephants."""
    c, u, length, width = rect_axes(body["poly"])
    v = (-u[1], u[0])
    zg = body["y"]
    zf, zw = zg - POOL["depth"], zg - POOL["drop"]
    hl, hw = length / 2, width / 2
    ramp_end = -hl + POOL["ramp"]

    def at(s, t, h):
        return xyz((c[0] + u[0] * s + v[0] * t, c[1] + u[1] * s + v[1] * t), h)

    for side in (-hw, hw):
        prof = [(-hl, zg - 0.05), (ramp_end, zf), (hl, zf)]
        for (s0, z0), (s1, z1) in zip(prof, prof[1:]):
            w.quad("pool_shell", [at(s0, side, zg), at(s1, side, zg), at(s1, side, z1), at(s0, side, z0)])
    w.quad("pool_shell", [at(hl, -hw, zg), at(hl, hw, zg), at(hl, hw, zf), at(hl, -hw, zf)])
    w.quad("pool_shell", [at(-hl, -hw, zg - 0.05), at(ramp_end, -hw, zf), at(ramp_end, hw, zf), at(-hl, hw, zg - 0.05)])
    w.quad("pool_shell", [at(ramp_end, -hw, zf), at(hl, -hw, zf), at(hl, hw, zf), at(ramp_end, hw, zf)])
    w.quad("pool_water", [at(-hl, -hw, zw), at(hl, -hw, zw), at(hl, hw, zw), at(-hl, hw, zw)])
    # Coping around the edge.
    for sgn in (-1, 1):
        w.box("paving", (c[0] + v[0] * sgn * (hw + 0.4), c[1] + v[1] * sgn * (hw + 0.4)), u, length + 1.6, 0.8, 0.15, 0.4)
        w.box("paving", (c[0] + u[0] * sgn * (hl + 0.4), c[1] + u[1] * sgn * (hl + 0.4)), u, 0.8, width, 0.15, 0.4)
    return {"color": list(POOL["water"])}


# ---------------------------------------------------------------- site base


def site_base(w: World, bodies):
    h = GROUND_SIZE / 2
    square = [(-h, -h), (h, -h), (h, h), (-h, h)]
    outline = ccw(SITE["outline"])

    def holes_in(poly):
        return [b["poly"] for b in bodies if all(inside(p, poly) for p in b["poly"])]

    w.surface("ground_scrub", square, GROUND_Y, holes_in(square))
    w.surface("site_ground", outline, SITE_Y, holes_in(outline))
    # Perimeter wall.
    for a, b in zip(outline, outline[1:] + outline[:1]):
        d, length = unit(a, b)
        if length > 1e-3:
            w.box("wall", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), d, length + WALL_THICKNESS, WALL_THICKNESS, 0.0, WALL_HEIGHT)
    for i, r in enumerate(SITE["roads"]):
        mat = {"track": "road_dirt", "service": "road_concrete"}.get(r["kind"], "road_asphalt")
        w.ribbons.append({"material": mat, "width": r["width"], "y": round(ROAD_Y + 0.004 * (i % 5), 3),
                          "points": poly_xz(r["points"])})  # fmt: skip
    for line in SITE["rail"]:
        w.ribbons.append({"material": "rail", "width": 4.0, "y": RAIL_Y, "points": poly_xz(line)})
    for ww in SITE["waterways"]:
        w.ribbons.append({"material": "stream", "width": ww["width"], "y": WATER_Y, "points": poly_xz(ww["points"])})
    # Woodland floor: the woodland area clipped to the site outline.
    wood = next(z["area"] for z in LAYOUT["zones"] if z["id"] == "woodland")
    floor = clip_polygon(outline, ccw(wood))
    if len(floor) >= 3:
        w.surface("woodland_floor", floor, SITE_Y + 0.004)


# ---------------------------------------------------------------- zones


def zone_items(w: World, bodies):
    water_polys = [b["poly"] for b in bodies]
    for _, it in items():
        kind = it["type"]
        if kind == "surface":
            poly = it["polygon"]
            holes = [p for p in water_polys if all(inside(q, poly) for q in p)]
            w.surface(it["material"], poly, SURFACE_Y[it["material"]], holes)
        elif kind == "building":
            pts, h = it["footprint"], it["height"]
            w.prism(it["material"], pts, 0.15, h)
            if it["roof"] == "gable":
                w.gable("roof_gable", pts, h)
            else:
                w.prism("roof_flat", pts, h, h + 0.25)
        elif kind == "shed":
            pts, h = it["footprint"], it["height"]
            c, axis, long_len, short_len = rect_axes(pts)
            side = (-axis[1], axis[0])
            n = max(2, round(long_len / 8) + 1)
            for i in range(n):
                t = -long_len / 2 + long_len * i / (n - 1)
                for sgn in (-1, 1):
                    p = (c[0] + axis[0] * t + side[0] * sgn * (short_len / 2 - 0.3),
                         c[1] + axis[1] * t + side[1] * sgn * (short_len / 2 - 0.3))  # fmt: skip
                    w.box("steel", p, axis, 0.3, 0.3, 0.15, h)
            w.gable("shed_roof", pts, h, pitch=0.15)
        elif kind == "fence":
            fence(w, it)


def fence(w: World, it):
    pts = list(it["points"])
    if it.get("closed", True):
        pts = pts + pts[:1]
    h, style = it["height"], it["style"]
    spacing = 3.0 if style == "post_rail" else 4.0
    for a, c in zip(pts, pts[1:]):
        d, length = unit(a, c)
        if length < 0.1:
            continue
        n = max(1, round(length / spacing))
        for i in range(n + 1):
            t = length * i / n
            w.box("post" if style == "post_rail" else "steel", (a[0] + d[0] * t, a[1] + d[1] * t), d, 0.15, 0.15, 0.15, h)
        mid = ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)
        if style == "post_rail":
            for frac in (0.45, 0.85):
                y = 0.15 + h * frac
                w.box("post", mid, d, length, 0.1, y - 0.06, y + 0.06)
        else:
            w.box("mesh", mid, d, length, 0.04, 0.15, h)


def building_details(w: World):
    """Windows by storey, doors, parapets, rooftop plant and the hospital entrance canopy."""
    counts = {"windows": 0, "doors": 0}
    for _, it in items("building"):
        pts = [tuple(p) for p in it["footprint"]]
        h, name = it["height"], it["name"].lower()
        night_house = name.startswith(("night house", "large enclosure night"))
        # Footprints are counter-clockwise: the outward normal of edge a->b is (dy, -dx).
        edges = []
        for a, b in zip(pts, pts[1:] + pts[:1]):
            d, length = unit(a, b)
            edges.append((a, b, length, d, (d[1], -d[0])))
        front = min(edges, key=lambda e: (e[4][1], -e[2]))  # the most south-facing wall
        a, b, length, along, out = front
        mid = ((a[0] + b[0]) / 2 + out[0] * 0.06, (a[1] + b[1]) / 2 + out[1] * 0.06)
        if night_house:
            w.box("door", mid, along, min(3.0, length * 0.4), 0.12, 0.15, 2.4)
        elif it["material"] == "hospital" and h > 8:
            w.box("glass", mid, along, 6.0, 0.12, 0.15, 3.2)
            canopy = ((a[0] + b[0]) / 2 + out[0] * 4.0, (a[1] + b[1]) / 2 + out[1] * 4.0)
            w.box("trim", canopy, along, 10.0, 8.0, 3.6, 3.9)
            for s in (-1, 1):
                p = (canopy[0] + along[0] * s * 4.5 + out[0] * 3.5, canopy[1] + along[1] * s * 4.5 + out[1] * 3.5)
                w.box("trim", p, along, 0.35, 0.35, 0.15, 3.6)
        else:
            big = length > 20
            w.box("door", mid, along, 2.4 if big else 1.2, 0.12, 0.15, 2.6 if big else 2.2)
        counts["doors"] += 1
        if not night_house:
            if it["roof"] == "gable" and h > 7:
                rows = [(h - 3.2, h - 1.4)]  # high clerestory band (kitchen hall)
            else:
                rows = [(0.15 + s * STOREY + 1.0, 0.15 + s * STOREY + 2.5) for s in range(max(1, int(h // STOREY)))]
            door_at = ((front[0][0] + front[1][0]) / 2, (front[0][1] + front[1][1]) / 2)
            for ea, eb, length, along, out in edges:
                n = int((length - 2.5) // 3.6)
                if n < 1:
                    continue
                start = (length - (n - 1) * 3.6) / 2
                for i in range(n):
                    t = start + i * 3.6
                    c = (ea[0] + along[0] * t + out[0] * 0.05, ea[1] + along[1] * t + out[1] * 0.05)
                    if (ea, eb) == (front[0], front[1]) and math.dist(c, door_at) < 4.0:
                        continue  # keep the door clear
                    for y0, y1 in rows:
                        w.box("glass", c, along, 1.8, 0.1, y0, y1)
                        w.box("trim", (c[0] + out[0] * 0.06, c[1] + out[1] * 0.06), along, 2.1, 0.22, y0 - 0.12, y0)
                        counts["windows"] += 1
        if it["roof"] != "gable":
            for ea, eb, length, along, out in edges:
                m = ((ea[0] + eb[0]) / 2 - out[0] * 0.12, (ea[1] + eb[1]) / 2 - out[1] * 0.12)
                w.box(it["material"], m, along, length, 0.25, h + 0.25, h + 1.0)
            if h > 8:
                # Rooftop plant: AC units and a water tank, as on most Indian institutional roofs.
                c = centroid(pts)
                along0 = max(edges, key=lambda e: e[2])[3]
                side = (-along0[1], along0[0])
                for i in range(4):
                    k = -12 + i * 8
                    w.box("rooftop_plant", (c[0] + along0[0] * k + side[0] * 6, c[1] + along0[1] * k + side[1] * 6),
                          along0, 3.0, 2.0, h + 0.25, h + 1.9)  # fmt: skip
                w.box("rooftop_plant", (c[0] - side[0] * 6, c[1] - side[1] * 6), along0, 4.0, 4.0, h + 0.25, h + 2.8)
    return counts


# ---------------------------------------------------------------- plants


def plant_variants():
    """Mesh variants in each downloaded model (names from the glTF), with role and scale range."""
    out = {}
    for asset, (role, scale) in PLANTS.items():
        files = sorted((MODELS / asset).glob("*.gltf"))
        if not files:
            continue
        g = json.loads(files[0].read_text(encoding="utf-8"))
        for node in g.get("nodes", []):
            if "mesh" in node:
                out[node["name"]] = {"asset": asset, "role": role, "scale": list(scale)}
    return out


def plants(bodies):
    variants = plant_variants()
    by_role: dict[str, list[str]] = {}
    for name, v in variants.items():
        by_role.setdefault(v["role"], []).append(name)
    rng = random.Random(SEED)
    outline = ccw(SITE["outline"])
    ox0, oy0, ox1, oy1 = bbox(outline)

    def near_site(q):
        return ox0 - 60 < q[0] < ox1 + 60 and oy0 - 60 < q[1] < oy1 + 60

    built = []
    for _, it in items():
        if it["type"] in ("building", "shed"):
            built.append((it["footprint"], 4.0))
        elif it["type"] == "water":
            built.append((it["polygon"], 3.0))
        elif it["type"] == "surface" and it["material"] in ("paving", "asphalt"):
            built.append((it["polygon"], 2.0))
    built = Obstacles(built)
    road_list = [(r["points"], r["width"] / 2 + 3.0) for r in SITE["roads"] if any(near_site(q) for q in r["points"])]
    roads = Lines(road_list)
    fences = Obstacles([(it["points"], 2.5) for _, it in items("fence")], solid=False)
    zone_areas = {z["id"]: z["area"] for z in LAYOUT["zones"]}
    other_zones = [a for zid, a in zone_areas.items() if zid != "woodland"]
    woods = zone_areas["woodland"]

    def blocked(p, extra=0.0, fence_too=True):
        if not inside(p, outline) or edge_dist(p, outline) < 4.0:
            return True
        if built.hit(p, extra) or roads.hit(p):
            return True
        return fence_too and fences.hit(p)

    def free(p):
        return not blocked(p) and not any(inside(p, a) for a in other_zones)

    instances: dict[str, list] = {}
    planted: dict[str, list] = {}

    def put(role, pts, y=SITE_Y):
        names = sorted(by_role.get(role, []))
        if not names:
            return
        for x, yy in pts:
            name = rng.choice(names)
            lo, hi = variants[name]["scale"]
            instances.setdefault(name, []).append(
                [round(x, 2), round(y, 3), round(-yy, 2), round(rng.uniform(0, 2 * math.pi), 3), round(rng.uniform(lo, hi), 3)]
            )
        planted.setdefault(role, []).extend(pts)

    def clear_of(role, p, d):
        return all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= d * d for q in planted.get(role, []))

    def each_surface(test):
        for _, it in items("surface"):
            if test(it["name"].lower(), it["material"]):
                yield it["name"].lower(), it["polygon"]

    def avenue_points():
        """Both sides of the internal roads, every 16 m, 4 m back from the edge."""
        pts = []
        for line, clear in road_list:
            off = clear + 1.0
            for a, b in zip(line, line[1:]):
                d, length = unit(a, b)
                if length < 1:
                    continue
                side = (-d[1], d[0])
                t = 8.0
                while t <= length:
                    for sgn in (-1, 1):
                        q = (a[0] + d[0] * t + side[0] * sgn * off, a[1] + d[1] * t + side[1] * sgn * off)
                        if not blocked(q, 1.0) and clear_of("tree", q, 9) and all(math.dist(q, o) > 10 for o in pts):
                            pts.append(q)
                    t += 16.0
        return pts

    # Trees: closed woodland canopy, road avenues, shade on the grounds and in every yard.
    put("tree", scatter(rng, woods, 7.5, 420, blocked))
    put("tree", avenue_points())
    put("tree", scatter(rng, outline, 15, 260, lambda p: not free(p) or not clear_of("tree", p, 9)))
    for name, poly in each_surface(lambda n, m: "enclosure" in n or "paddock" in n):
        k = 10 if "elephant" in name else 4 if "paddock" in name else 3
        put("tree", scatter(rng, poly, 12, k, lambda p: blocked(p, 2.0)))
    # Understory and shrubs.
    put("bush", scatter(rng, woods, 4.5, 380, lambda p: blocked(p) or not clear_of("tree", p, 2.5)))
    put("bush", scatter(rng, outline, 11, 200, lambda p: not free(p)))
    for name, poly in each_surface(lambda n, m: m == "grass_wild"):
        put("bush", scatter(rng, poly, 6, 4, lambda p: blocked(p, 1.0)))
    put("shrub", scatter(rng, woods, 3.2, 450, lambda p: blocked(p, 0.0, False) or not clear_of("tree", p, 1.5)))
    put("shrub", scatter(rng, outline, 6, 450, lambda p: not free(p)))
    for name, poly in each_surface(lambda n, m: m == "grass_wild"):
        put("shrub", scatter(rng, poly, 4, 8, lambda p: blocked(p, 1.0)))
    for name, poly in each_surface(lambda n, m: "enclosure" in n or "elephant paddock" in n):
        put("rock", scatter(rng, poly, 8, 6 if "elephant" in name else 3, lambda p: blocked(p, 1.0)))

    # Shores: rocks on the upper bank, a planted ring outside, a couple of trees.
    # The bathing pond keeps its south side open: elephants walk in there.
    solid = [it["footprint"] for _, it in items() if it["type"] in ("building", "shed")]
    fence_lines = [it["points"] for _, it in items("fence")]

    def shore_ok(q):
        return (inside(q, outline) and edge_dist(q, outline) > 3 and not any(inside(q, f) for f in solid)
                and all(edge_dist(q, f) > 1.5 for f in fence_lines))  # fmt: skip

    for body in bodies:
        if body["kind"] in ("pool", "lake"):
            continue
        poly = body["poly"]
        cy = centroid(poly)[1]
        bathing = body["kind"] == "bathing"

        def open_side(q):
            return bathing and q[1] < cy

        edge = [q for q in offset_polygon(poly, 0.7) if not open_side(q)]
        put("rock", [q for q in rng.sample(edge, min(len(edge), 5)) if shore_ok(q)], y=body["y"] - 0.15)
        ring = [q for q in offset_polygon(poly, -2.8) if shore_ok(q) and not open_side(q)]
        put("shrub", [q for q in ring if rng.random() < 0.7])
        put("bush", [q for q in offset_polygon(poly, -5.0)[::3] if shore_ok(q) and not open_side(q)])
        far = [q for q in offset_polygon(poly, -9.0) if shore_ok(q) and not open_side(q) and clear_of("tree", q, 8)]
        put("tree", rng.sample(far, min(len(far), 2)))

    counts = {role: len(pts) for role, pts in planted.items()}
    return {"variants": variants, "instances": instances}, counts


# ---------------------------------------------------------------- animals, places, zones


def animals():
    """Each placed animal walks a loop of three waypoints inside its yard, out of the water."""
    surfaces = [it["polygon"] for _, it in items("surface")]
    water = [it["polygon"] for _, it in items("water")]
    out = []
    for i, (kind, x, y, heading) in enumerate(ANIMAL_SPOTS):
        p = (x, y)
        home = next((s for s in surfaces if inside(p, s)), None)
        pts = [p]
        r = WALK_RADIUS.get(kind, 10.0)
        for k in range(36):
            if len(pts) == 3:
                break
            a = math.radians(k * 47 + i * 31)
            q = (p[0] + r * math.cos(a), p[1] + r * math.sin(a))
            ok = home is None or (inside(q, home) and edge_dist(q, home) > 4)
            ok = ok and not any(inside(q, w) or edge_dist(q, w) < 3 for w in water)
            ok = ok and all(math.dist(q, o) > r * 0.6 for o in pts)
            if ok:
                pts.append(q)
        out.append({"animal": kind, "path": [xz(q) for q in pts], "headingDeg": heading,
                    "idleSeconds": [6, 16] if kind == "elephant" else [5, 14]})  # fmt: skip
    return out


def label_name(name):
    return name.split(" (")[0]


def places():
    """Every named part of the site, for 3D labels, click-to-zoom and the map.

    tier 1: zones (always shown), 2: main places, 3: small things (shown close up).
    stand: a walkable spot outside buildings, fences and water, facing the place.
    """
    blockers, fences = [], []
    for _, it in items():
        if it["type"] in ("building", "shed"):
            blockers.append(it["footprint"])
        elif it["type"] == "water":
            blockers.append(it["polygon"])
        elif it["type"] == "fence" and it.get("closed", True):
            fences.append(it["points"])
    outline = SITE["outline"]

    def stand_among(cx, cy, reach, own, blocks):
        for ring in (reach + 4, reach + 10, reach + 20):
            for k in range(16):
                a = -math.pi / 2 + k * math.pi / 8  # start south of the place, then go round
                q = (cx + ring * math.cos(a), cy + ring * math.sin(a))
                if not inside(q, outline) or edge_dist(q, outline) < 3:
                    continue
                if any(inside(q, b) or edge_dist(q, b) < 1.5 for b in blocks if b is not own):
                    continue
                if own is not None and inside(q, own):
                    continue
                heading = math.degrees(math.atan2(cx - q[0], cy - q[1]))  # clockwise from north
                return {"position": xyz(q, SITE_Y), "yawDeg": round(-heading, 1)}
        return None

    def stand_for(cx, cy, reach, own):
        # Outside fences if possible (visitors' side); else inside the yard (ponds in paddocks).
        return stand_among(cx, cy, reach, own, blockers + fences) or stand_among(cx, cy, reach, own, blockers)

    out = []
    for z in LAYOUT["zones"]:
        cx, cy = centroid(z["area"])
        out.append({
            "id": z["id"], "name": z["name"].split(" (")[0], "tier": 1, "zone": z["id"], "kind": "zone",
            "description": ZONE_DESCRIPTIONS.get(z["id"], ""),
            "position": xyz((cx, cy), 32.0), "size": round(math.sqrt(area(z["area"])), 1), "stand": None,
        })  # fmt: skip
        for it in z["items"]:
            if it["type"] == "fence" or it["name"] == "Pool deck" or label_name(it["name"]) == z["name"]:
                continue  # fences, the deck under the pool label, and areas named like their zone
            poly = it.get("footprint") or it.get("polygon")
            a = area(poly)
            px, py = centroid(poly)
            height = it.get("height", 0.0)
            low = it["name"].lower()
            if it["type"] in ("building", "shed"):
                tier = 2 if a >= 200 and not low.startswith("night house") else 3
            elif it["type"] == "water":
                tier = 3 if "paddock" in low or "large enclosure" in low else 2
            else:
                tier = 2 if a >= 1000 or "path" in low or "plaza" in low else 3
            own = poly if it["type"] in ("building", "shed", "water") else None
            fenced = next((f for f in fences if f == poly), None)
            out.append({
                "id": f"{z['id']}/{low.replace(' ', '-').replace('(', '').replace(')', '')}",
                "name": label_name(it["name"]), "tier": tier, "zone": z["id"], "kind": it["type"],
                "description": next((d for key, d in DESCRIPTIONS if key in low), ""),
                "position": xyz((px, py), height + 2.5 if height else 2.5),
                "size": round(max(6.0, math.sqrt(a)), 1),
                "stand": stand_for(px, py, math.sqrt(a) / 2, own or fenced),
            })  # fmt: skip
    return out


def occluders():
    """Solid buildings as footprint + top height: labels behind them are hidden."""
    out = []
    for _, it in items("building"):
        pts = it["footprint"]
        short = min(math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2]))
        top = it["height"] + (0.28 * short if it["roof"] == "gable" else 1.0)
        out.append({"footprint": poly_xz(pts), "top": round(top, 2)})
    return out


def map_frame():
    """Area the overview map shows: centre and span in local metres (x east, y north)."""
    x0, y0, x1, y1 = bbox(SITE["outline"])
    w, h = 2048, 1536
    span_x = max(x1 - x0, (y1 - y0) * w / h) * 1.08
    return {"image": "/map/overview.svg", "centre": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)],
            "span": [round(span_x, 2), round(span_x * h / w, 2)], "size": [w, h]}  # fmt: skip


def solar_position(lat, lon, when):
    """Sun elevation and azimuth (degrees, azimuth clockwise from north); NOAA approximation."""
    utc = when.astimezone(timezone.utc)
    day = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60
    g = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))  # fmt: skip
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))  # fmt: skip
    tst = hour * 60 + eqtime + 4 * lon
    ha = math.radians(tst / 4 - 180)
    phi = math.radians(lat)
    cos_zen = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1, min(1, cos_zen)))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))) + 180
    return 90 - math.degrees(zen), az % 360


def sun():
    elevation, azimuth = solar_position(SITE["origin"]["lat"], SITE["origin"]["lon"], WHEN)
    el, az = math.radians(elevation), math.radians(azimuth)
    towards = (math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el))  # x east, y north, z up
    return {"direction": [round(towards[0], 4), round(towards[2], 4), round(-towards[1], 4)],
            "elevationDeg": round(elevation, 1), "azimuthDeg": round(azimuth, 1)}  # fmt: skip


def zone_meta(zone_id, layout_id, spawn, heading, sun_dir, size_mb):
    area_poly = next(z["area"] for z in LAYOUT["zones"] if z["id"] == layout_id)
    x0, y0, x1, y1 = bbox(area_poly)
    cx, cy = centroid(area_poly)
    # Flyover: a loop around the zone 12 m up, inset from its edge.
    path = [xyz((cx + (x1 - x0) * 0.38 * math.cos(a), cy + (y1 - y0) * 0.38 * math.sin(a)), 12.0)
            for a in (2 * math.pi * k / 10 for k in range(10))]  # fmt: skip
    # Walkable bounds: the whole site, so "walk here" works for places in other zones.
    ox0, oy0, ox1, oy1 = bbox(SITE["outline"])
    m = 60
    return {
        "zone": zone_id,
        "units": "m",
        "kind": "world",
        "world": {"manifest": "world/world.json"},
        "groundY": SITE_Y,
        "files": {"desktop": "", "mobile": "", "collision": ""},
        "sizesMB": {"world": size_mb},
        "splats": {},
        "bounds": {"min": [ox0 - m, -5, -(oy1 + m)], "max": [ox1 + m, 60, -(oy0 - m)]},
        "spawn": {"position": xyz(spawn, SITE_Y + EYE_HEIGHT), "yawDeg": -heading},
        "eyeHeight": EYE_HEIGHT,
        "cameraPath": path,
        "fovY": 60,
        "north": {"deg": 0, "known": True},
        "lighting": {"ambient": [0.55, 0.6, 0.68], "sun": {"direction": sun_dir, "color": [2.6, 2.45, 2.25]},
                     "estimated": False},  # fmt: skip
    }


# ---------------------------------------------------------------- main


def compile_world():
    """The whole world as one dict (no files written)."""
    w = World()
    bodies = water_bodies()
    site_base(w, bodies)
    zone_items(w, bodies)
    details = building_details(w)
    for body in bodies:
        if body["kind"] == "pool":
            pool_basin(w, body)
        else:
            basin(w, body)
    plant_data, plant_counts = plants(bodies)
    world = {
        "format": "vantara-world",
        "version": 2,
        "note": "Artistic interpretation: designed layout inside Vantara's mapped outline, not surveyed.",
        "attribution": [SITE["attribution"], "Textures and plants: Poly Haven (polyhaven.com), CC0",
                        "Animals: CC0 placeholders (see /models/CREDITS.md)"],  # fmt: skip
        "units": "m",
        # Built by prepare_textures.py (textures/<set>_diff.jpg, _nor.jpg) and
        # world/tools/build_plants.mjs (nodes "<variant>|lod0", "|lod1"), relative to this file.
        "assets": {"textures": "textures/", "plants": "plants.glb"},
        "groundY": SITE_Y,
        "sun": sun(),
        "materials": MATERIALS,
        "surfaces": w.surfaces,
        "ribbons": w.ribbons,
        "prisms": w.prisms,
        "gables": w.gables,
        "boxes": w.boxes,
        "basins": w.basins,
        "quads": w.quads,
        "plants": plant_data,
        "animals": animals(),
        "places": places(),
        "occluders": occluders(),
        "map": map_frame(),
    }
    stats = {
        "surfaces": len(w.surfaces), "ribbons": len(w.ribbons), "prisms": len(w.prisms), "gables": len(w.gables),
        "boxes": sum(len(v) for v in w.boxes.values()), "basins": len(w.basins), "quads": sum(len(v) for v in w.quads.values()),
        **details, "plants": plant_counts, "animals": len(world["animals"]), "places": len(world["places"]),
    }  # fmt: skip
    return world, stats


def compact_json(data):
    """indent=2, but short flat objects and arrays on one line (zones.json's hand-written style)."""

    def fold(m, open_, close, pad):
        items_ = ", ".join(x.strip() for x in m.group(1).split(",\n"))
        line = f"{open_}{pad}{items_}{pad}{close}"
        return line if len(line) <= 60 else m.group(0)

    text = json.dumps(data, indent=2, ensure_ascii=False)
    text = re.sub(r"\[\n\s+([^\[\]{}]*?)\n\s+\]", lambda m: fold(m, "[", "]", ""), text)
    text = re.sub(r"\{\n\s+([^\[\]{}]*?)\n\s+\}", lambda m: fold(m, "{", "}", " "), text)
    return text + "\n"


def write_map(world):
    """Overview SVG plus the matching zone positions in zones.json."""
    svg, positions = overview_map.render(world, LAYOUT, SITE, world["map"], {z: v[0] for z, v in EXPLORER_ZONES.items()})
    MAP_SVG.parent.mkdir(parents=True, exist_ok=True)
    MAP_SVG.write_text(svg, encoding="utf-8")
    data = json.loads(ZONES_JSON.read_text(encoding="utf-8"))
    for z in data["zones"]:
        if z["id"] in positions:
            z["map"] = positions[z["id"]]
    w, h = world["map"]["size"]
    data["map"] = {"image": world["map"]["image"], "width": w, "height": h}
    ZONES_JSON.write_text(compact_json(data), encoding="utf-8", newline="\n")
    return len(svg)


def main() -> None:
    world, stats = compile_world()
    out_world = OUT / "world"
    out_world.mkdir(parents=True, exist_ok=True)
    text = json.dumps(world, separators=(",", ":"))
    (out_world / "world.json").write_text(text, encoding="utf-8")
    size_mb = round(len(text) / 1e6, 2)
    for zone_id, (layout_id, spawn, heading) in EXPLORER_ZONES.items():
        (OUT / zone_id).mkdir(parents=True, exist_ok=True)
        meta = zone_meta(zone_id, layout_id, spawn, heading, world["sun"]["direction"], size_mb)
        (OUT / zone_id / f"{zone_id}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    svg_bytes = write_map(world)
    print(f"world.json: {size_mb} MB -> {out_world / 'world.json'}")
    print(f"overview.svg: {svg_bytes / 1e3:.0f} kB -> {MAP_SVG}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
