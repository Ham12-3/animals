"""Download the CC0 Poly Haven assets used by dress_zones.py into world/assets/polyhaven/.

    uv run --project pipeline python world/scripts/fetch_polyhaven.py

Textures: 1k JPG colour, normal (GL) and roughness maps. Models: 1k glTF with
its buffers and textures. All Poly Haven assets are CC0. Already-downloaded
files are skipped. world/assets/ is not in git.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "polyhaven"
UA = {"User-Agent": "VantaraFanRecon/0.1"}
TEXTURES = ["dry_ground_01", "sand_01", "withered_grass", "asphalt_02", "red_sandstone_pavement",
            "white_plaster_02", "yellow_plaster", "corrugated_iron_02", "clay_roof_tiles", "brown_mud_02"]  # fmt: skip
MODELS = ["island_tree_02", "searsia_lucida", "shrub_02", "wild_rooibos_bush", "grass_bermuda_01",
          "boulder_01", "namaqualand_boulder_02"]  # fmt: skip


def api(path):
    return json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.polyhaven.com/{path}", headers=UA)))


def fetch(url, dest: Path):
    if dest.exists() and dest.stat().st_size > 0:
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return len(data)


def main() -> None:
    total = 0
    for asset in TEXTURES:
        files = api(f"files/{asset}")
        for key in ("Diffuse", "nor_gl", "Rough"):
            f = files[key]["1k"]["jpg"]
            total += fetch(f["url"], OUT / "textures" / asset / f["url"].rsplit("/", 1)[1])
        print("texture", asset)
    for asset in MODELS:
        g = api(f"files/{asset}")["gltf"]["1k"]["gltf"]
        base = OUT / "models" / asset
        total += fetch(g["url"], base / g["url"].rsplit("/", 1)[1])
        for rel, inc in g.get("include", {}).items():
            dest = (base / rel).resolve()
            if base.resolve() not in dest.parents:
                raise SystemExit(f"refusing path outside the asset folder: {rel}")
            total += fetch(inc["url"], dest)
        print("model", asset)
    (OUT / "LICENSE.txt").write_text(
        "All assets in this folder are from Poly Haven (polyhaven.com) and are CC0 (public domain).\n"
        "Textures: " + ", ".join(TEXTURES) + "\nModels: " + ", ".join(MODELS) + "\n", encoding="utf-8")
    print(f"downloaded {total / 1e6:.1f} MB -> {OUT}")


if __name__ == "__main__":
    main()
