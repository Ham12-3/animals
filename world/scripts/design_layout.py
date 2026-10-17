"""World step 2: the designed layout of Vantara's zones (artistic interpretation).

    uv run --project pipeline python world/scripts/design_layout.py

Writes world/data/layout.json: for each zone its area and items (buildings,
open sheds, pools, ponds, yards, fences, paved areas) in the same local metres
as site.json. Zones follow the blocks formed by the real internal roads from
OpenStreetMap; what is inside each block is designed from public descriptions
of Vantara (elephant shelters and hydrotherapy pools, an elephant kitchen, a
multi-specialty wildlife hospital, big-cat enclosures, herbivore paddocks), not
surveyed. Every item is checked to lie inside the mapped outline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SITE = json.loads((HERE / "data" / "site.json").read_text(encoding="utf-8"))
OUT = HERE / "data" / "layout.json"


def rect(cx, cy, w, d, rot=0.0):
    """Rectangle footprint centred at (cx, cy), w along local X, d along local Y, rotated rot degrees."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = []
    for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        pts.append([round(cx + x * c - y * s, 2), round(cy + x * s + y * c, 2)])
    return pts


def blob(cx, cy, rx, ry, n=18, wobble=0.18, seed=1):
    """Irregular natural outline (ponds, wallows)."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + wobble * math.sin(3 * a + seed) * math.cos(2 * a - seed * 0.7)
        pts.append([round(cx + rx * k * math.cos(a), 2), round(cy + ry * k * math.sin(a), 2)])
    return pts


def building(name, footprint, height, roof="flat", material="building"):
    return {"type": "building", "name": name, "footprint": footprint, "height": height, "roof": roof, "material": material}


def shed(name, footprint, height):
    """Open-sided shelter: posts and a roof, no walls."""
    return {"type": "shed", "name": name, "footprint": footprint, "height": height}


def surface(name, polygon, material):
    return {"type": "surface", "name": name, "polygon": polygon, "material": material}


def water(name, polygon, kind):
    return {"type": "water", "name": name, "polygon": polygon, "kind": kind}


def fence(name, polygon, height, style, closed=True):
    return {"type": "fence", "name": name, "points": polygon, "height": height, "style": style, "closed": closed}


def elephant_care_centre():
    items = [
        building("Elephant kitchen", rect(-40, -95, 50, 28), 9.0, roof="gable"),
        building("Elephant care office", rect(-30, 112, 26, 14), 5.0),
        water("Hydrotherapy pool", rect(-60, 40, 40, 18), "pool"),
        surface("Pool deck", rect(-60, 40, 52, 30), "paving"),
        water("Bathing pond", blob(-160, -45, 48, 26, seed=2), "pond"),
        water("Mud wallow", blob(-290, -70, 15, 11, seed=5), "mud"),
        surface("Elephant paddock (sand)", rect(-215, -55, 270, 105), "sand"),
        fence("Elephant paddock fence", rect(-215, -55, 270, 105), 2.4, "post_rail"),
    ]
    for row, y in enumerate((110, 72)):
        for col, x in enumerate((-300, -215, -130)):
            items.append(shed(f"Elephant shelter {row * 3 + col + 1}", rect(x, y, 70, 18), 8.0))
    items.append(surface("Shelter yards (sand)", rect(-215, 91, 270, 58), "sand"))
    return {
        "id": "elephant-care-centre",
        "name": "Elephant Care Centre",
        "area": [[-365, -122], [2, -122], [2, 138], [-362, 133]],
        "items": items,
    }


def wildlife_hospital():
    return {
        "id": "wildlife-hospital",
        "name": "Wildlife Hospital",
        "area": [[24, -38], [135, -38], [137, 118], [26, 118]],
        "items": [
            building("Hospital main block", rect(80, 45, 80, 45), 11.0, material="hospital"),
            building("Surgery and ICU wing", rect(80, -5, 50, 20), 7.0, material="hospital"),
            building("Recovery ward A", rect(45, 98, 30, 16), 5.0, material="hospital"),
            building("Recovery ward B", rect(115, 98, 30, 16), 5.0, material="hospital"),
            shed("Ambulance bay", rect(122, -26, 20, 10), 5.0),
            surface("Hospital parking", rect(42, -22, 26, 24), "asphalt"),
            surface("Hospital forecourt", rect(80, 14, 80, 14), "paving"),
        ],
    }


def entrance():
    return {
        "id": "entrance",
        "name": "Entrance plaza",
        "area": [[60, -155], [145, -156], [145, -128], [60, -127]],
        "items": [
            surface("Entrance plaza", rect(102, -141, 80, 24), "paving"),
            building("Gatehouse", rect(70, -140, 14, 8), 4.0, roof="gable"),
            building("Visitor centre", rect(133, -140, 18, 12), 5.0, roof="gable"),
        ],
    }


def big_cat_rescue():
    items = []
    columns = (174, 238)  # 52 m wide enclosures with a 12 m path between columns
    rows = (-96, -48, 0, 48, 96)
    n = 0
    for x in columns:
        for y in rows:
            n += 1
            items.append(surface(f"Big cat enclosure {n} (grass)", rect(x, y, 50, 42), "grass_wild"))
            items.append(fence(f"Big cat enclosure {n} fence", rect(x, y, 50, 42), 5.0, "mesh"))
            back = y + 21 - 4 if x == columns[0] else y + 21 - 4
            items.append(building(f"Night house {n}", rect(x + (-17 if x == columns[0] else 17), back, 12, 6), 3.5))
    items.append(surface("Visitor path", rect(206, 0, 10, 250), "paving"))
    items.append(surface("Large enclosure (grass)", rect(307, -86, 58, 74), "grass_wild"))
    items.append(fence("Large enclosure fence", rect(307, -86, 58, 74), 5.0, "mesh"))
    items.append(water("Large enclosure pool", blob(300, -95, 12, 8, seed=3), "pond"))
    items.append(building("Large enclosure night house", rect(318, -56, 16, 7), 3.5))
    return {
        "id": "big-cat-rescue",
        "name": "Big Cat Rescue",
        "area": [[145, -122], [265, -122], [267, 128], [147, 128]],
        "items": items,
    }


def herbivore_reserve():
    items = []
    bands = ((-128, -46), (-40, 42), (48, 128))
    for i, (y0, y1) in enumerate(bands, start=1):
        x1_low, x1_high = 446 + (y0 + 153) * 35 / 270 - 8, 446 + (y1 + 153) * 35 / 270 - 8
        poly = [[350, y0], [round(x1_low, 1), y0], [round(x1_high, 1), y1], [350, y1]]
        items.append(surface(f"Paddock {i} (grass)", poly, "grass_wild"))
        items.append(fence(f"Paddock {i} fence", poly, 1.6, "post_rail"))
        cy = (y0 + y1) / 2
        items.append(water(f"Paddock {i} pond", blob(395, cy - 10, 16, 9, seed=4 + i), "pond"))
        items.append(shed(f"Paddock {i} shade shelter", rect(372, cy + 22, 12, 8), 4.0))
    return {
        "id": "herbivore-reserve",
        "name": "Herbivore Reserve",
        "area": [[348, -130], [441, -130], [471, 130], [347, 130]],
        "items": items,
    }


def woodland():
    return {
        "id": "woodland",
        "name": "Woodland (not described publicly)",
        "area": [[-585, 140], [-376, 136], [-376, -78], [-440, -70]],
        "items": [],
    }


def inside(pt, poly):
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def main() -> None:
    zones = [elephant_care_centre(), wildlife_hospital(), entrance(), big_cat_rescue(), herbivore_reserve(), woodland()]
    outline = SITE["outline"]
    problems = []
    for z in zones:
        for item in z["items"]:
            pts = item.get("footprint") or item.get("polygon") or item.get("points")
            outside = [p for p in pts if not inside(p, outline)]
            if outside:
                problems.append(f"{z['id']}: {item['name']} has {len(outside)} point(s) outside the outline")
    layout = {
        "note": "Artistic interpretation: designed layout inside Vantara's mapped outline, not surveyed.",
        "attribution": SITE["attribution"],
        "zones": zones,
    }
    OUT.write_text(json.dumps(layout, indent=1), encoding="utf-8")
    counts = {z["id"]: len(z["items"]) for z in zones}
    print("items per zone:", counts)
    print("outside-outline problems:", problems or "none")
    print("->", OUT)


if __name__ == "__main__":
    main()
