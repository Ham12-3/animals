"""Web textures for the world (OpenCV only).

    uv run --project pipeline python world/scripts/prepare_textures.py

From the CC0 Poly Haven downloads in world/assets/polyhaven/ (fetch_polyhaven.py):

- surface textures named in compile_world.MATERIALS ->
  world/publish/world/textures/<set>_diff.jpg (1024 px) and <set>_nor.jpg (512 px)
- plant model textures -> world/publish/_staging/plants/<asset>/<file> at 512 px,
  same names and formats (PNG keeps its alpha for leaf cards); build_plants.mjs
  swaps them into the plant models
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from compile_world import MATERIALS, PLANTS  # noqa: E402

WORLD = HERE.parent
SRC = WORLD / "assets" / "polyhaven"
OUT = WORLD / "publish" / "world" / "textures"
STAGING = WORLD / "publish" / "_staging" / "plants"
COLOUR_PX, DATA_PX, PLANT_PX = 1024, 512, 512
JPEG_Q = 82


def fit(img, px):
    h, w = img.shape[:2]
    if max(h, w) <= px:
        return img
    s = px / max(h, w)
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def write(path: Path, img) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".png":
        ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    else:
        ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    if not ok:
        raise SystemExit(f"could not write {path}")
    return path.stat().st_size


def find(folder: Path, marker: str) -> Path:
    hits = sorted(folder.glob(f"*{marker}*"))
    if not hits:
        raise SystemExit(f"missing {marker} map in {folder} (run fetch_polyhaven.py)")
    return hits[0]


def surface_textures() -> int:
    total = 0
    sets = {}
    for m in MATERIALS.values():
        if "texture" in m:
            sets.setdefault(m["texture"], set()).update({"diff", "nor"})
        if "normal" in m:
            sets.setdefault(m["normal"], set()).add("nor")
    for name, maps in sorted(sets.items()):
        folder = SRC / "textures" / name
        if "diff" in maps:
            total += write(OUT / f"{name}_diff.jpg", fit(cv2.imread(str(find(folder, "_diff_"))), COLOUR_PX))
        if "nor" in maps:
            total += write(OUT / f"{name}_nor.jpg", fit(cv2.imread(str(find(folder, "_nor_gl_"))), DATA_PX))
    return total


def plant_textures() -> int:
    total = 0
    for asset in PLANTS:
        gltf = sorted((SRC / "models" / asset).glob("*.gltf"))[0]
        doc = json.loads(gltf.read_text(encoding="utf-8"))
        for image in doc.get("images", []):
            src = gltf.parent / image["uri"]
            img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
            total += write(STAGING / asset / Path(image["uri"]).name, fit(img, PLANT_PX))
    return total


def main() -> None:
    a = surface_textures()
    b = plant_textures()
    print(f"surface textures: {a / 1e6:.2f} MB -> {OUT}")
    print(f"plant textures (staged): {b / 1e6:.2f} MB -> {STAGING}")


if __name__ == "__main__":
    main()
