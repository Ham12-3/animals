import math

import numpy as np

from vantara_pipeline.lighting import SH_C0, estimate_lighting


def _quat_z_to(n: np.ndarray) -> np.ndarray:
    """Quaternions (w, x, y, z) rotating +Z onto each normal."""
    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(np.broadcast_to(z, n.shape), n)
    s = np.linalg.norm(axis, axis=1, keepdims=True)
    angle = np.arctan2(s[:, 0], n @ z)
    axis = np.where(s > 1e-9, axis / np.maximum(s, 1e-9), [1.0, 0.0, 0.0])
    half = angle / 2
    return np.c_[np.cos(half), axis * np.sin(half)[:, None]]


def _linear_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def test_recovers_sun_direction_and_strength():
    rng = np.random.default_rng(1)
    n = 6000
    normals = rng.normal(size=(n, 3))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    pos = 5 * normals
    sun_dir = np.array([0.4, 0.8, -0.45])
    sun_dir /= np.linalg.norm(sun_dir)
    e_ambient, e_sun = np.array([0.5, 0.55, 0.65]), np.array([2.2, 2.0, 1.7])
    albedo = rng.uniform(0.25, 0.45, (n, 1))
    radiance = albedo / math.pi * (e_ambient + e_sun * np.clip(normals @ sun_dir, 0, None)[:, None])
    f_dc = (_linear_to_srgb(radiance) - 0.5) / SH_C0

    q = _quat_z_to(normals)
    # Random sign: the estimator has to orient normals towards the viewpoints itself.
    sign = rng.choice([-1.0, 1.0], n)
    q[sign < 0] = np.c_[-q[sign < 0, 2], q[sign < 0, 3], q[sign < 0, 0], -q[sign < 0, 1]]  # 180 deg about local X
    splats = {
        "x": pos[:, 0], "y": pos[:, 1], "z": pos[:, 2],
        "opacity": np.full(n, 4.0),
        "scale_0": np.full(n, math.log(0.1)), "scale_1": np.full(n, math.log(0.1)), "scale_2": np.full(n, math.log(0.005)),
        **{f"f_dc_{i}": f_dc[:, i] for i in range(3)},
        **{f"rot_{i}": q[:, i] for i in range(4)},
    }  # fmt: skip
    views = rng.normal(size=(200, 3))
    views = 30 * views / np.linalg.norm(views, axis=1, keepdims=True)

    light = estimate_lighting(splats, views)

    assert light["estimated"]
    got = np.array(light["sun"]["direction"])
    assert math.degrees(math.acos(np.clip(got @ sun_dir, -1, 1))) < 8
    np.testing.assert_allclose(light["sun"]["color"], e_sun, rtol=0.3)
    np.testing.assert_allclose(light["ambient"], e_ambient, rtol=0.35)


def test_too_few_samples_falls_back():
    splats = {k: np.zeros(5) for k in ["x", "y", "z", "opacity", "f_dc_0", "f_dc_1", "f_dc_2", "rot_1", "rot_2", "rot_3"]}
    splats.update({"rot_0": np.ones(5), **{f"scale_{i}": np.zeros(5) for i in range(3)}})
    light = estimate_lighting(splats, np.zeros((1, 3)))
    assert not light["estimated"] and light["samples"] == 0


def test_sun_kept_above_horizon():
    from vantara_pipeline.lighting import fit_lighting

    rng = np.random.default_rng(2)
    normals = rng.normal(size=(3000, 3))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    # Downward-facing surfaces brightest, as with a white ceiling.
    colours = 0.2 + 0.15 * np.clip(-normals[:, 1:2], 0, None) * np.ones((1, 3))
    light = fit_lighting(normals, colours, np.ones(len(normals)))
    assert light["sunClampedAboveHorizon"]
    assert light["sun"]["direction"][1] > 0.19
