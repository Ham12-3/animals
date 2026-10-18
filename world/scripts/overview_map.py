"""Overview map of the world as a vector image (SVG), drawn from the same data as the 3D world.

Called by compile_world.py. Writes web/public/map/overview.svg in the frame
compile_world.map_frame() describes (the explorer places zone and place dots
with the same frame), and returns each explorer zone's position on it (0..1).
No text on the map itself: the explorer draws the names on top.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from worldgeo import centroid


# Map colours (sRGB), close to how each surface looks from above in the explorer.
FILL = {
    "ground_scrub": "#8b7a63", "site_ground": "#9a8668", "woodland_floor": "#6f5d46",
    "sand": "#c9b28a", "grass_wild": "#a2956a", "asphalt": "#4a4a48", "paving": "#9c8576",
    "wet_bank": "#5b4936", "mud": "#5e4630", "pond": "#4f6a5a", "lake": "#4d7380", "pool": "#5fb3c2",
    "roof_gable": "#9a5a3f", "roof_flat": "#bdbdba", "hospital": "#e4e4e0", "building": "#cdbb94",
    "shed_roof": "#5f7468", "tree": "#3f5a2c", "bush": "#55683a",
}  # fmt: skip
ROAD = {"road_asphalt": "#3d3d3c", "road_concrete": "#c9c4ba", "road_dirt": "#a48a68", "rail": "#5a5654", "stream": "#4d7380"}


def render(world: dict, layout: dict, site: dict, frame: dict, zones: dict) -> tuple[str, dict]:
    w, h = frame["size"]
    cx, cy = frame["centre"]
    sx, sy = frame["span"]
    k = w / sx  # pixels per metre

    def px(x, z):
        """three.js ground point [x, z] -> SVG pixel."""
        return (round((x - cx) * k + w / 2, 1), round((-z - cy) * -k + h / 2, 1))

    def path(points, close=True):
        if not points:
            return ""
        d = "M" + " L".join("{} {}".format(*px(*p)) for p in points)
        return d + (" Z" if close else "")

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
           f'<rect width="{w}" height="{h}" fill="{FILL["ground_scrub"]}"/>']  # fmt: skip

    # Ground layers (with their holes), back to front as the explorer draws them.
    order = ["ground_scrub", "site_ground", "woodland_floor", "grass_wild", "sand", "asphalt", "wet_bank", "paving", "mud"]
    surfaces = sorted(world["surfaces"], key=lambda s: order.index(s["material"]) if s["material"] in order else 99)
    for s in surfaces:
        if s["material"] == "ground_scrub":
            continue
        d = path(s["polygon"]) + " " + " ".join(path(hole) for hole in s["holes"])
        out.append(f'<path d="{d}" fill="{FILL.get(s["material"], "#999")}" fill-rule="evenodd"/>')
    # Water.
    for b in world["basins"]:
        kind = "mud" if b["water"]["material"] == "mud_water" else "lake" if b["water"]["material"] == "lake_water" else "pond"
        out.append(f'<path d="{path(b["bank"]["rings"][0][0])}" fill="{FILL[kind]}"/>')
    for quad in world["quads"].get("pool_water", []):
        out.append(f'<path d="{path([[c[0], c[2]] for c in quad])}" fill="{FILL["pool"]}"/>')
    # Roads, rail and streams (at least 1.5 px wide).
    for r in world["ribbons"]:
        dash = ' stroke-dasharray="6 4"' if r["material"] == "rail" else ""
        width = max(1.5, r["width"] * k)
        out.append(f'<path d="{path(r["points"], close=False)}" fill="none" stroke="{ROAD[r["material"]]}" '
                   f'stroke-width="{width:.1f}" stroke-linecap="round" stroke-linejoin="round"{dash}/>')  # fmt: skip
    # Perimeter wall.
    outline = [[x, -y] for x, y in site["outline"]]
    out.append(f'<path d="{path(outline)}" fill="none" stroke="#e2d6bd" stroke-width="2"/>')
    # Fences.
    for z in layout["zones"]:
        for it in z["items"]:
            if it["type"] == "fence":
                pts = [[x, -y] for x, y in it["points"]]
                colour = "#6d6a64" if it["style"] == "mesh" else "#7a6046"
                out.append(f'<path d="{path(pts, it.get("closed", True))}" fill="none" stroke="{colour}" stroke-width="1"/>')
    # Plants: canopies as soft dots (trees ~3.5 m, bushes ~1.2 m radius at scale 1).
    plants = world["plants"]
    for name, rows in plants["instances"].items():
        role = plants["variants"][name]["role"]
        if role not in ("tree", "bush"):
            continue
        r0 = 1.6 if role == "tree" else 0.9
        dots = "".join(f'<circle cx="{px(x, zz)[0]}" cy="{px(x, zz)[1]}" r="{max(1.2, r0 * s * k):.1f}"/>' for x, _, zz, _, s in rows)
        out.append(f'<g fill="{FILL[role]}" fill-opacity="{0.85 if role == "tree" else 0.7}">{dots}</g>')
    # Buildings and shelters (roofs), on top.
    for z in layout["zones"]:
        for it in z["items"]:
            if it["type"] == "building":
                key = "roof_gable" if it["roof"] == "gable" else ("hospital" if it["material"] == "hospital" else "roof_flat")
                out.append(f'<path d="{path([[x, -y] for x, y in it["footprint"]])}" fill="{FILL[key]}" stroke="#3b3a36" stroke-width="0.8"/>')
            elif it["type"] == "shed":
                out.append(f'<path d="{path([[x, -y] for x, y in it["footprint"]])}" fill="{FILL["shed_roof"]}" '
                           f'fill-opacity="0.9" stroke="#2f3a33" stroke-width="0.8"/>')  # fmt: skip
    out.append(f"<!-- {escape(site['attribution'])}. Artistic interpretation: designed layout, not surveyed. -->")
    out.append("</svg>")

    positions = {}
    for zone_id, layout_id in zones.items():
        area = next(z["area"] for z in layout["zones"] if z["id"] == layout_id)
        zx, zy = centroid(area)
        positions[zone_id] = {"x": round(0.5 + (zx - cx) / sx, 3), "y": round(0.5 - (zy - cy) / sy, 3)}
    return "\n".join(out) + "\n", positions

