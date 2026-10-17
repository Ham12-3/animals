"""World step 3: dress the zone blockouts (runs inside Blender).

    cd pipeline
    uv run python -m vantara_pipeline.blender_bridge execute_code \
        --code "exec(open('../world/scripts/dress_zones.py', encoding='utf-8').read())"

Run after build_zones.py, in vantara_world.blend. Replaces the "Dress: ..."
collections and re-skins the blockout materials:

- surface materials (ground, sand, grass, asphalt, paving, plaster, roofs, mud)
  use CC0 Poly Haven textures from world/assets/polyhaven/ when present, with
  large-scale colour variation so tiling doesn't show; procedural fallback
  otherwise
- water shader for ponds and pools, wire-mesh fences
- building detail: windows per storey, doors, parapets, rooftop plant,
  hospital entrance canopy
- trees, shrubs, grass and rocks scattered (seeded) where the layout leaves
  room, if the Poly Haven models are downloaded
- the CC0 placeholder animals (web/public/models) placed in their zones
"""

import glob
import json
import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
WORLD = os.path.join(REPO, "world")
LAYOUT = json.load(open(os.path.join(WORLD, "data", "layout.json"), encoding="utf-8"))
SITE = json.load(open(os.path.join(WORLD, "data", "site.json"), encoding="utf-8"))
TEXTURES = os.path.join(WORLD, "assets", "polyhaven", "textures")
MODELS = os.path.join(WORLD, "assets", "polyhaven", "models")
ANIMALS = os.path.join(REPO, "web", "public", "models")
SEED = 17
STOREY = 3.6

# material name -> (Poly Haven texture, tile size m, fallback colour, saturation, value, roughness offset)
SURFACES = {
    "Ground: Vantara landscaped": ("dry_ground_01", 4.0, (0.40, 0.32, 0.22), 0.9, 1.0, 0.0),
    "Ground: dry scrub": ("dry_ground_01", 5.0, (0.36, 0.29, 0.20), 0.8, 0.85, 0.0),
    "Blockout: sand": ("sand_01", 3.0, (0.66, 0.55, 0.38), 1.0, 1.05, 0.0),
    "Blockout: grass_wild": ("withered_grass", 3.0, (0.30, 0.30, 0.14), 1.0, 1.0, 0.0),
    "Blockout: asphalt": ("asphalt_02", 6.0, (0.09, 0.09, 0.09), 1.0, 1.0, 0.0),
    "Road: asphalt": ("asphalt_02", 6.0, (0.09, 0.09, 0.09), 1.0, 1.0, 0.0),
    "Blockout: paving": ("red_sandstone_pavement", 3.0, (0.60, 0.50, 0.42), 1.0, 1.0, 0.0),
    "Blockout: hospital": ("white_plaster_02", 4.0, (0.86, 0.87, 0.86), 0.25, 1.5, 0.0),
    "Road: concrete": ("procedural", 4.0, (0.50, 0.48, 0.44), 1.0, 1.0, 0.0),  # no texture downloaded
    "Blockout: building": ("yellow_plaster", 2.5, (0.62, 0.57, 0.48), 0.8, 1.0, 0.0),
    "Perimeter wall": ("yellow_plaster", 2.5, (0.62, 0.57, 0.48), 0.7, 0.95, 0.0),
    "Blockout: shed_roof": ("corrugated_iron_02", 2.0, (0.30, 0.38, 0.33), 1.0, 1.0, 0.0),
    "Blockout: roof_gable": ("clay_roof_tiles", 2.0, (0.42, 0.24, 0.17), 1.0, 1.0, 0.0),
    "Blockout: mud": ("brown_mud_02", 3.0, (0.22, 0.16, 0.11), 1.0, 0.8, -0.35),
}

# Poly Haven model -> (role, scale range). Each mesh in a file is a separate
# variant. island_tree_02 is a 3.4 m tree, scaled up to a 6-8 m shade tree
# (neem/khejri size). grass_bermuda_01 (10 cm tufts) is too small to read at
# site scale, so grass comes from the withered_grass ground texture instead.
PLANTS = {
    "island_tree_02": ("tree", (1.8, 2.4)),
    "searsia_lucida": ("bush", (1.0, 1.6)),
    "shrub_02": ("shrub", (0.8, 1.3)),
    "wild_rooibos_bush": ("shrub", (1.6, 2.6)),
    "boulder_01": ("rock", (0.7, 1.4)),
    "namaqualand_boulder_02": ("rock", (0.6, 1.2)),
}
# Meshes above this many faces get a Decimate modifier (renders hundreds of instances).
MAX_FACES = 200_000

# (animal, x, y, heading deg; 0 = facing north)
ANIMAL_SPOTS = [
    ("elephant", -275, -60, 200), ("elephant", -250, -35, 120), ("elephant", -175, -78, 60),
    ("elephant", -120, -20, 300), ("elephant", -225, 64, 170), ("elephant", -192, 82, 230),
    ("tiger", 190, -100, 250), ("tiger", 160, -40, 30), ("tiger", 248, 5, 300),
    ("tiger", 225, 92, 140), ("tiger", 296, -110, 80),
    ("rhino", 372, -108, 70), ("rhino", 412, -70, 250), ("rhino", 380, 12, 200), ("rhino", 400, 92, 110),
]


# ---------------------------------------------------------------- helpers


def node(nt, kind, x, y, **props):
    n = nt.nodes.new(kind)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def texture_files(asset):
    d = os.path.join(TEXTURES, asset)
    found = {}
    for key, pat in (("diff", "_diff_"), ("nor", "_nor_gl_"), ("rough", "_rough_")):
        hits = glob.glob(os.path.join(d, f"*{pat}*"))
        if hits:
            found[key] = hits[0]
    return found if "diff" in found else None


def reskin(mat, spec):
    """Rebuild a surface material: Poly Haven maps (box-projected in world metres) or noise fallback."""
    asset, tile, colour, sat, val, rough_off = spec
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 900, 0)
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", 600, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    coord = node(nt, "ShaderNodeTexCoord", -900, 0)
    mapping = node(nt, "ShaderNodeMapping", -700, 0)
    mapping.inputs["Scale"].default_value = (1 / tile,) * 3
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    # Large-scale brightness variation (40-80 m blotches) hides tile repeats.
    macro = node(nt, "ShaderNodeTexNoise", -700, 400)
    macro.inputs["Scale"].default_value = 0.02
    macro.inputs["Detail"].default_value = 3
    nt.links.new(coord.outputs["Object"], macro.inputs["Vector"])
    vrange = node(nt, "ShaderNodeMapRange", -450, 400)
    vrange.inputs["To Min"].default_value = 0.82 * val
    vrange.inputs["To Max"].default_value = 1.15 * val
    nt.links.new(macro.outputs["Fac"], vrange.inputs["Value"])
    hsv = node(nt, "ShaderNodeHueSaturation", 300, 200)
    hsv.inputs["Saturation"].default_value = sat
    nt.links.new(vrange.outputs["Result"], hsv.inputs["Value"])
    nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])

    files = texture_files(asset)
    if files:
        def image(path, x, y, colour_data):
            tex = node(nt, "ShaderNodeTexImage", x, y, projection="BOX", projection_blend=0.3)
            tex.image = bpy.data.images.load(path, check_existing=True)
            if not colour_data:
                tex.image.colorspace_settings.name = "Non-Color"
            nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
            return tex

        diff = image(files["diff"], -300, 200, True)
        # Anti-tiling: a second, larger and rotated sample of the colour map,
        # blended in by a 6-8 m noise mask, breaks the repeat grid on open ground.
        mapping2 = node(nt, "ShaderNodeMapping", -700, 700)
        mapping2.inputs["Scale"].default_value = (1 / (tile * 2.7),) * 3
        mapping2.inputs["Rotation"].default_value = (0, 0, 0.61)
        nt.links.new(coord.outputs["Object"], mapping2.inputs["Vector"])
        diff2 = node(nt, "ShaderNodeTexImage", -300, 700, projection="BOX", projection_blend=0.3)
        diff2.image = diff.image
        nt.links.new(mapping2.outputs["Vector"], diff2.inputs["Vector"])
        mask = node(nt, "ShaderNodeTexNoise", -700, 1000)
        mask.inputs["Scale"].default_value = 0.15
        nt.links.new(coord.outputs["Object"], mask.inputs["Vector"])
        soft = node(nt, "ShaderNodeMapRange", -450, 1000)
        soft.inputs["From Min"].default_value = 0.4
        soft.inputs["From Max"].default_value = 0.6
        nt.links.new(mask.outputs["Fac"], soft.inputs["Value"])
        mix = node(nt, "ShaderNodeMix", 0, 450, data_type="RGBA")
        sock = lambda socks, ident: next(x for x in socks if x.identifier == ident)  # noqa: E731
        nt.links.new(soft.outputs["Result"], sock(mix.inputs, "Factor_Float"))
        nt.links.new(diff.outputs["Color"], sock(mix.inputs, "A_Color"))
        nt.links.new(diff2.outputs["Color"], sock(mix.inputs, "B_Color"))
        nt.links.new(sock(mix.outputs, "Result_Color"), hsv.inputs["Color"])
        if "rough" in files:
            r = image(files["rough"], -300, -100, False)
            add = node(nt, "ShaderNodeMath", 300, -100, operation="ADD", use_clamp=True)
            add.inputs[1].default_value = rough_off
            nt.links.new(r.outputs["Color"], add.inputs[0])
            nt.links.new(add.outputs["Value"], bsdf.inputs["Roughness"])
        else:
            bsdf.inputs["Roughness"].default_value = 0.9 + rough_off
        if "nor" in files:
            n = image(files["nor"], -300, -400, False)
            nm = node(nt, "ShaderNodeNormalMap", 300, -400)
            nt.links.new(n.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        mat["vantara_texture"] = asset
    else:
        # Procedural fallback: fine noise on the flat colour.
        fine = node(nt, "ShaderNodeTexNoise", -450, 150)
        fine.inputs["Scale"].default_value = 3.0
        fine.inputs["Detail"].default_value = 8
        nt.links.new(mapping.outputs["Vector"], fine.inputs["Vector"])
        ramp = node(nt, "ShaderNodeValToRGB", -200, 150)
        ramp.color_ramp.elements[0].color = (*[c * 0.8 for c in colour], 1)
        ramp.color_ramp.elements[1].color = (*[min(1, c * 1.15) for c in colour], 1)
        nt.links.new(fine.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], hsv.inputs["Color"])
        bsdf.inputs["Roughness"].default_value = 0.9 + rough_off
        mat["vantara_texture"] = "procedural"


def water_material(mat, deep, shallow):
    """Dark, slightly rippled water: reflects the sky without going white."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 700, 0)
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", 400, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    coord = node(nt, "ShaderNodeTexCoord", -800, 0)
    ripples = node(nt, "ShaderNodeTexNoise", -550, -200)
    ripples.inputs["Scale"].default_value = 1.5
    ripples.inputs["Detail"].default_value = 6
    nt.links.new(coord.outputs["Object"], ripples.inputs["Vector"])
    bump = node(nt, "ShaderNodeBump", 100, -200)
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(ripples.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    tint = node(nt, "ShaderNodeTexNoise", -550, 200)
    tint.inputs["Scale"].default_value = 0.08
    nt.links.new(coord.outputs["Object"], tint.inputs["Vector"])
    ramp = node(nt, "ShaderNodeValToRGB", -200, 200)
    ramp.color_ramp.elements[0].color = (*deep, 1)
    ramp.color_ramp.elements[1].color = (*shallow, 1)
    nt.links.new(tint.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.06
    bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Specular IOR Level"].default_value = 0.5


def mesh_fence_material(mat):
    """Chain-link look: thin diagonal wires, mostly see-through."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 700, 0)
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", 400, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (0.32, 0.33, 0.33, 1)
    bsdf.inputs["Metallic"].default_value = 0.8
    bsdf.inputs["Roughness"].default_value = 0.45
    coord = node(nt, "ShaderNodeTexCoord", -900, 0)
    sep = node(nt, "ShaderNodeSeparateXYZ", -700, 0)
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    # Along-fence coordinate: x + y works for any wall direction (no UVs needed).
    along = node(nt, "ShaderNodeMath", -500, 100, operation="ADD")
    nt.links.new(sep.outputs["X"], along.inputs[0])
    nt.links.new(sep.outputs["Y"], along.inputs[1])
    wires = []  # two diagonal wire families, 5 cm pitch
    for i, op in enumerate(("ADD", "SUBTRACT")):
        m = node(nt, "ShaderNodeMath", -300, 200 - 200 * i, operation=op)
        nt.links.new(along.outputs["Value"], m.inputs[0])
        nt.links.new(sep.outputs["Z"], m.inputs[1])
        wave = node(nt, "ShaderNodeMath", -100, 200 - 200 * i, operation="PINGPONG")
        nt.links.new(m.outputs["Value"], wave.inputs[0])
        wave.inputs[1].default_value = 0.025
        wires.append(wave)
    lo = node(nt, "ShaderNodeMath", 50, 100, operation="MINIMUM")
    nt.links.new(wires[0].outputs["Value"], lo.inputs[0])
    nt.links.new(wires[1].outputs["Value"], lo.inputs[1])
    edge = node(nt, "ShaderNodeMapRange", 200, 100)
    edge.inputs["From Min"].default_value = 0.0
    edge.inputs["From Max"].default_value = 0.0025
    edge.inputs["To Min"].default_value = 1.0
    edge.inputs["To Max"].default_value = 0.0  # wires opaque, gaps clear
    nt.links.new(lo.outputs["Value"], edge.inputs["Value"])
    nt.links.new(edge.outputs["Result"], bsdf.inputs["Alpha"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"


def flat_material(name, colour, rough, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def prism(bm, pts, z0, z1):
    lo = [bm.verts.new((x, y, z0)) for x, y in pts]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))


def oriented_box(bm, centre, along, w, d, z0, z1):
    """Box centred at centre (2D), w along `along`, d across it."""
    side = Vector((-along.y, along.x))
    pts = [centre + along * sx * w / 2 + side * sy * d / 2 for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    prism(bm, [(p.x, p.y) for p in pts], z0, z1)


def link_mesh(col, name, bm, mat):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


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


def poly_dist(p, poly, closed=True):
    pts = poly + poly[:1] if closed else poly
    return min(seg_dist(p, a, b) for a, b in zip(pts, pts[1:]))


def new_collection(name, parent=None):
    col = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(col)
    return col


# ---------------------------------------------------------------- dressing


def remove_previous():
    for col in list(bpy.data.collections):
        if col.name.startswith("Dress"):
            for ob in list(col.objects):
                bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.collections.remove(col)
    for ob in list(bpy.data.objects):
        if ob.name.startswith("Cam: Dress"):
            bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)


def reskin_all():
    for name, spec in SURFACES.items():
        mat = bpy.data.materials.get(name)
        if mat:
            reskin(mat, spec)
    for name, deep, shallow in (
        ("Blockout: pond", (0.07, 0.08, 0.05), (0.16, 0.15, 0.09)),  # murky, silt-green
        ("Water", (0.02, 0.05, 0.05), (0.05, 0.09, 0.08)),
        ("Blockout: pool", (0.03, 0.22, 0.26), (0.10, 0.38, 0.42)),
    ):
        mat = bpy.data.materials.get(name)
        if mat:
            water_material(mat, deep, shallow)
    mesh = bpy.data.materials.get("Blockout: mesh")
    if mesh:
        mesh_fence_material(mesh)
    return {n: bpy.data.materials[n].get("vantara_texture") for n in SURFACES if n in bpy.data.materials}


def building_details(parent):
    col = new_collection("Dress: building detail", parent)
    glass = flat_material("Dress: glass", (0.035, 0.05, 0.06), 0.06)
    door = flat_material("Dress: door steel", (0.22, 0.24, 0.25), 0.45, 0.6)
    plant = flat_material("Dress: rooftop plant", (0.55, 0.56, 0.55), 0.5, 0.3)
    sill = flat_material("Dress: concrete trim", (0.55, 0.53, 0.5), 0.8)
    meshes = {"glass": bmesh.new(), "door": bmesh.new(), "plant": bmesh.new(), "trim": bmesh.new()}
    walls = {}  # wall material key -> bmesh (parapets)
    count = {"windows": 0, "doors": 0}
    for zone in LAYOUT["zones"]:
        for item in zone["items"]:
            if item["type"] != "building":
                continue
            pts = [Vector(p) for p in item["footprint"]]
            h, name = item["height"], item["name"]
            night_house = name.lower().startswith(("night house", "large enclosure night"))
            # Footprints are counter-clockwise, so the outward normal of edge a->b is (dy, -dx).
            edges = []
            for a, b in zip(pts, pts[1:] + pts[:1]):
                d = (b - a)
                edges.append((a, b, d.length, d.normalized(), Vector((d.normalized().y, -d.normalized().x))))
            # Door on the longest south-facing wall (or a slide door for night houses).
            front = min(edges, key=lambda e: (e[4].y, -e[2]))
            a, b, length, along, out = front
            mid = (a + b) / 2 + out * 0.06
            if night_house:
                oriented_box(meshes["door"], mid, along, min(3.0, length * 0.4), 0.12, 0.15, 2.4)
            elif item["material"] == "hospital" and h > 8:
                oriented_box(meshes["glass"], mid, along, 6.0, 0.12, 0.15, 3.2)
                # Entrance canopy on two posts.
                canopy = (a + b) / 2 + out * 4.0
                oriented_box(meshes["trim"], canopy, along, 10.0, 8.0, 3.6, 3.9)
                for s in (-1, 1):
                    oriented_box(meshes["trim"], canopy + along * s * 4.5 + out * 3.5, along, 0.35, 0.35, 0.15, 3.6)
            else:
                oriented_box(meshes["door"], mid, along, 2.4 if length > 20 else 1.2, 0.12, 0.15, 2.6 if length > 20 else 2.2)
            count["doors"] += 1
            if not night_house:
                if item["roof"] == "gable" and h > 7:
                    rows = [(h - 3.2, h - 1.4)]  # high clerestory band (kitchen hall)
                else:
                    rows = [(0.15 + s * STOREY + 1.0, 0.15 + s * STOREY + 2.5) for s in range(max(1, int(h // STOREY)))]
                for a, b, length, along, out in edges:
                    n = int((length - 2.5) // 3.6)
                    if n < 1:
                        continue
                    start = (length - (n - 1) * 3.6) / 2
                    for i in range(n):
                        c = a + along * (start + i * 3.6) + out * 0.05
                        if (c - ((front[0] + front[1]) / 2 + out * 0.05)).length < 4.0 and (a, b) == (front[0], front[1]):
                            continue  # keep the door clear
                        for z0, z1 in rows:
                            oriented_box(meshes["glass"], c, along, 1.8, 0.1, z0, z1)
                            oriented_box(meshes["trim"], c + out * 0.06, along, 2.1, 0.22, z0 - 0.12, z0)
                            count["windows"] += 1
            if item["roof"] != "gable":
                key = item["material"]
                bm = walls.setdefault(key, bmesh.new())
                for a, b, length, along, out in edges:
                    oriented_box(bm, (a + b) / 2 - out * 0.12, along, length, 0.25, h + 0.25, h + 1.0)
                if h > 8:
                    # Rooftop plant: AC units and a water tank, as on most Indian institutional roofs.
                    c = sum(pts, Vector((0, 0))) / 4
                    _, _, _, along0, _ = max(edges, key=lambda e: e[2])
                    side = Vector((-along0.y, along0.x))
                    for i in range(4):
                        oriented_box(meshes["plant"], c + along0 * (-12 + i * 8) + side * 6, along0, 3.0, 2.0, h + 0.25, h + 1.9)
                    oriented_box(meshes["plant"], c - side * 6, along0, 4.0, 4.0, h + 0.25, h + 2.8)
    link_mesh(col, "Dress: glass", meshes["glass"], glass)
    link_mesh(col, "Dress: doors", meshes["door"], door)
    link_mesh(col, "Dress: rooftop plant", meshes["plant"], plant)
    link_mesh(col, "Dress: trim", meshes["trim"], sill)
    for key, bm in walls.items():
        link_mesh(col, f"Dress: parapets ({key})", bm, bpy.data.materials[f"Blockout: {key}"])
    return count


def source_collection(parent, name):
    col = new_collection(name, parent)
    lc = bpy.context.view_layer.layer_collection
    stack = [lc]
    while stack:
        cur = stack.pop()
        if cur.collection == col:
            cur.exclude = True  # sources only show through their instances
        stack.extend(cur.children)
    return col


def import_gltf(path, col):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    for ob in [o for o in new if o.type == "MESH" and o.parent is None and o.name.startswith("Icosphere")]:
        new.remove(ob)  # bone display shape made by the glTF importer, not part of the model
        bpy.data.objects.remove(ob, do_unlink=True)
    for ob in new:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        col.objects.link(ob)
    # Instance origin: bottom centre of the model.
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in new:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(dg)
        for corner in ev.bound_box:
            w = ev.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    col.instance_offset = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
    return new, hi - lo


def instance(col, src, name, x, y, z=0.12, heading=0.0, scale=1.0):
    ob = bpy.data.objects.new(name, None)
    ob.instance_type = "COLLECTION"
    ob.instance_collection = src
    ob.location = (x, y, z)
    ob.rotation_euler = (0, 0, math.radians(heading))
    ob.scale = (scale,) * 3
    col.objects.link(ob)
    return ob


def place_animals(parent):
    sources = source_collection(parent, "Dress sources: animals")
    col = new_collection("Dress: animals", parent)
    srcs = {}
    for name in ("elephant", "tiger", "rhino"):
        path = os.path.join(ANIMALS, f"{name}.glb")
        if not os.path.exists(path):
            continue
        src = new_collection(f"Dress source: {name}", sources)
        objs, size = import_gltf(path, src)
        for ob in objs:
            if ob.type == "ARMATURE" and ob.animation_data and name == "elephant":
                idle = bpy.data.actions.get("Idle")
                if idle:
                    ob.animation_data.action = idle
        srcs[name] = src
    placed = 0
    for name, x, y, heading in ANIMAL_SPOTS:
        if name in srcs:
            # Models face Blender -Y; heading 0 = facing north (+Y).
            instance(col, srcs[name], f"Animal: {name}", x, y, 0.14, heading + 180)
            placed += 1
    return placed


def scatter_points(rng, region, spacing, count, keep_out):
    """Seeded dart throwing inside `region`, at least `spacing` apart, rejected by keep_out(p)."""
    xs = [p[0] for p in region]
    ys = [p[1] for p in region]
    pts = []
    tries = 0
    while len(pts) < count and tries < count * 60:
        tries += 1
        p = (rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys)))
        if not inside(p, region) or keep_out(p):
            continue
        if any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < spacing**2 for q in pts):
            continue
        pts.append(p)
    return pts


def footprints():
    """Everything built (buildings, sheds, water, paved/sand surfaces) with a clearance in metres."""
    out = []
    for zone in LAYOUT["zones"]:
        for item in zone["items"]:
            if item["type"] in ("building", "shed"):
                out.append((item["footprint"], 4.0))
            elif item["type"] == "water":
                out.append((item["polygon"], 3.0))
            elif item["type"] == "surface" and item["material"] in ("paving", "asphalt"):
                out.append((item["polygon"], 2.0))
    return out


def bottom_centre(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in objs:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(dg)
        for corner in ev.bound_box:
            w = ev.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))


def plant_sources(parent):
    """Import each downloaded model; one source collection per mesh variant."""
    available = [a for a in PLANTS if glob.glob(os.path.join(MODELS, a, "*.gltf"))]
    if not available:
        return {}
    sources = source_collection(parent, "Dress sources: plants")
    srcs = {}
    for asset in available:
        role, scale = PLANTS[asset]
        tmp = new_collection(f"Dress tmp: {asset}", sources)
        objs, _ = import_gltf(glob.glob(os.path.join(MODELS, asset, "*.gltf"))[0], tmp)
        for mat in {s.material for o in objs if o.type == "MESH" for s in o.material_slots if s.material}:
            # Leaf cards come in alpha-blended; dithered sorts and shadows correctly in EEVEE.
            if getattr(mat, "surface_render_method", None) == "BLENDED":
                mat.surface_render_method = "DITHERED"
        for ob in [o for o in objs if o.type == "MESH"]:
            if ob.parent and ob.parent.type == "EMPTY":
                world = ob.matrix_world.copy()
                ob.parent = None
                ob.matrix_world = world
            faces = len(ob.data.polygons)
            if faces > MAX_FACES:
                mod = ob.modifiers.new("Decimate", "DECIMATE")
                mod.ratio = MAX_FACES / faces
            variant = new_collection(f"Dress source: {ob.name}", sources)
            for o in [ob] + [c for c in objs if c.parent == ob]:
                tmp.objects.unlink(o)
                variant.objects.link(o)
            variant.instance_offset = bottom_centre([ob])
            srcs.setdefault(role, []).append((variant, scale))
        for o in list(tmp.objects):  # empties left from the glTF node tree
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(tmp)
    return srcs


def plant_vegetation(parent):
    srcs = plant_sources(parent)
    if not srcs:
        return {}
    col = new_collection("Dress: vegetation", parent)
    rng = random.Random(SEED)
    built = footprints()
    roads = [(r["points"], r["width"] / 2 + 3.0) for r in SITE["roads"]]
    outline = SITE["outline"]
    zone_areas = {z["id"]: z["area"] for z in LAYOUT["zones"]}
    fences = [(it["points"], 2.5) for z in LAYOUT["zones"] for it in z["items"] if it["type"] == "fence"]

    def blocked(p, extra=0.0, fence_too=True):
        if not inside(p, outline) or poly_dist(p, outline) < 4.0:
            return True
        for poly, clear in built:
            if inside(p, poly) or poly_dist(p, poly) < clear + extra:
                return True
        for line, clear in roads:
            if min(seg_dist(p, a, b) for a, b in zip(line, line[1:])) < clear:
                return True
        if fence_too:
            for poly, clear in fences:
                if poly_dist(p, poly) < clear:
                    return True
        return False

    counts = {}

    def put(role, pts):
        for x, y in pts:
            src, scale = rng.choice(srcs[role])
            instance(col, src, f"{role}", x, y, 0.12, rng.uniform(0, 360), rng.uniform(*scale))
        counts[role] = counts.get(role, 0) + len(pts)

    def has(role):
        return role in srcs

    in_zone = lambda p: any(inside(p, a) for zid, a in zone_areas.items() if zid != "woodland")  # noqa: E731

    def each_surface(test):
        for zone in LAYOUT["zones"]:
            for item in zone["items"]:
                if item["type"] == "surface" and test(item["name"].lower(), item["material"]):
                    yield item["name"].lower(), item["polygon"]

    def free(p):
        return not blocked(p) and not in_zone(p)

    if has("tree"):
        # Woodland wedge: dense canopy; grounds between zones: scattered shade trees.
        put("tree", scatter_points(rng, zone_areas["woodland"], 12, 140, blocked))
        put("tree", scatter_points(rng, outline, 24, 110, lambda p: not free(p)))
        # Shade inside the elephant paddock, each big-cat enclosure and herbivore paddock.
        for name, poly in each_surface(lambda n, m: "enclosure" in n or "paddock" in n):
            put("tree", scatter_points(rng, poly, 14, 6 if "elephant" in name else 2, lambda p: blocked(p, 2.0)))
    if has("bush"):
        put("bush", scatter_points(rng, zone_areas["woodland"], 6, 160, blocked))
        put("bush", scatter_points(rng, outline, 12, 160, lambda p: not free(p)))
        for name, poly in each_surface(lambda n, m: m == "grass_wild"):
            put("bush", scatter_points(rng, poly, 6, 3, lambda p: blocked(p, 1.0)))
    if has("shrub"):
        put("shrub", scatter_points(rng, outline, 6, 450, lambda p: not free(p)))
        for name, poly in each_surface(lambda n, m: m == "grass_wild"):
            put("shrub", scatter_points(rng, poly, 4, 8, lambda p: blocked(p, 1.0)))
    if has("rock"):
        for name, poly in each_surface(lambda n, m: "enclosure" in n or "elephant paddock" in n):
            put("rock", scatter_points(rng, poly, 8, 6 if "elephant" in name else 3, lambda p: blocked(p, 1.0)))
    return counts


def dress_cameras():
    env = bpy.data.collections.get("Sky, sun, cameras") or bpy.context.scene.collection

    def cam(name, loc, target, lens=26):
        data = bpy.data.cameras.new(name)
        data.lens = lens
        data.clip_start = 0.3 if loc[2] < 10 else 2.0
        data.clip_end = 12000
        ob = bpy.data.objects.new(name, data)
        env.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    cam("Cam: Dress elephant paddock", (-300, -100, 4.5), (-250, -45, 1.5), 30)
    cam("Cam: Dress tiger enclosure", (206, -100, 2.2), (186, -100, 0.6), 30)


def grade():
    """Light and colour pass: the step-1 sky was too strong against the sun, so
    everything went grey-blue. Sun disc off in the sky (the Sun lamp is the sun),
    weaker sky fill, stronger sun, and a neutral view transform that keeps
    albedo colours (sand stays sand)."""
    scene = bpy.context.scene
    nt = scene.world.node_tree
    sky = next(n for n in nt.nodes if n.type == "TEX_SKY")
    sky.sun_disc = False
    next(n for n in nt.nodes if n.type == "BACKGROUND").inputs["Strength"].default_value = 0.10
    sun = bpy.data.objects.get("Sun")
    if sun:
        sun.data.energy = 4.5
    scene.view_settings.view_transform = "Khronos PBR Neutral"
    scene.view_settings.exposure = -1.0


def dress():
    scene = bpy.context.scene
    remove_previous()
    root = new_collection("Dress")
    textures = reskin_all()
    details = building_details(root)
    animals = place_animals(root)
    plants = plant_vegetation(root)
    dress_cameras()
    grade()
    scene.frame_set(1)
    bpy.ops.wm.save_mainfile()
    print("textures:", textures)
    print("building detail:", details, "| animals:", animals, "| plants:", plants or "none (models not downloaded)")


dress()
