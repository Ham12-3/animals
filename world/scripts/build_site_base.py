"""World step 1: build the Vantara site base in Blender (runs inside Blender).

    uv run --project pipeline python -m vantara_pipeline.blender_bridge execute_code \
        --code "exec(open('world/scripts/build_site_base.py', encoding='utf-8').read())"

Reads world/data/site.json (from osm_to_json.py) and builds, at real scale in
metres (X east, Y north, Z up), a scene "Vantara Site":

  ground (10 km), Vantara's mapped outline on a landscaped base with a
  perimeter wall, roads at their real widths, lakes, streams, railway, a
  physical sky with the sun placed for Jamnagar, an aerial and a ground camera,
  and the "artistic interpretation" + OpenStreetMap attribution label.

ARTISTIC INTERPRETATION: only the outline, roads, water and railway come from
map data. Everything inside Vantara will be designed, not surveyed.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import bmesh
import bpy
from mathutils import Vector

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
SITE = json.load(open(os.path.join(REPO, "world", "data", "site.json"), encoding="utf-8"))
BLEND = os.path.join(REPO, "world", "vantara_world.blend")
SCENE = "Vantara Site"
GROUND_SIZE = 10000.0  # well past the mapped area so the horizon is ground, not void
# Mid-morning, mid-March: dry-season light typical of Jamnagar.
# Layer heights above the ground plane (m): enough separation to avoid depth
# flicker when seen from a kilometre away.
Z_WATER, Z_SITE, Z_ROAD, Z_RAIL = 0.10, 0.12, 0.18, 0.22
WHEN = datetime(2026, 3, 15, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


# --- scene ---------------------------------------------------------------------


def fresh_scene():
    """A new scene in this file; the previous one is removed (its content is saved elsewhere)."""
    old = bpy.context.window.scene
    scene = bpy.data.scenes.get(SCENE)
    if scene is not None and scene != old:
        bpy.data.scenes.remove(scene)
        scene = None
    if scene is None:
        scene = bpy.data.scenes.new(SCENE)
    bpy.context.window.scene = scene
    for s in list(bpy.data.scenes):
        if s != scene:
            bpy.data.scenes.remove(s)
    # Rebuild from scratch: this file only holds what this script makes.
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    bpy.data.orphans_purge(do_recursive=True)
    for col in list(scene.collection.children):
        scene.collection.children.unlink(col)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene["vantara3d"] = "Artistic interpretation. Map data (c) OpenStreetMap contributors, ODbL."
    return scene


def collection(scene, name):
    col = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def mesh_object(col, name, bm, material):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


# --- materials ------------------------------------------------------------------


def material(name, base, roughness=0.9, *, noise_color=None, noise_scale=0.05, water=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = roughness
    if water:
        bsdf.inputs["Base Color"].default_value = (*base, 1)
        bsdf.inputs["Roughness"].default_value = 0.05
        bsdf.inputs["IOR"].default_value = 1.33
        wave = nt.nodes.new("ShaderNodeTexNoise")
        wave.inputs["Scale"].default_value = 0.6
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.08
        nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        return mat
    if noise_color is None:
        bsdf.inputs["Base Color"].default_value = (*base, 1)
        return mat
    # Two-tone noise in world space: breaks up large flat areas at any distance.
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = noise_scale
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (*base, 1)
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (*noise_color, 1)
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = noise_scale * 40
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    nt.links.new(coord.outputs["Object"], fine.inputs["Vector"])
    nt.links.new(fine.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# --- geometry -------------------------------------------------------------------


def polygon(bm, pts, z):
    verts = [bm.verts.new((x, y, z)) for x, y in pts]
    if len(verts) >= 3:
        bm.faces.new(verts)


def ribbon(bm, pts, width, z):
    """Flat strip along a polyline, mitred joints (limited for sharp turns)."""
    p = [Vector((x, y)) for x, y in pts]
    if len(p) < 2:
        return
    half = width / 2
    left, right = [], []
    for i, cur in enumerate(p):
        d_in = (cur - p[i - 1]).normalized() if i > 0 else None
        d_out = (p[i + 1] - cur).normalized() if i < len(p) - 1 else None
        d = (d_in + d_out) if d_in and d_out else (d_in or d_out)
        if d.length < 1e-6:
            d = d_out or d_in
        d.normalize()
        n = Vector((-d.y, d.x))
        scale = 1.0
        if d_in and d_out:
            scale = min(3.0, 1.0 / max(0.2, n.dot(Vector((-d_in.y, d_in.x)))))
        left.append(bm.verts.new((*(cur + n * half * scale), z)))
        right.append(bm.verts.new((*(cur - n * half * scale), z)))
    for i in range(len(p) - 1):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))


def wall(bm, pts, height, thickness):
    """Closed perimeter wall along a polygon."""
    ring = pts + pts[:1]
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        d = Vector((x1 - x0, y1 - y0))
        if d.length < 1e-3:
            continue
        n = Vector((-d.y, d.x)).normalized() * (thickness / 2)
        a, b = Vector((x0, y0)), Vector((x1, y1))
        corners = [a + n, b + n, b - n, a - n]
        bottom = [bm.verts.new((c.x, c.y, 0)) for c in corners]
        top = [bm.verts.new((c.x, c.y, height)) for c in corners]
        bm.faces.new(top)
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((bottom[i], bottom[j], top[j], top[i]))


# --- sun ------------------------------------------------------------------------


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


def sky_and_sun(scene, col):
    lat, lon = SITE["origin"]["lat"], SITE["origin"]["lon"]
    elevation, azimuth = solar_position(lat, lon, WHEN)
    world = bpy.data.worlds.get("Vantara Sky") or bpy.data.worlds.new("Vantara Sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    types = [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items]
    for wanted in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
        if wanted in types:
            sky.sky_type = wanted
            break
    for attr, val in (("sun_elevation", math.radians(elevation)), ("sun_rotation", math.radians(azimuth)),
                      ("altitude", 15.0), ("air_density", 1.2), ("dust_density", 2.5)):  # fmt: skip
        if hasattr(sky, attr):
            setattr(sky, attr, val)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.22
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    sun_data = bpy.data.lights.get("Sun") or bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(0.53)
    sun_data.color = (1.0, 0.96, 0.9)
    sun = bpy.data.objects.new("Sun", sun_data)
    col.objects.link(sun)
    # Light points along -Z: tilt down to the elevation, then turn to the azimuth (Blender Y = north).
    sun.rotation_euler = (math.radians(90 - elevation), 0, math.radians(180 - azimuth))
    sun.location = (0, 0, 500)
    return elevation, azimuth, sky.sky_type


def cameras(scene, col):
    def cam(name, loc, target, lens):
        data = bpy.data.cameras.new(name)
        data.lens = lens
        data.clip_start = 0.3 if loc[2] < 10 else 3.0  # far cameras need depth precision
        data.clip_end = 12000
        ob = bpy.data.objects.new(name, data)
        col.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return ob

    aerial = cam("Aerial", (-700, -900, 520), (60, -20, 0), 32)
    cam("South gate", (-120, -175, 1.7), (-40, -60, 2.0), 28)
    scene.camera = aerial


def label(col, mat):
    xs = [p[0] for p in SITE["outline"]]
    ys = [p[1] for p in SITE["outline"]]
    curve = bpy.data.curves.new("ArtisticInterpretationLabel", "FONT")
    curve.body = "VANTARA 3D\nartistic interpretation\nmap data (c) OpenStreetMap contributors"
    curve.size = 14
    curve.align_x = "CENTER"
    ob = bpy.data.objects.new("Label: artistic interpretation", curve)
    ob.location = ((min(xs) + max(xs)) / 2, min(ys) - 95, 0.3)
    ob.data.materials.append(mat)
    col.objects.link(ob)


# --- build ----------------------------------------------------------------------


def build():
    scene = fresh_scene()
    terrain = collection(scene, "Terrain")
    site = collection(scene, "Vantara (outline from OSM)")
    infra = collection(scene, "Roads, rail, water (OSM)")
    env = collection(scene, "Sky, sun, cameras")

    m_ground = material("Ground: dry scrub", (0.42, 0.34, 0.24), noise_color=(0.30, 0.30, 0.17), noise_scale=0.02)
    m_lawn = material("Ground: Vantara landscaped", (0.17, 0.25, 0.08), noise_color=(0.24, 0.30, 0.12), noise_scale=0.05)
    m_wall = material("Perimeter wall", (0.62, 0.58, 0.52), 0.85)
    m_asphalt = material("Road: asphalt", (0.09, 0.09, 0.09), 0.75, noise_color=(0.13, 0.13, 0.12), noise_scale=0.3)
    m_concrete = material("Road: concrete", (0.45, 0.43, 0.40), 0.85)
    m_dirt = material("Road: dirt track", (0.40, 0.31, 0.21), 0.95)
    m_ballast = material("Rail ballast", (0.22, 0.21, 0.20), 0.95)
    m_water = material("Water", (0.06, 0.12, 0.13), water=True)
    m_label = material("Label", (0.95, 0.95, 0.95), 0.5)

    bm = bmesh.new()
    h = GROUND_SIZE / 2
    polygon(bm, [(-h, -h), (h, -h), (h, h), (-h, h)], 0.0)
    mesh_object(terrain, "Ground", bm, m_ground)

    bm = bmesh.new()
    polygon(bm, SITE["outline"], Z_SITE)
    mesh_object(site, "Vantara grounds", bm, m_lawn)
    bm = bmesh.new()
    wall(bm, SITE["outline"], 2.2, 0.3)
    mesh_object(site, "Perimeter wall", bm, m_wall)

    by_material = {"asphalt": [], "concrete": [], "dirt": []}
    for r in SITE["roads"]:
        kind = {"track": "dirt", "service": "concrete"}.get(r["kind"], "asphalt")
        by_material[kind].append(r)
    mats = {"asphalt": m_asphalt, "concrete": m_concrete, "dirt": m_dirt}
    for kind, roads in by_material.items():
        if not roads:
            continue
        bm = bmesh.new()
        for i, r in enumerate(roads):
            ribbon(bm, r["points"], r["width"], Z_ROAD + 0.004 * (i % 5))  # small steps avoid flicker at junctions
        mesh_object(infra, f"Roads: {kind}", bm, mats[kind])

    bm = bmesh.new()
    for w in SITE["water"]:
        polygon(bm, w, Z_WATER)
    for ww in SITE["waterways"]:
        ribbon(bm, ww["points"], ww["width"], Z_WATER)
    mesh_object(infra, "Water", bm, m_water)

    bm = bmesh.new()
    for r in SITE["rail"]:
        ribbon(bm, r, 4.0, Z_RAIL)
    mesh_object(infra, "Railway", bm, m_ballast)

    elevation, azimuth, sky_type = sky_and_sun(scene, env)
    cameras(scene, env)
    label(site, m_label)

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    vs = scene.view_settings
    transforms = [i.identifier for i in vs.bl_rna.properties["view_transform"].enum_items]
    # Khronos PBR Neutral keeps material colours true (AgX washes them out here).
    for t in ("Khronos PBR Neutral", "AgX", "Filmic"):
        if t in transforms:
            vs.view_transform = t
            break
    vs.exposure = -0.6

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.clip_start, space.clip_end = 0.5, 15000
            space.shading.type = "MATERIAL"
            space.region_3d.view_perspective = "CAMERA"

    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    print(f"built '{SCENE}': sun elevation {elevation:.1f} deg, azimuth {azimuth:.1f} deg, sky {sky_type}, "
          f"engine {scene.render.engine}; saved {BLEND}")  # fmt: skip


build()
