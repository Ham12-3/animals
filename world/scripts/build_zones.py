"""World step 2: build the zone blockouts from layout.json (runs inside Blender).

    cd pipeline
    uv run python -m vantara_pipeline.blender_bridge execute_code \
        --code "exec(open('../world/scripts/build_zones.py', encoding='utf-8').read())"

Run after build_site_base.py, in vantara_world.blend. Replaces the "Zone: ..."
collections (and the zone cameras) and leaves the site base alone. Blockout
level: simple honest shapes (footprints, roofs, posts, fences, water) to judge
layout and scale; step 3 dresses them with real materials and assets.
"""

import json
import math
import os

import bmesh
import bpy
from mathutils import Vector

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
LAYOUT = json.load(open(os.path.join(REPO, "world", "data", "layout.json"), encoding="utf-8"))

# Heights above the ground plane (m); the site base sits at 0.10-0.22.
Z = {"grass_wild": 0.135, "sand": 0.14, "asphalt": 0.145, "paving": 0.15, "water": 0.16, "label": 0.4}

# (base colour, roughness, alpha)
MATERIALS = {
    "building": ((0.62, 0.57, 0.48), 0.85, 1.0),
    "hospital": ((0.86, 0.87, 0.86), 0.6, 1.0),
    "roof_gable": ((0.42, 0.24, 0.17), 0.8, 1.0),
    "roof_flat": ((0.45, 0.45, 0.44), 0.9, 1.0),
    "shed_roof": ((0.30, 0.38, 0.33), 0.55, 1.0),
    "post": ((0.33, 0.27, 0.20), 0.9, 1.0),
    "steel": ((0.18, 0.18, 0.18), 0.5, 1.0),
    "mesh": ((0.10, 0.10, 0.10), 0.6, 0.35),
    "sand": ((0.66, 0.55, 0.38), 0.95, 1.0),
    "paving": ((0.60, 0.58, 0.54), 0.85, 1.0),
    "asphalt": ((0.09, 0.09, 0.09), 0.75, 1.0),
    "grass_wild": ((0.25, 0.32, 0.12), 0.95, 1.0),
    "pool": ((0.10, 0.42, 0.48), 0.05, 1.0),
    "pond": ((0.08, 0.15, 0.13), 0.05, 1.0),
    "mud": ((0.22, 0.16, 0.11), 0.35, 1.0),
    "label": ((0.97, 0.97, 0.97), 0.5, 1.0),
}


def material(key):
    name = f"Blockout: {key}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    color, rough, alpha = MATERIALS[key]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    if alpha < 1:
        bsdf.inputs["Alpha"].default_value = alpha
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    if key in ("pool", "pond"):
        bsdf.inputs["IOR"].default_value = 1.33
    return mat


class Builder:
    """Collects geometry per material into one mesh per (zone, material)."""

    def __init__(self, col, zone_id):
        self.col, self.zone_id, self.meshes = col, zone_id, {}

    def bm(self, key):
        if key not in self.meshes:
            self.meshes[key] = bmesh.new()
        return self.meshes[key]

    def finish(self):
        for key, bm in self.meshes.items():
            me = bpy.data.meshes.new(f"{self.zone_id}: {key}")
            bm.to_mesh(me)
            bm.free()
            me.materials.append(material(key))
            ob = bpy.data.objects.new(f"{self.zone_id}: {key}", me)
            self.col.objects.link(ob)


def face(bm, pts, z):
    verts = [bm.verts.new((x, y, z)) for x, y in pts]
    bm.faces.new(verts)


def prism(bm, pts, z0, z1):
    """Vertical extrusion of a footprint (closed box)."""
    lo = [bm.verts.new((x, y, z0)) for x, y in pts]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))


def box(bm, cx, cy, w, d, z0, z1, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    pts = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]
    prism(bm, pts, z0, z1)


def rect_axes(pts):
    """Centre, long-axis unit vector, long length, short length of a 4-point rectangle."""
    a, b, c, d = (Vector(p) for p in pts)
    e1, e2 = b - a, d - a
    centre = (a + c) / 2
    if e1.length >= e2.length:
        return centre, e1.normalized(), e1.length, e2.length
    return centre, e2.normalized(), e2.length, e1.length


def gable_roof(bm, pts, z, pitch=0.28):
    """Ridge along the long axis, rise = pitch * short side."""
    centre, axis, long_len, short_len = rect_axes(pts)
    side = Vector((-axis.y, axis.x))
    rise = pitch * short_len
    over = 0.6  # eaves overhang
    hl, hs = long_len / 2 + over, short_len / 2 + over
    eave = [centre + axis * sx * hl + side * sy * hs for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    ridge = [centre - axis * hl, centre + axis * hl]
    e = [bm.verts.new((p.x, p.y, z)) for p in eave]
    r = [bm.verts.new((p.x, p.y, z + rise)) for p in ridge]
    bm.faces.new((e[0], e[1], r[1], r[0]))
    bm.faces.new((e[3], r[0], r[1], e[2]))
    bm.faces.new((e[0], r[0], e[3]))
    bm.faces.new((e[1], e[2], r[1]))


def build_building(b, item):
    pts, h = item["footprint"], item["height"]
    prism(b.bm(item["material"]), pts, 0.15, h)
    if item["roof"] == "gable":
        gable_roof(b.bm("roof_gable"), pts, h)
    else:
        # Parapet-less flat roof slab, slightly darker than the walls.
        prism(b.bm("roof_flat"), pts, h, h + 0.25)


def build_shed(b, item):
    pts, h = item["footprint"], item["height"]
    centre, axis, long_len, short_len = rect_axes(pts)
    side = Vector((-axis.y, axis.x))
    rot = math.atan2(axis.y, axis.x)
    n = max(2, round(long_len / 8) + 1)
    for i in range(n):
        t = -long_len / 2 + long_len * i / (n - 1)
        for sgn in (-1, 1):
            p = centre + axis * t + side * sgn * (short_len / 2 - 0.3)
            box(b.bm("steel"), p.x, p.y, 0.3, 0.3, 0.15, h, rot)
    gable_roof(b.bm("shed_roof"), pts, h, pitch=0.15)


def build_fence(b, item):
    pts = [Vector(p) for p in item["points"]]
    if item.get("closed", True):
        pts = pts + pts[:1]
    h, style = item["height"], item["style"]
    spacing = 3.0 if style == "post_rail" else 4.0
    for a, c in zip(pts, pts[1:]):
        seg = c - a
        length = seg.length
        if length < 0.1:
            continue
        d = seg / length
        rot = math.atan2(d.y, d.x)
        n = max(1, round(length / spacing))
        for i in range(n + 1):
            p = a + d * (length * i / n)
            box(b.bm("post" if style == "post_rail" else "steel"), p.x, p.y, 0.15, 0.15, 0.15, h, rot)
        mid = (a + c) / 2
        if style == "post_rail":
            for frac in (0.45, 0.85):
                z = 0.15 + h * frac
                box(b.bm("post"), mid.x, mid.y, length, 0.1, z - 0.06, z + 0.06, rot)
        else:
            box(b.bm("mesh"), mid.x, mid.y, length, 0.04, 0.15, h, rot)


def build_water(b, item):
    kind, pts = item["kind"], item["polygon"]
    if kind == "pool":
        face(b.bm("pool"), pts, Z["water"])
        # Coping ring around the pool.
        centre, axis, long_len, short_len = rect_axes(pts)
        rot = math.atan2(axis.y, axis.x)
        side = Vector((-axis.y, axis.x))
        for sgn in (-1, 1):
            p = centre + side * sgn * (short_len / 2 + 0.4)
            box(b.bm("paving"), p.x, p.y, long_len + 1.6, 0.8, 0.15, 0.4, rot)
            q = centre + axis * sgn * (long_len / 2 + 0.4)
            box(b.bm("paving"), q.x, q.y, 0.8, short_len, 0.15, 0.4, rot)
    else:
        face(b.bm("mud" if kind == "mud" else "pond"), pts, Z["water"])


def label(col, zone):
    xs = [p[0] for p in zone["area"]]
    ys = [p[1] for p in zone["area"]]
    curve = bpy.data.curves.new(f"Label {zone['id']}", "FONT")
    curve.body = zone["name"].upper()
    curve.size = 9
    curve.align_x = "CENTER"
    ob = bpy.data.objects.new(f"Label: {zone['name']}", curve)
    ob.location = (sum(xs) / len(xs), sum(ys) / len(ys), Z["label"])
    ob.data.materials.append(material("label"))
    col.objects.link(ob)


def remove_previous(scene):
    for col in list(bpy.data.collections):
        if col.name.startswith("Zone: ") or col.name == "Zone labels":
            for ob in list(col.objects):
                bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.collections.remove(col)
    for ob in list(bpy.data.objects):
        if ob.name.startswith("Cam: "):
            bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)


def zone_cameras(scene):
    env = bpy.data.collections.get("Sky, sun, cameras") or scene.collection

    def cam(name, loc, target, lens=26):
        data = bpy.data.cameras.new(name)
        data.lens = lens
        data.clip_start = 0.3 if loc[2] < 10 else 2.0
        data.clip_end = 12000
        ob = bpy.data.objects.new(name, data)
        env.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    cam("Cam: Aerial close", (-260, -430, 230), (-20, 0, 0), 30)
    cam("Cam: Elephant yards", (-215, 22, 1.7), (-215, 100, 4), 24)
    cam("Cam: Big cat path", (206, -112, 1.7), (206, 60, 2.5), 24)
    cam("Cam: Hospital approach", (100, -60, 1.7), (80, 30, 6), 26)
    cam("Cam: Herbivore paddock", (354, -122, 1.7), (395, -88, 1.0), 26)


def build():
    scene = bpy.context.scene
    remove_previous(scene)
    labels = bpy.data.collections.new("Zone labels")
    scene.collection.children.link(labels)
    for zone in LAYOUT["zones"]:
        col = bpy.data.collections.new(f"Zone: {zone['name']}")
        scene.collection.children.link(col)
        b = Builder(col, zone["id"])
        for item in zone["items"]:
            kind = item["type"]
            if kind == "building":
                build_building(b, item)
            elif kind == "shed":
                build_shed(b, item)
            elif kind == "surface":
                face(b.bm(item["material"]), item["polygon"], Z[item["material"]])
            elif kind == "water":
                build_water(b, item)
            elif kind == "fence":
                build_fence(b, item)
        b.finish()
        label(labels, zone)
    zone_cameras(scene)
    bpy.ops.wm.save_mainfile()
    counts = {z["id"]: len(z["items"]) for z in LAYOUT["zones"]}
    print("built zones:", counts, "| objects in file:", len(bpy.data.objects))


build()
