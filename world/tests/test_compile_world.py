"""World compiler checks.

    uv run --project pipeline pytest world/tests -q
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compile_world as cw  # noqa: E402
from worldgeo import area, ccw, clip_polygon, inside, offset_polygon  # noqa: E402

OUTLINE = cw.SITE["outline"]


@pytest.fixture(scope="module")
def built():
    return cw.compile_world()


def local(p):
    """three.js [x, z] (or [x, y, z]) back to local (x east, y north)."""
    return (p[0], -p[-1])


def test_deterministic(built):
    again, _ = cw.compile_world()
    assert json.dumps(built[0], sort_keys=True) == json.dumps(again, sort_keys=True)


def test_counts(built):
    world, stats = built
    assert stats["plants"]["tree"] >= 700
    assert stats["plants"]["bush"] >= 500 and stats["plants"]["shrub"] >= 900
    assert stats["animals"] == 9
    assert stats["windows"] > 200 and stats["doors"] == sum(1 for _ in cw.items("building"))
    assert len(world["basins"]) == sum(1 for _, it in cw.items("water") if it["kind"] != "pool") + len(cw.SITE["water"])
    assert len(json.dumps(world)) < 2_000_000


def test_plants_inside_the_site(built):
    world, _ = built
    for name, rows in world["plants"]["instances"].items():
        assert name in world["plants"]["variants"]
        for x, y, z, yaw, s in rows:
            assert inside((x, -z), OUTLINE), (name, x, z)
            lo, hi = world["plants"]["variants"][name]["scale"]
            assert lo <= s <= hi and 0 <= yaw <= 2 * math.pi


def test_plants_clear_of_buildings(built):
    world, _ = built
    footprints = [it["footprint"] for _, it in cw.items("building")]
    for rows in world["plants"]["instances"].values():
        for x, _, z, _, _ in rows:
            assert not any(inside((x, -z), f) for f in footprints)


def test_animals_stay_out_of_water(built):
    world, _ = built
    water = [it["polygon"] for _, it in cw.items("water")]
    for a in world["animals"]:
        assert len(a["path"]) >= 2
        for p in a["path"]:
            assert inside(local(p), OUTLINE)
            assert not any(inside(local(p), w) for w in water)


def test_water_is_cut_out_of_the_ground(built):
    world, _ = built
    by_material = {}
    for s in world["surfaces"]:
        by_material.setdefault(s["material"], []).append(s)
    site = by_material["site_ground"][0]
    ponds = [it["polygon"] for _, it in cw.items("water")]
    assert len(site["holes"]) == len(ponds)  # every pond and the pool sits inside the grounds
    ground = by_material["ground_scrub"][0]
    assert len(ground["holes"]) == len(ponds) + len(cw.SITE["water"])


def test_basins_go_down(built):
    world, _ = built
    for b in world["basins"]:
        heights = [y for _, y in b["bank"]["rings"]]
        assert heights == sorted(heights, reverse=True) and heights[0] > heights[-1]
        assert heights[-1] < b["water"]["y"] < heights[0]
        counts = {len(r) for r, _ in b["bank"]["rings"]} | {len(r) for r, _ in b["water"]["rings"]}
        assert len(counts) == 1  # same vertex count on every ring: quads between them
        for _, rgba in b["water"]["rings"]:
            assert len(rgba) == 4 and all(0 <= c <= 1 for c in rgba)


def test_every_material_is_defined(built):
    world, _ = built
    used = {s["material"] for s in world["surfaces"]} | {r["material"] for r in world["ribbons"]}
    used |= {p["material"] for p in world["prisms"]} | {g["material"] for g in world["gables"]}
    used |= set(world["boxes"]) | set(world["quads"])
    used |= {b["bank"]["material"] for b in world["basins"]} | {b["water"]["material"] for b in world["basins"]}
    assert used <= set(world["materials"]), used - set(world["materials"])


def test_places_and_stands(built):
    world, _ = built
    ids = [p["id"] for p in world["places"]]
    assert len(ids) == len(set(ids))
    for p in world["places"]:
        if p["tier"] > 1:
            assert p["stand"] is not None, p["name"]
            assert inside(local(p["stand"]["position"]), OUTLINE)


def test_sun_matches_jamnagar_morning(built):
    world, _ = built
    s = world["sun"]
    assert 35 < s["elevationDeg"] < 45 and 100 < s["azimuthDeg"] < 125  # 10:00 IST, 15 March
    d = s["direction"]
    assert abs(math.hypot(*d) - 1) < 1e-3 and d[0] > 0 and d[1] > 0  # up and to the east


def test_geometry_helpers():
    sq = ccw([(0, 0), (10, 0), (10, 10), (0, 10)])
    inner = offset_polygon(sq, 1)
    assert area(inner) == pytest.approx(64)
    outer = offset_polygon(sq, -1)
    assert area(outer) == pytest.approx(144)
    tri = clip_polygon(sq, ccw([(5, -5), (15, -5), (15, 15), (5, 15)]))
    assert area(tri) == pytest.approx(50)


def test_assets_exist_for_everything_referenced(built):
    """Textures named by materials and plant variants must match what the asset steps produce."""
    world, _ = built
    tex = cw.OUT / "world" / world["assets"]["textures"]
    if not tex.exists():
        pytest.skip("run prepare_textures.py first")
    for m in world["materials"].values():
        if "texture" in m:
            assert (tex / f"{m['texture']}_diff.jpg").exists(), m["texture"]
            assert (tex / f"{m['texture']}_nor.jpg").exists(), m["texture"]
        if "normal" in m:
            assert (tex / f"{m['normal']}_nor.jpg").exists(), m["normal"]
    plants = cw.OUT / "world" / world["assets"]["plants"]
    if plants.exists():
        data = plants.read_bytes()
        for name in world["plants"]["instances"]:
            assert f"{name}|lod0".encode() in data and f"{name}|lod1".encode() in data, name
