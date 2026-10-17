"""World step 4: export the dressed world for the web explorer (runs inside Blender).

    cd pipeline
    uv run python -m vantara_pipeline.blender_bridge execute_code \
        --code "exec(open('C:/Users/mobol/Downloads/animals/world/scripts/export_web.py', encoding='utf-8').read())"

Run after dress_zones.py, in vantara_world.blend. Writes world/publish/
(not in git), laid out like the splat zones so the explorer and the asset
host treat both the same way:

    world/            world.json (manifest), site.gltf, buildings.gltf,
                      plants.gltf (+ .bin, shared .jpg/.png textures),
                      collision.glb
    <zone>/<zone>.json  per-zone metadata (spawn, bounds, flyover path) that
                        points at world/world.json

Textures stay as separate files so every part shares one download. The
Blender materials (world-space box projection, colour variation) are
replaced on export copies by plain glTF materials, with UVs generated in
world metres at each texture's tile size. Plants are exported once per
variant at two levels of detail and placed in the browser as instances.
Coordinates: Blender (x east, y north, z up) -> three.js (x, z, -y).

Also renders a top-down overview map to web/public/map/overview.webp and
updates the map positions in zones.json to match.
"""

import json
import math
import os
import re
import shutil

import bmesh
import bpy
from mathutils import Matrix, Vector

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
WORLD = os.path.join(REPO, "world")
LAYOUT = json.load(open(os.path.join(WORLD, "data", "layout.json"), encoding="utf-8"))
SITE = json.load(open(os.path.join(WORLD, "data", "site.json"), encoding="utf-8"))
OUT = os.path.join(WORLD, "publish")
OUT_WORLD = os.path.join(OUT, "world")
ZONES_JSON = os.path.join(REPO, "zones.json")
MAP_IMAGE = os.path.join(REPO, "web", "public", "map", "overview.webp")
RENDER_MAP = globals().get("RENDER_MAP", True)

GROUND_Y = 0.12  # Vantara grounds (Blender z); the walk fallback plane
EYE_HEIGHT = 1.6
LOD_DISTANCE = 60.0  # metres: plants further than this use LOD1
# role -> (LOD0 faces, LOD1 faces)
PLANT_LODS = {"tree": (30_000, 4_000), "bush": (8_000, 2_000), "shrub": (5_000, 1_200), "rock": (3_000, 500)}
# Web texture budget: colour maps stay 1k, data maps (normal, AO/roughness) go to 512.
DATA_MAP_SIZE = 512
JPEG_QUALITY = 82
DRACO = dict(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
             export_draco_position_quantization=14, export_draco_normal_quantization=10,
             export_draco_texcoord_quantization=12)  # fmt: skip
SITE_COLLECTIONS = ("Terrain", "Vantara (outline from OSM)", "Roads, rail, water (OSM)")

# Explorer zones (zones.json ids) -> layout zone, spawn (Blender x, y), heading (deg clockwise from north).
EXPLORER_ZONES = {
    "elephant-care-centre": ("elephant-care-centre", (-215, 22), 0),
    "big-cat-rescue": ("big-cat-rescue", (206, -112), 0),
    "herbivore-reserve": ("herbivore-reserve", (343, -87), 90),
    "wildlife-hospital": ("wildlife-hospital", (100, -60), -10),
}
# Draw order for coplanar ground layers (higher wins), by source material.
DEPTH_LAYERS = {
    "Ground: dry scrub": 0, "Ground: Vantara landscaped": 1, "Blockout: grass_wild": 2, "Blockout: sand": 2,
    "Blockout: asphalt": 3, "Blockout: paving": 4, "Blockout: mud": 5, "Blockout: pond": 5, "Blockout: pool": 5,
    "Water": 1, "Road: asphalt": 6, "Road: concrete": 6, "Rail ballast": 6,
}  # fmt: skip
# Materials whose texture would come out too dark/dirty without Blender's tint: flat colour + normal map.
FLAT_TINTED = {"Blockout: hospital": (0.78, 0.78, 0.76)}
WALK_ANIMALS = {"elephant": 18.0, "rhino": 14.0, "tiger": 9.0}  # wander radius (m)


def to_three(v):
    return [round(v[0], 3), round(v[2], 3), round(-v[1], 3)]


# ---------------------------------------------------------------- materials


def principled(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat and mat.use_nodes else None


def flat_values(mat):
    """Representative flat colour / roughness / metallic of a (procedural) material."""
    bsdf = principled(mat)
    colour, rough, metal = (0.5, 0.5, 0.5), 0.8, 0.0
    if bsdf:
        base = bsdf.inputs["Base Color"]
        if not base.is_linked:
            colour = tuple(base.default_value[:3])
        else:
            ramp = next((n for n in mat.node_tree.nodes if n.type == "VALTORGB"), None)
            if ramp:
                els = ramp.color_ramp.elements
                colour = tuple(sum(e.color[i] for e in els) / len(els) for i in range(3))
        if not bsdf.inputs["Roughness"].is_linked:
            rough = bsdf.inputs["Roughness"].default_value
        metal = bsdf.inputs["Metallic"].default_value
    return colour, rough, metal


def texture_info(mat):
    """(images by role, tile metres) for a material re-skinned by dress_zones.py, else None."""
    if not mat or not mat.use_nodes or not mat.get("vantara_texture") or mat["vantara_texture"] == "procedural":
        return None
    imgs = {}
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            name = n.image.name
            role = "nor" if "_nor_" in name else "rough" if "_rough_" in name else "diff"
            imgs.setdefault(role, n.image)
    scales = [n.inputs["Scale"].default_value[0] for n in mat.node_tree.nodes if n.type == "MAPPING"]
    return (imgs, 1 / max(scales)) if imgs and scales else None


def chainlink_image():
    img = bpy.data.images.get("chainlink")
    if img:
        return img
    n = 32
    img = bpy.data.images.new("chainlink", n, n, alpha=True)
    px = []
    for j in range(n):
        for i in range(n):
            a = (i + j) % n
            b = (i - j) % n
            wire = min(a, n - a) < 2 or min(b, n - b) < 2
            px += [0.42, 0.43, 0.43, 1.0] if wire else [0.42, 0.43, 0.43, 0.0]
    img.pixels = px
    img.filepath_raw = os.path.join(OUT_WORLD, "chainlink.png")
    img.file_format = "PNG"
    os.makedirs(OUT_WORLD, exist_ok=True)
    img.save()
    return img


def web_material(src):
    """Plain glTF material for an export copy (cached per source material)."""
    name = f"Web: {src.name}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = principled(mat)
    colour, rough, metal = flat_values(src)
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    info = texture_info(src)

    def tex(img, y, colour_data=True):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.location = (-500, y)
        t.image = img
        if not colour_data:
            img.colorspace_settings.name = "Non-Color"
        return t

    if src.name == "Blockout: mesh":
        t = tex(chainlink_image(), 200)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
        bsdf.inputs["Metallic"].default_value = 0.6
        mat["web_tile"] = 0.05
    elif info:
        imgs, tile = info
        mat["web_tile"] = tile
        if src.name in FLAT_TINTED:
            bsdf.inputs["Base Color"].default_value = (*FLAT_TINTED[src.name], 1)
        elif "diff" in imgs:
            nt.links.new(tex(imgs["diff"], 300).outputs["Color"], bsdf.inputs["Base Color"])
        # No roughness map on the web (it barely shows on ground and walls, ~1 MB each).
        bsdf.inputs["Roughness"].default_value = 0.45 if src.name == "Blockout: mud" else 0.88
        if "nor" in imgs:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(tex(imgs["nor"], -300, False).outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if src.name in ("Blockout: pond", "Blockout: pool", "Water"):
        bsdf.inputs["Roughness"].default_value = 0.05
    return mat


# ---------------------------------------------------------------- geometry


def baked_copy(ob, col, depsgraph):
    """World-space mesh copy with modifiers applied, web materials and world-metre UVs."""
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph))
    me.transform(ob.matrix_world)
    me.name = f"web {ob.name}"
    for i, m in enumerate(me.materials):
        me.materials[i] = web_material(m) if m else None
    uv = me.uv_layers.new(name="UVMap") if not me.uv_layers else me.uv_layers[0]
    for poly in me.polygons:
        m = me.materials[poly.material_index] if me.materials else None
        tile = m.get("web_tile", 2.0) if m else 2.0
        n = poly.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if ax == 2:
                u, v = co.x, co.y
            elif ax == 0:
                u, v = co.y, co.z
            else:
                u, v = co.x, co.z
            uv.data[li].uv = (u / tile, v / tile)
    copy = bpy.data.objects.new(ob.name, me)
    col.objects.link(copy)
    return copy


def export_selection(objs, path, **kw):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    opts = dict(
        filepath=path, use_selection=True, export_yup=True, export_apply=True,
        export_cameras=False, export_lights=False, export_animations=False, export_extras=False,
    )  # fmt: skip
    opts.update(kw)
    bpy.ops.export_scene.gltf(**opts)


def collection_meshes(names):
    out = []
    for n in names:
        col = bpy.data.collections.get(n)
        if col:
            out += [o for o in col.all_objects if o.type == "MESH"]
    return out


# ---------------------------------------------------------------- plants


def decimated(src_ob, faces, name, col, offset):
    me = bpy.data.meshes.new_from_object(src_ob)  # without the render-time decimate
    tmp = bpy.data.objects.new("tmp", me)
    col.objects.link(tmp)
    # Collapse stalls on some scans (UV seams), so decimate in passes until on budget.
    for _ in range(4):
        if len(tmp.data.polygons) <= faces * 1.15:
            break
        mod = tmp.modifiers.new("lod", "DECIMATE")
        mod.ratio = max(0.02, faces / len(tmp.data.polygons))
        mod.use_collapse_triangulate = True
        dg = bpy.context.evaluated_depsgraph_get()
        reduced = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
        tmp.modifiers.remove(mod)
        old, tmp.data = tmp.data, reduced
        bpy.data.meshes.remove(old)
    me = tmp.data
    out = me.copy()
    out.transform(src_ob.matrix_world)
    out.transform(Matrix.Translation(-Vector(offset)))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(me)
    ob = bpy.data.objects.new(name, out)
    col.objects.link(ob)
    return ob, len(out.polygons)


def export_plants(col):
    veg = bpy.data.collections.get("Dress: vegetation")
    if not veg:
        return None
    roles = {}
    variants = {}
    for inst in veg.objects:
        src = inst.instance_collection
        if not src:
            continue
        key = src.name.removeprefix("Dress source: ")
        roles[key] = inst.name.split(".")[0]  # instance objects are named by role
        variants.setdefault(key, []).append(
            to_three(inst.location) + [round(inst.rotation_euler.z, 4), round(inst.scale.x, 3)]
        )
    objs, faces = [], {}
    for key in variants:
        src_col = bpy.data.collections[f"Dress source: {key}"]
        src_ob = next(o for o in src_col.objects if o.type == "MESH")
        lod0, lod1 = PLANT_LODS.get(roles[key], (8_000, 1_500))
        a, fa = decimated(src_ob, lod0, f"{key}|lod0", col, src_col.instance_offset)
        b, fb = decimated(src_ob, lod1, f"{key}|lod1", col, src_col.instance_offset)
        objs += [a, b]
        faces[key] = [fa, fb]
    export_selection(objs, os.path.join(OUT_WORLD, "plants.gltf"), export_format="GLTF_SEPARATE",
                     export_texture_dir="", export_image_format="AUTO", **DRACO)  # fmt: skip
    return {
        "file": "plants.gltf",
        "lodDistance": LOD_DISTANCE,
        "variants": {k: {"role": roles[k], "faces": faces[k], "instances": v} for k, v in variants.items()},
    }


# ---------------------------------------------------------------- collision


def export_collision(col, part_objs):
    bm = bmesh.new()
    for ob in part_objs:
        if ob.name.startswith(("Dress: glass", "Dress: trim", "Dress: doors")):
            continue
        me = ob.data
        verts = [bm.verts.new(v.co) for v in me.vertices]
        for poly in me.polygons:
            try:
                bm.faces.new([verts[i] for i in poly.vertices])
            except ValueError:
                pass  # duplicate face
    # Tree trunks and boulders as simple boxes.
    veg = bpy.data.collections.get("Dress: vegetation")
    for inst in veg.objects if veg else []:
        role = inst.name.split(".")[0]
        if role not in ("tree", "rock"):
            continue
        s = inst.scale.x
        half, h = (0.35 * s, 4.0) if role == "tree" else (0.55 * s, 1.0 * s)
        x, y, z = inst.location
        verts = [bm.verts.new((x + dx, y + dy, z + dz)) for dz in (0, h) for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half))]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bm.faces.new([verts[i] for i in f])
    me = bpy.data.meshes.new("collision")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("collision", me)
    col.objects.link(ob)
    export_selection([ob], os.path.join(OUT_WORLD, "collision.glb"), export_format="GLB",
                     export_materials="NONE", export_normals=False)  # fmt: skip
    return len(me.polygons)


# ---------------------------------------------------------------- animals, zones, map


def inside(pt, poly):
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def seg_dist(p, a, b):
    p, a, b = Vector(p), Vector(a), Vector(b)
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def edge_dist(p, poly):
    return min(seg_dist(p, a, b) for a, b in zip(poly, poly[1:] + poly[:1]))


def animal_paths():
    """Loop of three waypoints per placed animal, kept inside its yard and out of the water."""
    col = bpy.data.collections.get("Dress: animals")
    surfaces = [it["polygon"] for z in LAYOUT["zones"] for it in z["items"] if it["type"] == "surface"]
    water = [it["polygon"] for z in LAYOUT["zones"] for it in z["items"] if it["type"] == "water"]
    out = []
    for i, inst in enumerate(col.objects if col else []):
        kind = inst.name.split(": ")[1].split(".")[0]
        p = (inst.location.x, inst.location.y)
        home = next((s for s in surfaces if inside(p, s)), None)
        pts = [p]
        r = WALK_ANIMALS.get(kind, 10.0)
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
        out.append({
            "animal": kind,
            "path": [[round(x, 2), round(-y, 2)] for x, y in pts],
            "idleSeconds": [6, 16] if kind == "elephant" else [5, 14],
        })  # fmt: skip
    return out


def lighting():
    sun = bpy.data.objects.get("Sun")
    d = (sun.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized() if sun else Vector((0.3, -0.5, 0.8)).normalized()
    return {"direction": to_three(d), "elevationDeg": round(math.degrees(math.asin(d.z)), 1)}


def zone_meta(zone_id, layout_id, spawn, heading, sun_dir, sizes):
    area = next(z["area"] for z in LAYOUT["zones"] if z["id"] == layout_id)
    xs = [p[0] for p in area]
    ys = [p[1] for p in area]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    # Flyover: a loop around the zone 12 m up, inset from its edge.
    path = []
    for k in range(10):
        a = 2 * math.pi * k / 10
        rx, ry = (max(xs) - min(xs)) * 0.38, (max(ys) - min(ys)) * 0.38
        path.append(to_three((cx + rx * math.cos(a), cy + ry * math.sin(a), 12.0)))
    m = 80
    lo = to_three((min(xs) - m, max(ys) + m, -5))
    hi = to_three((max(xs) + m, min(ys) - m, 60))
    return {
        "zone": zone_id,
        "units": "m",
        "kind": "world",
        "world": {"manifest": "world/world.json"},
        "groundY": GROUND_Y,
        "files": {"desktop": "", "mobile": "", "collision": ""},
        "sizesMB": sizes,
        "splats": {},
        "bounds": {"min": [lo[0], lo[1], lo[2]], "max": [hi[0], hi[1], hi[2]]},
        "spawn": {"position": to_three((spawn[0], spawn[1], GROUND_Y + EYE_HEIGHT)), "yawDeg": -heading},
        "eyeHeight": EYE_HEIGHT,
        "cameraPath": path,
        "fovY": 60,
        "north": {"deg": 0, "known": True},
        "lighting": {
            "ambient": [0.55, 0.6, 0.68],
            "sun": {"direction": sun_dir, "color": [2.6, 2.45, 2.25]},
            "estimated": False,
        },
    }


def render_map():
    """Top-down orthographic overview for the explorer's map, plus zone positions on it (0..1)."""
    scene = bpy.context.scene
    xs = [p[0] for p in SITE["outline"]]
    ys = [p[1] for p in SITE["outline"]]
    w, h = 2048, 1536
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span_x = max(max(xs) - min(xs), (max(ys) - min(ys)) * w / h) * 1.08
    span_y = span_x * h / w
    cam_data = bpy.data.cameras.new("Map")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span_x
    cam_data.clip_start, cam_data.clip_end = 1, 2000
    cam = bpy.data.objects.new("Map camera", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (cx, cy, 800)
    old = (scene.camera, scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
           scene.render.filepath, scene.render.image_settings.file_format)  # fmt: skip
    labels = bpy.data.collections.get("Zone labels")
    if labels:
        labels.hide_render = True
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = w, h, 100
    scene.render.image_settings.file_format = "WEBP"
    scene.render.image_settings.quality = 82
    os.makedirs(os.path.dirname(MAP_IMAGE), exist_ok=True)
    scene.render.filepath = MAP_IMAGE
    bpy.ops.render.render(write_still=True)
    (scene.camera, scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
     scene.render.filepath, scene.render.image_settings.file_format) = old  # fmt: skip
    if labels:
        labels.hide_render = False
    bpy.data.objects.remove(cam, do_unlink=True)
    positions = {}
    for zone_id, (layout_id, _, _) in EXPLORER_ZONES.items():
        area = next(z["area"] for z in LAYOUT["zones"] if z["id"] == layout_id)
        zx = sum(p[0] for p in area) / len(area)
        zy = sum(p[1] for p in area) / len(area)
        positions[zone_id] = {"x": round(0.5 + (zx - cx) / span_x, 3), "y": round(0.5 - (zy - cy) / span_y, 3)}
    return positions


def update_zones_json(positions):
    data = json.load(open(ZONES_JSON, encoding="utf-8"))
    for z in data["zones"]:
        if z["id"] in positions:
            z["map"] = positions[z["id"]]
    data["map"] = {"image": "/map/overview.webp", "width": 2048, "height": 1536}
    with open(ZONES_JSON, "w", encoding="utf-8", newline="\n") as f:
        f.write(compact_json(data))


def compact_json(data):
    """indent=2, but short flat objects and arrays on one line (the file's hand-written style)."""

    def fold(m, open_, close, pad):
        items = ", ".join(x.strip() for x in m.group(1).split(",\n"))
        line = f"{open_}{pad}{items}{pad}{close}"
        return line if len(line) <= 60 else m.group(0)

    text = json.dumps(data, indent=2, ensure_ascii=False)
    text = re.sub(r"\[\n\s+([^\[\]{}]*?)\n\s+\]", lambda m: fold(m, "[", "]", ""), text)
    text = re.sub(r"\{\n\s+([^\[\]{}]*?)\n\s+\}", lambda m: fold(m, "{", "}", " "), text)
    return text + "\n"


def shrink_textures():
    """Data maps to DATA_MAP_SIZE; JPEGs re-encoded at JPEG_QUALITY. PNGs (alpha) keep their size."""
    for f in os.listdir(OUT_WORLD):
        path = os.path.join(OUT_WORLD, f)
        ext = os.path.splitext(f)[1].lower()
        if ext not in (".jpg", ".png") or f == "chainlink.png":
            continue
        img = bpy.data.images.load(path)
        try:
            w, h = img.size
            data_map = any(k in f for k in ("_nor_", "_arm_", "_rough_"))
            if data_map and max(w, h) > DATA_MAP_SIZE:
                img.scale(DATA_MAP_SIZE, DATA_MAP_SIZE * h // w)
            elif ext == ".png":
                continue
            img.file_format = "JPEG" if ext == ".jpg" else "PNG"
            img.save(filepath=path, quality=JPEG_QUALITY)
        finally:
            bpy.data.images.remove(img)


# ---------------------------------------------------------------- main


def export():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT_WORLD)
    scene = bpy.context.scene
    col = bpy.data.collections.new("Export tmp")
    scene.collection.children.link(col)
    dg = bpy.context.evaluated_depsgraph_get()
    try:
        site = [baked_copy(o, col, dg) for o in collection_meshes(SITE_COLLECTIONS)]
        zone_cols = [c.name for c in bpy.data.collections if c.name.startswith("Zone: ")]
        buildings = [baked_copy(o, col, dg) for o in collection_meshes(zone_cols + ["Dress: building detail"])]
        common = dict(export_format="GLTF_SEPARATE", export_texture_dir="", export_image_format="AUTO", **DRACO)
        export_selection(site, os.path.join(OUT_WORLD, "site.gltf"), **common)
        export_selection(buildings, os.path.join(OUT_WORLD, "buildings.gltf"), **common)
        plants = export_plants(col)
        collision_faces = export_collision(col, site + buildings)
    finally:
        for o in list(col.objects):
            me = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)
        bpy.data.collections.remove(col)
        for m in [m for m in bpy.data.materials if m.name.startswith("Web: ")]:
            bpy.data.materials.remove(m)
        bpy.data.orphans_purge(do_recursive=True)

    shrink_textures()
    files = sorted(os.listdir(OUT_WORLD))
    sizes = {f: os.path.getsize(os.path.join(OUT_WORLD, f)) for f in files}
    total = sum(sizes.values())
    sun = lighting()
    manifest = {
        "format": "vantara-world",
        "version": 1,
        "note": "Artistic interpretation: designed layout inside Vantara's mapped outline, not surveyed.",
        "attribution": [SITE["attribution"], "Textures and plants: Poly Haven (polyhaven.com), CC0",
                        "Animals: CC0 placeholders (see /models/CREDITS.md)"],
        "units": "m",
        "groundY": GROUND_Y,
        "parts": [{"id": "site", "file": "site.gltf"}, {"id": "buildings", "file": "buildings.gltf"}],
        "plants": plants,
        "collision": "collision.glb",
        "depthLayers": {f"Web: {k}": v for k, v in DEPTH_LAYERS.items()},
        "sun": sun,
        "animals": animal_paths(),
        "bytes": total,
    }  # fmt: skip
    with open(os.path.join(OUT_WORLD, "world.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
    mb = {"world": round(total / 1e6, 2)}
    for zone_id, (layout_id, spawn, heading) in EXPLORER_ZONES.items():
        os.makedirs(os.path.join(OUT, zone_id))
        with open(os.path.join(OUT, zone_id, f"{zone_id}.json"), "w", encoding="utf-8") as f:
            json.dump(zone_meta(zone_id, layout_id, spawn, heading, sun["direction"], mb), f, indent=1)
    positions = render_map() if RENDER_MAP else None
    if positions:
        update_zones_json(positions)
    big = sorted(sizes.items(), key=lambda kv: -kv[1])[:8]
    print(f"world: {len(files)} files, {total / 1e6:.1f} MB; collision faces {collision_faces}")
    print("largest:", [(k, round(v / 1e6, 2)) for k, v in big])
    print("plants:", {k: (v["faces"], len(v["instances"])) for k, v in (plants or {}).get("variants", {}).items()})
    print("animals:", len(manifest["animals"]), "| map positions:", positions)


export()
