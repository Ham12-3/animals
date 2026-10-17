"""Read, write and rigidly transform 3D Gaussian splat PLY files.

Columns follow the 3DGS convention: x/y/z, f_dc_0..2, f_rest_* (stored
channel-major: R coefficients, then G, then B), opacity (logit), scale_0..2
(log), rot_0..3 (quaternion w, x, y, z).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

Splats = dict[str, np.ndarray]


def read_ply(path: Path) -> tuple[Splats, list[str]]:
    raw = path.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError(f"{path}: only binary little-endian PLY is supported")
    n = int(next(line for line in header if line.startswith("element vertex")).split()[-1])
    props = []
    for line in header:
        if line.startswith("property"):
            _, kind, name = line.split()
            if kind != "float":
                raise ValueError(f"{path}: property {name} is {kind}, expected float")
            props.append(name)
    data = np.frombuffer(raw, np.float32, count=n * len(props), offset=end).reshape(n, len(props))
    return {p: data[:, i].copy() for i, p in enumerate(props)}, props


def write_ply(path: Path, splats: Splats, order: list[str], comments: list[str] = ()) -> None:
    n = len(splats["x"])
    head = ["ply", "format binary_little_endian 1.0", *(f"comment {c}" for c in comments), f"element vertex {n}"]
    head += [f"property float {p}" for p in order] + ["end_header"]
    body = np.stack([splats[p].astype(np.float32) for p in order], 1)
    with open(path, "wb") as fh:
        fh.write(("\n".join(head) + "\n").encode("ascii"))
        fh.write(np.ascontiguousarray(body).tobytes())


def select(splats: Splats, keep: np.ndarray) -> Splats:
    return {k: v[keep] for k, v in splats.items()}


def sh_degree(splats: Splats) -> int:
    rest = sum(k.startswith("f_rest_") for k in splats) // 3
    return {0: 0, 3: 1, 8: 2, 15: 3}[rest]


# --- spherical harmonics -----------------------------------------------------

_C1 = 0.4886025119029199
_C2 = (1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396)
_C3 = (-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154,
       -0.4570457994644658, 1.445305721320277, -0.5900435899266435)  # fmt: skip


def sh_band(level: int, d: np.ndarray) -> np.ndarray:
    """Real SH basis of one band, as used by 3DGS renderers. d: (N, 3) unit vectors."""
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    if level == 1:
        return np.stack([-_C1 * y, _C1 * z, -_C1 * x], 1)
    if level == 2:
        return np.stack([_C2[0] * x * y, _C2[1] * y * z, _C2[2] * (2 * z * z - x * x - y * y),
                         _C2[3] * x * z, _C2[4] * (x * x - y * y)], 1)  # fmt: skip
    if level == 3:
        return np.stack([
            _C3[0] * y * (3 * x * x - y * y), _C3[1] * x * y * z, _C3[2] * y * (4 * z * z - x * x - y * y),
            _C3[3] * z * (2 * z * z - 3 * x * x - 3 * y * y), _C3[4] * x * (4 * z * z - x * x - y * y),
            _C3[5] * z * (x * x - y * y), _C3[6] * x * (x * x - 3 * y * y),
        ], 1)  # fmt: skip
    raise ValueError(level)


def sh_rotation(level: int, rot: np.ndarray) -> np.ndarray:
    """Matrix M with new_coeffs = M @ old_coeffs when the scene is rotated by ``rot``.

    A rotated splat must show colour c(rot^T d) in direction d. Each SH band is
    closed under rotation, so Y(rot^T d) = A^T Y(d) for some A, found here by
    least squares over many directions; new coefficients are then A @ old.
    """
    rng = np.random.default_rng(0)
    d = rng.normal(size=(512, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    a, *_ = np.linalg.lstsq(sh_band(level, d), sh_band(level, d @ rot), rcond=None)  # d @ rot == (rot^T d)^T
    return a


def _quat_from_matrix(m: np.ndarray) -> np.ndarray:
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2, m[2, 1] - m[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2, m[0, 2] - m[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2, m[1, 0] - m[0, 1])
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def transform(splats: Splats, rot: np.ndarray, origin: np.ndarray, scale: float) -> Splats:
    """Rigid transform plus uniform scale: p' = scale * rot @ (p - origin)."""
    out = dict(splats)
    p = np.stack([splats["x"], splats["y"], splats["z"]], 1).astype(np.float64)
    p = scale * (p - origin) @ rot.T
    out["x"], out["y"], out["z"] = (p[:, i].astype(np.float32) for i in range(3))

    # Orientation: q' = q_rot * q (Hamilton product, w first).
    w0, x0, y0, z0 = _quat_from_matrix(rot)
    w, x, y, z = (splats[f"rot_{i}"].astype(np.float64) for i in range(4))
    out["rot_0"] = (w0 * w - x0 * x - y0 * y - z0 * z).astype(np.float32)
    out["rot_1"] = (w0 * x + x0 * w + y0 * z - z0 * y).astype(np.float32)
    out["rot_2"] = (w0 * y - x0 * z + y0 * w + z0 * x).astype(np.float32)
    out["rot_3"] = (w0 * z + x0 * y - y0 * x + z0 * w).astype(np.float32)

    for i in range(3):
        out[f"scale_{i}"] = (splats[f"scale_{i}"] + np.log(scale)).astype(np.float32)

    degree = sh_degree(splats)
    per_channel = (degree + 1) ** 2 - 1
    start = 0
    for level in range(1, degree + 1):
        m = sh_rotation(level, rot)
        width = 2 * level + 1
        for ch in range(3):
            names = [f"f_rest_{ch * per_channel + start + k}" for k in range(width)]
            coeffs = np.stack([splats[n] for n in names], 1).astype(np.float64)
            new = coeffs @ m.T
            for k, n in enumerate(names):
                out[n] = new[:, k].astype(np.float32)
        start += width
    return out
