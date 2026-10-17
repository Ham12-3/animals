"""Phase 5: clean, align and compress a trained splat for the web.

    uv run publish-splat <zone-or-name>

Reads work/<zone>/splat/<zone>.ply and the COLMAP model it was trained on, and
writes work/<zone>/publish/:

    <zone>.spz            desktop build (default budget 40 MB)
    <zone>.mobile.spz     mobile LOD: no view-dependent colour, fewer splats (15 MB)
    <zone>.collision.glb  invisible collision mesh (20 cm voxels), same frame
    <zone>.json           metadata for the web app: units, spawn point, bounds,
                          camera path, north, file sizes
    preview_*.webp        renders before/after cleanup, for review
    publish_report.json   what each step removed and why

Alignment: the ground plane is fitted to the SfM points (RANSAC, constrained
to the cameras' average up direction) and becomes y = 0 with +Y up (three.js).
Metric scale assumes the camera moved at ``eye_height`` metres above the
ground (handheld walkthrough: 1.5 m), unless a scale is given. North cannot be
recovered from video: set ``align.northDeg`` in zones.json (compass heading of
the scene's -Z axis after alignment, found by matching the top-down view to a
satellite map), otherwise -Z is just the main walking direction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pycolmap

from . import PIPELINE_DIR, WORK_DIR, ZONES_FILE
from .glb import rotate_vertices
from .splat_ply import read_ply, select, sh_degree, transform, write_ply

SPLAT_TRANSFORM = PIPELINE_DIR / "node_modules" / ".bin" / ("splat-transform.cmd" if os.name == "nt" else "splat-transform")


@dataclass
class Alignment:
    rotation: list[list[float]]  # 3x3, COLMAP frame -> aligned frame
    origin: list[float]  # COLMAP-frame point that becomes (0, 0, 0)
    scale: float  # COLMAP units -> metres
    eye_height_m: float
    ground_inlier_ratio: float
    north_deg: float | None  # compass heading of aligned -Z, if known

    def apply(self, p: np.ndarray) -> np.ndarray:
        return self.scale * (p - np.array(self.origin)) @ np.array(self.rotation).T


@dataclass
class Budget:
    desktop_mb: float = 40.0
    mobile_mb: float = 15.0
    mobile_max_splats: int = 500_000
    desktop_max_sh: int = 3


@dataclass
class Report:
    zone: str
    stages: dict[str, int] = field(default_factory=dict)
    alignment: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0


# --- alignment -----------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _fit_ground(points: np.ndarray, up: np.ndarray, cam_heights: np.ndarray, iters: int = 3000):
    """RANSAC plane among points below the cameras, normal within 25 deg of ``up``."""
    h = points @ up
    below = points[h < np.median(cam_heights)]
    if len(below) < 30:
        below = points
    spread = float(np.percentile(h, 95) - np.percentile(h, 5)) or 1.0
    thresh = 0.02 * spread
    rng = np.random.default_rng(0)
    best_n, best_d, best_count = None, None, 0
    for _ in range(iters):
        a, b, c = below[rng.choice(len(below), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-9:
            continue
        n = _unit(n)
        if n @ up < 0:
            n = -n
        if n @ up < math.cos(math.radians(25)):
            continue
        d = n @ a
        count = int(np.sum(np.abs(below @ n - d) < thresh))
        if count > best_count:
            best_n, best_d, best_count = n, d, count
    if best_n is None:
        return None
    inl = below[np.abs(below @ best_n - best_d) < thresh]
    centroid = inl.mean(0)
    n = _unit(np.linalg.svd(inl - centroid)[2][2])  # refine with all inliers
    if n @ up < 0:
        n = -n
    return n, centroid, best_count / len(below)


def estimate_alignment(
    rec: pycolmap.Reconstruction, eye_height: float, scale: float | None, north_deg: float | None
) -> tuple[Alignment, list[str]]:
    warnings = []
    images = sorted(rec.images.values(), key=lambda im: im.name)
    centers = np.array([im.projection_center() for im in images])
    # Image "up" is -y in COLMAP camera coordinates; average it in world space.
    ups = np.array([im.cam_from_world().rotation.matrix().T @ np.array([0.0, -1.0, 0.0]) for im in images])
    up = _unit(ups.mean(0))
    points = np.array([p.xyz for p in rec.points3D.values()])

    fit = _fit_ground(points, up, centers @ up)
    if fit is None or fit[2] < 0.05:
        warnings.append("No clear ground plane in the SfM points; levelled from camera orientation only.")
        n = up
        ground_pt = points[np.argmin(np.abs(points @ up - np.percentile(points @ up, 5)))]
        ratio = 0.0 if fit is None else fit[2]
    else:
        n, ground_pt, ratio = fit
        tilt = math.degrees(math.acos(min(1.0, float(n @ up))))
        if tilt > 10:
            warnings.append(f"Ground plane is {tilt:.0f} deg off the cameras' up: sloped ground, or the fit picked a wall.")

    heights = (centers - ground_pt) @ n
    cam_h = float(np.median(heights))
    if cam_h <= 0:
        warnings.append("Cameras are not above the fitted ground; flipping the plane.")
        n, heights, cam_h = -n, -heights, -cam_h
    s = scale if scale else eye_height / cam_h

    # Forward (-Z) = main walking direction projected onto the ground plane.
    travel = centers - centers.mean(0)
    travel -= np.outer(travel @ n, n)
    fwd = _unit(np.linalg.svd(travel)[2][0]) if np.linalg.norm(travel) > 1e-9 else None
    if fwd is None or abs(fwd @ n) > 0.99:
        look = np.array([im.cam_from_world().rotation.matrix().T @ np.array([0.0, 0.0, 1.0]) for im in images])
        fwd = _unit(look.mean(0) - (look.mean(0) @ n) * n)
    # Point forward the way the walk goes (first camera -> last camera).
    if (centers[-1] - centers[0]) @ fwd < 0:
        fwd = -fwd
    y_axis = n
    z_axis = -fwd  # three.js looks down -Z
    x_axis = _unit(np.cross(y_axis, z_axis))
    z_axis = np.cross(x_axis, y_axis)
    rot = np.stack([x_axis, y_axis, z_axis])

    if north_deg is not None:
        # Rotate about +Y so that aligned -Z points at the given compass heading
        # relative to north = -Z: yaw by +north_deg (counter-clockwise from above).
        t = math.radians(north_deg)
        yaw = np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])
        rot = yaw @ rot

    # Origin: ground point under the middle of the camera path.
    mid = centers.mean(0)
    origin = mid - ((mid - ground_pt) @ n) * n
    return Alignment(rot.tolist(), origin.tolist(), float(s), eye_height, round(float(ratio), 3), north_deg), warnings


# --- cleanup and export ----------------------------------------------------------


def _st(*args: str | Path) -> None:
    cmd = [str(SPLAT_TRANSFORM), "-q", "-w", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"splat-transform failed: {' '.join(cmd)}\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")


def _count(path: Path) -> int:
    with open(path, "rb") as fh:
        for raw in fh:
            if raw.startswith(b"element vertex"):
                return int(raw.split()[-1])
    return 0


def _spz(src_ply: Path, dest: Path, sh: int) -> float:
    _st(src_ply, "-H", str(sh), "--spz-version", "3", dest)
    return dest.stat().st_size / 1e6


def _fit_budget(clean: Path, dest: Path, max_mb: float, sh_levels: list[int], max_splats: int | None, tmp: Path) -> dict:
    """Highest SH degree that fits, then decimate until the file is under budget."""
    n = _count(clean)
    src = clean
    if max_splats and n > max_splats:
        src = tmp / f"{dest.stem}.decimated.ply"
        _st(clean, "--decimate", str(max_splats), src)
        n = _count(src)
    for sh in sh_levels:
        mb = _spz(src, dest, sh)
        if mb <= max_mb:
            return {"file": dest.name, "mb": round(mb, 2), "splats": n, "sh_degree": sh}
    sh = sh_levels[-1]
    for _ in range(6):
        target = int(n * max_mb / mb * 0.95)
        src = tmp / f"{dest.stem}.decimated.ply"
        _st(clean, "--decimate", str(target), src)
        n = _count(src)
        mb = _spz(src, dest, sh)
        if mb <= max_mb:
            break
    return {"file": dest.name, "mb": round(mb, 2), "splats": n, "sh_degree": sh}


def _render(ply: Path, dest: Path, pos, target, fov: float) -> None:
    # splat-transform works in PlayCanvas' frame, where x and y are negated
    # relative to the PLY (verified with a three-point probe); convert the camera.
    def flip(v):
        return f"{-v[0]:.3f},{-v[1]:.3f},{v[2]:.3f}"

    _st(ply, "--camera-pos", flip(pos), "--camera-target", flip(target), "--camera-up", "0,-1,0",
        "--camera-fov", f"{fov:.1f}", "--resolution", "960x540", "--camera-near", "0.05", dest)  # fmt: skip


def publish(zone_dir: Path, eye_height: float, scale: float | None, north_deg: float | None, budget: Budget,
            previews: bool = True) -> dict:  # fmt: skip
    t0 = time.time()
    zone = zone_dir.name
    report = Report(zone)
    ply_in = zone_dir / "splat" / f"{zone}.ply"
    model = zone_dir / "colmap" / "undistorted" / "sparse"
    if not ply_in.is_file():
        raise SystemExit(f"no splat at {ply_in}; run train-splat first (or put the Colab PLY there)")
    out = zone_dir / "publish"
    # Hand-authored files survive a re-publish; everything else is rebuilt.
    keep = {f: (out / f).read_bytes() for f in ("hotspots.json",) if (out / f).is_file()}
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for f, data in keep.items():
        (out / f).write_bytes(data)
    tmp = out / "_tmp"
    tmp.mkdir(parents=True)

    rec = pycolmap.Reconstruction(model)
    align, warns = estimate_alignment(rec, eye_height, scale, north_deg)
    report.warnings += warns
    report.alignment = asdict(align)

    splats, order = read_ply(ply_in)
    report.stages["input"] = len(splats["x"])
    splats = transform(splats, np.array(align.rotation), np.array(align.origin), align.scale)

    images = sorted(rec.images.values(), key=lambda im: im.name)
    cams = align.apply(np.array([im.projection_center() for im in images]))
    pts = align.apply(np.array([p.xyz for p in rec.points3D.values()]))

    # 1. Invalid and invisible splats.
    pos = np.stack([splats["x"], splats["y"], splats["z"]], 1)
    finite = np.isfinite(np.stack(list(splats.values()), 1)).all(1)
    opacity = 1 / (1 + np.exp(-splats["opacity"]))
    keep = finite & (opacity >= 0.02)
    report.stages["after_opacity"] = int(keep.sum())

    # 2. Oversized blobs: anything wider than 3 m (1 sigma) is a smear, not structure.
    size = np.exp(np.max(np.stack([splats[f"scale_{i}"] for i in range(3)], 1), 1))
    keep &= size < 3.0
    report.stages["after_size"] = int(keep.sum())

    # 3. Crop to the reconstructed area: SfM extent (1-99%) plus margin, and the
    #    camera path plus 3 m, from 1.5 m below ground.
    lo = np.minimum(np.percentile(pts, 1, 0), cams.min(0) - 3)
    hi = np.maximum(np.percentile(pts, 99, 0), cams.max(0) + 3)
    pad = 0.1 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    lo[1] = -1.5
    keep &= np.all((pos >= lo) & (pos <= hi), 1)
    report.stages["after_crop"] = int(keep.sum())
    splats = select(splats, keep)

    aligned = tmp / "aligned.ply"
    write_ply(aligned, splats, order, ["Vantara 3D: aligned, metres, +Y up"])

    # 4. Floaters: splats that don't contribute to any solid voxel (5 cm grid).
    clean = tmp / "clean.ply"
    _st(aligned, "-N", "-F", "0.05,0.1,0.004", clean)
    report.stages["after_floaters"] = _count(clean)

    deg = sh_degree(splats)
    desktop_levels = list(range(min(deg, budget.desktop_max_sh), -1, -1))
    report.outputs["desktop"] = _fit_budget(clean, out / f"{zone}.spz", budget.desktop_mb, desktop_levels, None, tmp)
    report.outputs["mobile"] = _fit_budget(
        clean, out / f"{zone}.mobile.spz", budget.mobile_mb, [0], budget.mobile_max_splats, tmp
    )

    # 5. Invisible collision mesh: solid voxels (20 cm) meshed by splat-transform.
    #    Its output is in splat-transform's internal frame (x and y negated, a
    #    180 deg turn about Z), so rotate it back into the splat's frame.
    _st(clean, "--voxel-size", "0.2", "--voxel-opacity", "0.3", "--collision-mesh", "smooth", tmp / "col.voxel.json")
    collision = out / f"{zone}.collision.glb"
    shutil.move(tmp / "col.collision.glb", collision)
    rotate_vertices(collision, np.diag([-1.0, -1.0, 1.0]))
    report.outputs["collision"] = {"file": collision.name, "mb": round(collision.stat().st_size / 1e6, 2)}

    first = images[0]
    look = first.cam_from_world().rotation.matrix().T @ np.array([0.0, 0.0, 1.0])
    look_aligned = np.array(align.rotation) @ look
    yaw = math.degrees(math.atan2(-look_aligned[0], -look_aligned[2]))
    cam = rec.cameras[first.camera_id]
    fov_y = math.degrees(2 * math.atan(cam.height / 2 / cam.focal_length_y))
    meta = {
        "zone": zone,
        "units": "m",
        "up": [0, 1, 0],
        "groundY": 0.0,
        "files": {k: v["file"] for k, v in report.outputs.items()},
        "sizesMB": {k: v["mb"] for k, v in report.outputs.items()},
        "splats": {k: v["splats"] for k, v in report.outputs.items() if "splats" in v},
        "bounds": {"min": np.round(lo, 2).tolist(), "max": np.round(hi, 2).tolist()},
        "spawn": {"position": np.round(cams[0], 3).tolist(), "yawDeg": round(yaw, 1)},
        "eyeHeight": eye_height,
        "cameraPath": np.round(cams[:: max(1, len(cams) // 60)], 3).tolist(),
        "fovY": round(fov_y, 1),
        "north": {"deg": north_deg, "known": north_deg is not None},
    }
    (out / f"{zone}.json").write_text(json.dumps(meta, indent=2))
    if north_deg is None:
        report.warnings.append("North unknown: set align.northDeg in zones.json after checking topdown.webp against a map.")
    if scale is None:
        report.warnings.append(f"Scale assumes the camera was carried {eye_height} m above the ground.")

    if previews:
        target = cams[0] + look_aligned * 3
        _render(aligned, out / "preview_before.webp", cams[0], target, fov_y)
        _render(out / f"{zone}.spz", out / "preview_after.webp", cams[0], target, fov_y)
        _render(out / f"{zone}.mobile.spz", out / "preview_mobile.webp", cams[0], target, fov_y)
        c = (lo + hi) / 2
        top = [c[0], hi[1] + max(hi[0] - lo[0], hi[2] - lo[2]), c[2] + 1e-3]
        _render(out / f"{zone}.spz", out / "topdown.webp", top, [c[0], 0, c[2]], 60)

    shutil.rmtree(tmp, ignore_errors=True)
    report.seconds = round(time.time() - t0, 1)
    (out / "publish_report.json").write_text(json.dumps(asdict(report), indent=2))
    return asdict(report)


def _zone_align(zone: str) -> dict:
    data = json.loads(ZONES_FILE.read_text(encoding="utf-8"))
    for z in data["zones"]:
        if z["id"] == zone:
            return z.get("align", {})
    return {}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="publish-splat", description=__doc__.split("\n\n")[0])
    p.add_argument("zone", help="folder name under work/")
    p.add_argument("--eye-height", type=float, help="camera height above ground in metres (default 1.5)")
    p.add_argument("--scale", type=float, help="explicit COLMAP-units-to-metres factor (overrides eye height)")
    p.add_argument("--north", type=float, help="compass heading of aligned -Z in degrees")
    p.add_argument("--desktop-mb", type=float, default=Budget.desktop_mb)
    p.add_argument("--mobile-mb", type=float, default=Budget.mobile_mb)
    p.add_argument("--mobile-max-splats", type=int, default=Budget.mobile_max_splats)
    p.add_argument("--no-previews", action="store_true")
    p.add_argument("--work-dir", type=Path, default=WORK_DIR)
    a = p.parse_args(argv)
    if not SPLAT_TRANSFORM.exists():
        raise SystemExit("splat-transform missing: run `npm install` in pipeline/")
    cfg = _zone_align(a.zone)  # zones.json "align": {"eyeHeight", "scale", "northDeg"}
    eye = a.eye_height or cfg.get("eyeHeight", 1.5)
    scale = a.scale or cfg.get("scale")
    north = a.north if a.north is not None else cfg.get("northDeg")
    budget = Budget(a.desktop_mb, a.mobile_mb, a.mobile_max_splats)
    r = publish(a.work_dir / a.zone, eye, scale, north, budget, not a.no_previews)

    s = r["stages"]
    print(f"\nZone {r['zone']}: {s['input']:,} splats in -> "
          f"opacity {s['after_opacity']:,} -> size {s['after_size']:,} -> crop {s['after_crop']:,} -> "
          f"floaters {s['after_floaters']:,}")  # fmt: skip
    al = r["alignment"]
    print(f"  scale {al['scale']:.3f} m/unit (eye height {al['eye_height_m']} m), ground fit {al['ground_inlier_ratio']:.0%}")
    for k, o in r["outputs"].items():
        detail = f"{o['splats']:>9,} splats  SH{o['sh_degree']}" if "splats" in o else ""
        print(f"  {k:<9} {o['file']:<40} {o['mb']:>6} MB  {detail}")
    for w in r["warnings"]:
        print(f"  ! {w}")


if __name__ == "__main__":
    main()
