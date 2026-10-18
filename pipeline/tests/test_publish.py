import math

import numpy as np
import pytest

from vantara_pipeline.splat_ply import read_ply, sh_band, sh_rotation, transform, write_ply


def _random_rotation(seed: int) -> np.ndarray:
    q, r = np.linalg.qr(np.random.default_rng(seed).normal(size=(3, 3)))
    q *= np.sign(np.diag(r))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def _quat_to_matrix(w, x, y, z):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])  # fmt: skip


def _splats(n=50, seed=1):
    rng = np.random.default_rng(seed)
    s = {k: rng.normal(size=n).astype(np.float32) for k in ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]}
    for i in range(45):
        s[f"f_rest_{i}"] = rng.normal(size=n).astype(np.float32)
    for i in range(3):
        s[f"scale_{i}"] = rng.normal(-2, 0.5, n).astype(np.float32)
    q = rng.normal(size=(n, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    for i in range(4):
        s[f"rot_{i}"] = q[:, i].astype(np.float32)
    return s


@pytest.mark.parametrize("level", [1, 2, 3])
def test_sh_rotation_moves_colour_with_the_scene(level):
    rot = _random_rotation(level)
    c = np.random.default_rng(level).normal(size=2 * level + 1)
    d = np.random.default_rng(9).normal(size=(100, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    new = sh_rotation(level, rot) @ c
    # Colour the rotated splat shows towards rot @ d == colour the original showed towards d.
    np.testing.assert_allclose(sh_band(level, d @ rot.T) @ new, sh_band(level, d) @ c, atol=1e-6)


def test_transform_positions_orientation_scale_and_sh():
    s = _splats()
    rot, origin, k = _random_rotation(4), np.array([1.0, -2.0, 0.5]), 2.5
    t = transform(s, rot, origin, k)
    p = np.stack([s["x"], s["y"], s["z"]], 1)
    p2 = np.stack([t["x"], t["y"], t["z"]], 1)
    np.testing.assert_allclose(p2, k * (p - origin) @ rot.T, atol=1e-4)
    for i in range(5):
        before = _quat_to_matrix(*(s[f"rot_{j}"][i] for j in range(4)))
        after = _quat_to_matrix(*(t[f"rot_{j}"][i] for j in range(4)))
        np.testing.assert_allclose(after, rot @ before, atol=1e-5)
    np.testing.assert_allclose(t["scale_0"], s["scale_0"] + math.log(k), atol=1e-5)
    # Band 1 of the red channel follows the same rule as the unit test above.
    c = np.stack([s[f"f_rest_{i}"] for i in range(3)], 1)[0]
    c2 = np.stack([t[f"f_rest_{i}"] for i in range(3)], 1)[0]
    d = np.array([[0.0, 0.0, 1.0], [0.6, 0.8, 0.0]])
    np.testing.assert_allclose(sh_band(1, d @ rot.T) @ c2, sh_band(1, d) @ c, atol=1e-5)


def test_ply_round_trip(tmp_path):
    s = _splats(10)
    order = sorted(s)
    write_ply(tmp_path / "a.ply", s, order, ["test"])
    back, props = read_ply(tmp_path / "a.ply")
    assert props == order
    for k in order:
        np.testing.assert_array_equal(back[k], s[k])


class _FakeRot:
    def __init__(self, m):
        self._m = m

    def matrix(self):
        return self._m


class _FakePose:
    def __init__(self, m):
        self.rotation = _FakeRot(m)


class _FakeImage:
    def __init__(self, name, center, cam_from_world):
        self.name, self._c, self._r = name, center, cam_from_world

    def projection_center(self):
        return self._c

    def cam_from_world(self):
        return _FakePose(self._r)


class _FakePoint:
    def __init__(self, xyz):
        self.xyz = xyz


class _FakeRec:
    def __init__(self, images, points):
        self.images = dict(enumerate(images))
        self.points3D = dict(enumerate(points))


def test_alignment_recovers_ground_scale_and_up():
    from vantara_pipeline.publish import estimate_alignment

    rng = np.random.default_rng(3)
    world = _random_rotation(7)  # true world (y up, metres) -> arbitrary COLMAP frame
    k = 0.37  # COLMAP units per metre
    ground = np.c_[rng.uniform(-10, 10, 800), np.zeros(800), rng.uniform(-10, 10, 800)]
    walls = np.c_[rng.uniform(-10, 10, 200), rng.uniform(0, 4, 200), np.full(200, 10.0)]
    to_colmap = lambda p: k * p @ world.T  # noqa: E731
    images = []
    for i, x in enumerate(np.linspace(-5, 5, 30)):
        center_m = np.array([x, 1.5 + rng.normal(0, 0.03), rng.normal(0, 0.2)])
        # Camera looks along +X in metres; camera axes: x right, y down, z forward.
        cam_axes_world = np.stack([[0, 0, 1.0], [0, -1.0, 0], [1.0, 0, 0]])  # rows: cam x,y,z in world
        r_world_to_cam = cam_axes_world @ world.T  # applied to COLMAP-frame vectors
        images.append(_FakeImage(f"v01_{i:06d}.jpg", to_colmap(center_m), r_world_to_cam))
    rec = _FakeRec(images, [_FakePoint(p) for p in to_colmap(np.r_[ground, walls])])

    align, warnings = estimate_alignment(rec, eye_height=1.5, scale=None, north_deg=None)
    assert align.scale == pytest.approx(1 / k, rel=0.03)
    # Ground points land on y = 0 and cameras at 1.5 m.
    g = align.apply(to_colmap(ground))
    assert np.abs(g[:, 1]).max() < 0.05
    cams = align.apply(np.array([im.projection_center() for im in images]))
    assert np.median(cams[:, 1]) == pytest.approx(1.5, abs=0.05)
    # The walk (+X in metres, first to last) becomes -Z.
    walk = cams[-1] - cams[0]
    assert walk[2] < -0.9 * np.linalg.norm(walk)
    assert not [w for w in warnings if "ground" in w.lower()]


def test_glb_rotation_round_trip(tmp_path):
    import json
    import struct

    from vantara_pipeline.glb import rotate_vertices

    pos = np.array([[1, 2, 3], [-4, 5, 6], [7, -8, 9]], np.float32)
    idx = np.array([0, 1, 2], np.uint16)
    binary = pos.tobytes() + idx.tobytes() + b"\0\0"
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [0, 0, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(binary))
    glb += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    path = tmp_path / "t.glb"
    path.write_bytes(glb)

    bounds = rotate_vertices(path, np.diag([-1.0, -1.0, 1.0]))
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    out = np.frombuffer(data, np.float32, count=9, offset=20 + n + 8).reshape(3, 3)
    np.testing.assert_allclose(out, pos * [-1, -1, 1])
    assert bounds["min"] == [-7.0, -5.0, 3.0] and bounds["max"] == [4.0, 8.0, 9.0]
    assert np.frombuffer(data, np.uint16, count=3, offset=20 + n + 8 + 36).tolist() == [0, 1, 2]
