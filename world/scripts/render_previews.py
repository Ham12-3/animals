"""Render the preview cameras of vantara_world.blend to world/renders/ (runs inside Blender).

    cd pipeline
    uv run python -m vantara_pipeline.blender_bridge execute_code \
        --code "STEP='step3'; exec(open('C:/Users/mobol/Downloads/animals/world/scripts/render_previews.py', encoding='utf-8').read())"

Renders every camera whose name starts with "Cam: " (or only those listed in
CAMERAS) to renders/<STEP>_<camera>.png. Zone labels painted on the ground are
hidden for eye-level cameras.
"""

import os
import sys

import bpy

REPO = os.environ.get("VANTARA_REPO", r"C:\Users\mobol\Downloads\animals")
OUT = os.path.join(REPO, "world", "renders")
# From the MCP socket: set STEP / CAMERAS before exec. Headless:
#   blender -b world/vantara_world.blend -P world/scripts/render_previews.py -- step5 "Aerial close,Dress woodland"
ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
STEP = globals().get("STEP") or (ARGS[0] if ARGS else "preview")
CAMERAS = globals().get("CAMERAS") or (ARGS[1].split(",") if len(ARGS) > 1 else None)  # names without "Cam: "


def render_previews():
    scene = bpy.context.scene
    os.makedirs(OUT, exist_ok=True)
    labels = bpy.data.collections.get("Zone labels")
    cams = sorted((o for o in bpy.data.objects if o.type == "CAMERA" and o.name.startswith("Cam: ")), key=lambda o: o.name)
    if CAMERAS:
        cams = [o for o in cams if o.name[5:] in CAMERAS]
    done = []
    for cam in cams:
        if labels:
            labels.hide_render = cam.location.z < 50
        scene.camera = cam
        slug = cam.name[5:].lower().replace("dress ", "").replace(" ", "_")
        scene.render.filepath = os.path.join(OUT, f"{STEP}_{slug}.png")
        bpy.ops.render.render(write_still=True)
        done.append(scene.render.filepath)
    if labels:
        labels.hide_render = False
    print("rendered:", done)


render_previews()
