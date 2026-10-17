"""Phase 7: turn the imported animal models into web-ready GLBs (runs inside Blender).

Run through the MCP-for-Blender socket from pipeline/:

    uv run python -m vantara_pipeline.blender_bridge execute_code --code "exec(open(r'blender/prepare_animals.py').read())"

or headless:  blender -b animals.blend -P blender/prepare_animals.py

Expects each animal in a collection "Animal: <name>" (meshes, optional
armature). For each one it:
  1. puts the model in its resting pose (idle clip, frame 0, if any),
  2. parents it under "<name>_root", scaled to real height, centred, feet on 0,
  3. gives untextured meshes a flat placeholder material,
  4. exports web/public/models/<name>.glb (+Y up, front = +Z, modifiers
     applied, skin + every action as a named clip),
and writes web/src/content/animals.json for the explorer.

Models face Blender -Y (glTF +Z) on input; set "yaw_deg" if one doesn't.
"""

import json
import math
import os

import bpy
from mathutils import Matrix, Vector

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
OUT_DIR = os.path.join(REPO, "web", "public", "models")
MANIFEST = os.path.join(REPO, "web", "src", "content", "animals.json")

# Heights are shoulder-to-ground plus head, for typical adults. Colours are
# linear albedo close to the real animals (elephant/rhino skin ~0.15-0.2).
ANIMALS = {
    "elephant": {
        "height_m": 3.2, "walk_speed": 1.1, "color": (0.17, 0.16, 0.15), "yaw_deg": 0,
        "clips": {"idle": "Idle", "walk": None, "extras": ["Eating", "Angry"]},
        "credit": "low poly elephant by syncopika (CC0), opengameart.org/node/92420",
    },
    "tiger": {
        "height_m": 1.05, "walk_speed": 1.2, "color": (0.45, 0.2, 0.05), "yaw_deg": 0,
        "clips": {"idle": None, "walk": None, "extras": []},
        "credit": "Tiger by Micket (CC0), opengameart.org/content/tiger",
    },
    "rhino": {
        "height_m": 1.75, "walk_speed": 0.9, "color": (0.22, 0.21, 0.2), "yaw_deg": 0,
        "clips": {"idle": None, "walk": None, "extras": []},
        "credit": "White Rhinoceros by Micket (CC0), opengameart.org/content/white-rhinoceros",
    },
}


def evaluated_bounds(meshes):
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in meshes:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        for v in me.vertices:
            p = ob.matrix_world @ v.co
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
        ev.to_mesh_clear()
    return lo, hi


def placeholder_material(name, color):
    mat = bpy.data.materials.get(f"placeholder_{name}") or bpy.data.materials.new(f"placeholder_{name}")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def glb_clips(path):
    """Animation clips actually present in an exported GLB, with durations."""
    import struct

    with open(path, "rb") as fh:
        data = fh.read()
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + length])
    clips = []
    for anim in doc.get("animations", []):
        # Duration = latest keyframe time across the clip's input accessors.
        end = max((doc["accessors"][s["input"]].get("max", [0])[0] for s in anim["samplers"]), default=0)
        clips.append({"name": anim.get("name", ""), "seconds": round(end, 2)})
    return clips


def has_texture(mesh):
    for mat in mesh.data.materials:
        if mat and mat.use_nodes and any(n.type == "TEX_IMAGE" and n.image for n in mat.node_tree.nodes):
            return True
    return False


def prepare(name, cfg):
    col = bpy.data.collections[f"Animal: {name}"]
    meshes = [o for o in col.objects if o.type == "MESH"]
    arms = [o for o in col.objects if o.type == "ARMATURE"]
    for ob in col.objects:
        ob.hide_set(False)

    # Resting pose for measuring and as the GLB's bind-time look.
    idle = cfg["clips"]["idle"]
    for arm in arms:
        if idle and idle in bpy.data.actions:
            arm.animation_data_create().action = bpy.data.actions[idle]
    bpy.context.scene.frame_set(0)

    # Root empty owns the normalising transform; re-running starts from scratch.
    root = bpy.data.objects.get(f"{name}_root")
    if root is None:
        root = bpy.data.objects.new(f"{name}_root", None)
        col.objects.link(root)
    root.matrix_world = Matrix.Identity(4)
    for ob in col.objects:
        if ob is not root and ob.parent is None:
            mw = ob.matrix_world.copy()
            ob.parent = root
            ob.matrix_world = mw
    bpy.context.view_layer.update()

    lo, hi = evaluated_bounds(meshes)
    scale = cfg["height_m"] / (hi.z - lo.z)
    centre = (lo + hi) / 2
    yaw = Matrix.Rotation(math.radians(cfg["yaw_deg"]), 4, "Z")
    root.matrix_world = (
        yaw @ Matrix.Diagonal((scale, scale, scale, 1.0)) @ Matrix.Translation((-centre.x, -centre.y, -lo.z))
    )
    bpy.context.view_layer.update()
    lo2, hi2 = evaluated_bounds(meshes)

    for ob in meshes:
        if not has_texture(ob):
            mat = placeholder_material(name, cfg["color"])
            ob.data.materials.clear()
            ob.data.materials.append(mat)

    # Export just this animal.
    bpy.ops.object.select_all(action="DESELECT")
    for ob in [root, *root.children_recursive]:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = root
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.glb")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,  # bake mirror/edge-split etc.; the armature stays a skin
        export_skins=True,
        export_animations=bool(arms),
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_cameras=False,
        export_lights=False,
        export_extras=False,
    )
    bpy.ops.object.select_all(action="DESELECT")

    clips = glb_clips(path)
    for role in ("idle", "walk"):
        wanted = cfg["clips"][role]
        if wanted and wanted not in {c["name"] for c in clips}:
            raise RuntimeError(f"{name}: {role} clip {wanted!r} is not in the exported GLB")
    size = hi2 - lo2
    return {
        "file": f"{name}.glb",
        "heightM": round(size.z, 2),
        "lengthM": round(size.y, 2),
        "widthM": round(size.x, 2),
        "walkSpeed": cfg["walk_speed"],
        "clips": clips,
        "idleClip": cfg["clips"]["idle"],
        "walkClip": cfg["clips"]["walk"],
        "extraClips": cfg["clips"]["extras"],
        "placeholder": True,
        "credit": cfg["credit"],
        "bytes": os.path.getsize(path),
    }


manifest = {"$comment": "Written by pipeline/blender/prepare_animals.py. Sizes in metres; models face +Z.", "animals": {}}
for animal, cfg in ANIMALS.items():
    manifest["animals"][animal] = prepare(animal, cfg)
    print(animal, json.dumps(manifest["animals"][animal]))
with open(MANIFEST, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2)
    fh.write("\n")
print("manifest ->", MANIFEST)
