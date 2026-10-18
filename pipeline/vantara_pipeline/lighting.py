"""Estimate a zone's lighting from its splats, to light animals so they match.

Splats on real surfaces are flat discs: the axis with the smallest scale is
the surface normal. Their colour is the light the surface sends back. Fitting
colour as a linear function of normal, per channel,

    L(n) = a + b . n

is the first-order (L1) spherical-harmonic irradiance model. Under ambient
light E_a plus a sun E_s from direction s, a Lambert surface of albedo rho
looks like  rho/pi * (E_a + E_s * max(0, n.s)),  and max(0, c) ~ 1/4 + c/2 on
the sphere, so

    E_s = 2 pi |b| / rho,   E_a = pi a / rho - E_s / 4,

which map straight onto three.js AmbientLight / DirectionalLight intensities
(irradiance, linear RGB). rho is the scene's average albedo, assumed ~0.35.
"""

from __future__ import annotations

import math

import numpy as np

from .splat_ply import Splats

SH_C0 = 0.28209479177387814
MIN_SUN_ELEVATION = 0.2  # sin of ~12 degrees


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _quat_to_mats(q: np.ndarray) -> np.ndarray:
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    w, x, y, z = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
    ], 1)  # fmt: skip  # (N, 3, 3), columns = local axes in world space


def surface_samples(splats: Splats, viewpoints: np.ndarray, max_samples: int = 200_000, seed: int = 0):
    """Normals and linear colours of opaque, flat splats, normals facing the cameras."""
    opacity = 1 / (1 + np.exp(-splats["opacity"]))
    scales = np.exp(np.stack([splats[f"scale_{i}"] for i in range(3)], 1))
    order = np.sort(scales, 1)
    flat = order[:, 0] < 0.35 * order[:, 1]
    keep = np.flatnonzero((opacity > 0.6) & flat & np.isfinite(scales).all(1))
    if len(keep) > max_samples:
        keep = np.random.default_rng(seed).choice(keep, max_samples, replace=False)
    if len(keep) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0)

    q = np.stack([splats[f"rot_{i}"][keep] for i in range(4)], 1).astype(np.float64)
    mats = _quat_to_mats(q)
    thin = np.argmin(scales[keep], 1)
    normals = mats[np.arange(len(keep)), :, thin]
    pos = np.stack([splats["x"][keep], splats["y"][keep], splats["z"][keep]], 1).astype(np.float64)

    # A disc's normal sign is arbitrary: point it at the nearest viewpoint, which saw that side.
    vp = viewpoints[:: max(1, len(viewpoints) // 64)]
    nearest = np.empty((len(pos), 3))
    for i in range(0, len(pos), 20_000):
        chunk = pos[i : i + 20_000]
        d = ((chunk[:, None, :] - vp[None, :, :]) ** 2).sum(-1)
        nearest[i : i + 20_000] = vp[np.argmin(d, 1)]
    flip = np.einsum("ij,ij->i", normals, nearest - pos) < 0
    normals[flip] *= -1

    rgb = 0.5 + SH_C0 * np.stack([splats[f"f_dc_{i}"][keep] for i in range(3)], 1)
    weights = opacity[keep] * order[keep, 1] * order[keep, 2]  # opaque, large discs count more
    return normals, srgb_to_linear(rgb), weights


def fit_lighting(normals: np.ndarray, colours: np.ndarray, weights: np.ndarray, albedo: float = 0.35) -> dict:
    """Ambient + sun (three.js irradiance, linear RGB) from surface samples."""
    if len(normals) < 200:
        return default_lighting(reason="too few flat splats to estimate lighting")
    w = np.sqrt(weights / weights.mean())[:, None]
    design = np.c_[np.ones(len(normals)), normals] * w
    coef, *_ = np.linalg.lstsq(design, colours * w, rcond=None)  # (4, 3): rows a, bx, by, bz
    a, b = coef[0], coef[1:]  # b: (3 axes, 3 channels)
    lum = np.array([0.2126, 0.7152, 0.0722])
    direction = b @ lum
    strength = np.linalg.norm(direction)
    if strength < 1e-6:
        return default_lighting(reason="no directional component found")
    direction /= strength
    b_along = np.clip(direction @ b, 0, None)  # per channel, along the light direction
    # Bright-coloured ceilings or floors can pull the fit below the horizon
    # (albedo read as light). Meshes lit from below look wrong: keep the sun up.
    clamped = bool(direction[1] < MIN_SUN_ELEVATION)
    if clamped:
        direction[1] = MIN_SUN_ELEVATION
        flat_len = np.linalg.norm(direction[[0, 2]])
        scale = math.sqrt(1 - MIN_SUN_ELEVATION**2) / flat_len if flat_len > 1e-6 else 0.0
        direction[[0, 2]] *= scale
        if flat_len <= 1e-6:
            direction = np.array([0.0, 1.0, 0.0])
        direction /= np.linalg.norm(direction)
    sun = 2 * np.pi * b_along / albedo
    ambient = np.clip(np.pi * a / albedo - sun / 4, 0.02, None)

    pred = np.c_[np.ones(len(normals)), normals] @ coef
    resid = ((pred - colours) ** 2 * weights[:, None]).sum()
    total = (((colours - colours.mean(0)) ** 2) * weights[:, None]).sum()
    return {
        "ambient": np.round(ambient, 4).tolist(),
        "sun": {"direction": np.round(direction, 4).tolist(), "color": np.round(sun, 4).tolist()},
        "albedoAssumed": albedo,
        "samples": int(len(normals)),
        # Most colour variation is albedo, not light: a low share explained is expected.
        "varianceExplained": round(float(1 - resid / max(total, 1e-12)), 3),
        "sunClampedAboveHorizon": clamped,
        "estimated": True,
    }


def default_lighting(reason: str) -> dict:
    return {
        "ambient": [0.9, 0.9, 0.9],
        "sun": {"direction": [0.3, 0.9, 0.3], "color": [1.6, 1.55, 1.45]},
        "albedoAssumed": 0.35,
        "samples": 0,
        "varianceExplained": 0.0,
        "estimated": False,
        "note": reason,
    }


def estimate_lighting(splats: Splats, viewpoints: np.ndarray) -> dict:
    return fit_lighting(*surface_samples(splats, viewpoints))
