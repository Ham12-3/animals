"""Phase 3: solve camera poses for a zone's frames with COLMAP (pycolmap, CPU).

    uv run solve-poses <zone-or-name>

Reads work/<zone>/frames (and masks/ if present) from extract-frames and writes
work/<zone>/colmap/:

    database.db          SIFT features and verified matches
    sparse/0/            largest reconstruction (cameras, images, points)
    sparse/1.. /         any other disconnected pieces
    undistorted/         pinhole images + model, the input for splat training
    points.ply           sparse point cloud, for a quick look
    topdown.jpg          camera path and points seen from above
    poses_report.json    registration rate, diagnostics, suggestions
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import pycolmap

from . import WORK_DIR

TARGET_REGISTRATION = 0.7


def _video_of(name: str) -> str:
    return name.split("_", 1)[0]  # "v01_000123.jpg" -> "v01"


def extract(db: Path, frames: Path, masks: Path | None, names: list[str], camera: str, max_size: int) -> None:
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    if masks is not None:
        reader.mask_path = masks
    opts = pycolmap.FeatureExtractionOptions()
    opts.max_image_size = max_size
    opts.sift.max_num_features = 8192
    if camera == "single":
        groups = [names]
        mode = pycolmap.CameraMode.SINGLE
    elif camera == "per-video":
        # Each source clip may have its own zoom/lens: one camera per clip.
        by_video = defaultdict(list)
        for n in names:
            by_video[_video_of(n)].append(n)
        groups = list(by_video.values())
        mode = pycolmap.CameraMode.SINGLE
    else:
        groups = [names]
        mode = pycolmap.CameraMode.PER_IMAGE
    for g in groups:
        pycolmap.extract_features(
            db, frames, image_names=g, camera_mode=mode, reader_options=reader,
            extraction_options=opts, device=pycolmap.Device.cpu,
        )  # fmt: skip


def match(db: Path, mode: str, overlap: int) -> None:
    if mode == "exhaustive":
        pycolmap.match_exhaustive(db, device=pycolmap.Device.cpu)
        return
    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = overlap
    pairing.quadratic_overlap = True  # also tries i+2^k: links separate passes over the same spot
    pycolmap.match_sequential(db, pairing_options=pairing, device=pycolmap.Device.cpu)


def map_scene(db: Path, frames: Path, sparse: Path) -> dict[int, pycolmap.Reconstruction]:
    opts = pycolmap.IncrementalPipelineOptions()
    opts.multiple_models = True  # keep disconnected pieces so we can report them
    opts.min_model_size = 10
    sparse.mkdir(parents=True, exist_ok=True)
    return pycolmap.incremental_mapping(db, frames, sparse, options=opts)


def _db_stats(db: Path) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Keypoints per image and verified inlier matches per image pair."""
    import sqlite3

    con = sqlite3.connect(db)
    ids = dict(con.execute("SELECT image_id, name FROM images"))
    kps = {ids[i]: rows for i, rows in con.execute("SELECT image_id, rows FROM keypoints")}
    pairs = {}
    for pair_id, rows in con.execute("SELECT pair_id, rows FROM two_view_geometries WHERE rows > 0"):
        i2 = pair_id % 2147483647
        i1 = (pair_id - i2) // 2147483647
        pairs[(ids[i1], ids[i2])] = rows
    con.close()
    return kps, pairs


def topdown(rec: pycolmap.Reconstruction, dest: Path, size: int = 1600) -> None:
    """Points and camera path projected on the plane the cameras move in."""
    cams = np.array([img.projection_center() for img in sorted(rec.images.values(), key=lambda i: i.name)])
    pts = np.array([p.xyz for p in rec.points3D.values()])
    cols = np.array([p.color for p in rec.points3D.values()], np.uint8)
    if len(cams) < 3 or len(pts) == 0:
        return
    # The two main directions of camera travel span the walking plane.
    mean = cams.mean(0)
    _, _, vt = np.linalg.svd(cams - mean)
    axes = vt[:2]
    c2, p2 = (cams - mean) @ axes.T, (pts - mean) @ axes.T
    lo, hi = np.percentile(p2, 2, 0), np.percentile(p2, 98, 0)
    lo, hi = np.minimum(lo, c2.min(0)), np.maximum(hi, c2.max(0))
    scale = (size - 40) / float((hi - lo).max())
    img = np.full((size, size, 3), 18, np.uint8)

    def px(v):
        return ((v - lo) * scale + 20).astype(int)

    pp = px(p2)
    ok = (pp >= 0).all(1) & (pp < size).all(1)
    img[pp[ok, 1], pp[ok, 0]] = cols[ok][:, ::-1]
    cp = px(c2)
    for a, b in zip(cp[:-1], cp[1:]):
        cv2.line(img, tuple(map(int, a)), tuple(map(int, b)), (0, 200, 255), 1, cv2.LINE_AA)
    for c in cp:
        cv2.circle(img, tuple(map(int, c)), 3, (0, 120, 255), -1, cv2.LINE_AA)
    cv2.imwrite(str(dest), img)


def diagnose(names: list[str], registered: set[str], kps: dict[str, int], pairs: dict, models: int) -> list[str]:
    """Explain a low registration rate in terms of the footage."""
    out = []
    by_video = defaultdict(list)
    for n in names:
        by_video[_video_of(n)].append(n)
    weak_videos = [v for v, ns in by_video.items() if sum(n in registered for n in ns) / len(ns) < 0.5]
    if weak_videos:
        out.append(f"Clips that mostly failed: {', '.join(weak_videos)} (see frames.csv for which source each is).")
    few = [n for n in names if kps.get(n, 0) < 1000 and n not in registered]
    if len(few) > 0.1 * len(names):
        out.append(f"{len(few)} unregistered frames have <1000 features: blur, low light, sky, water or blank walls. "
                   "Point the camera at textured scenery (buildings, trees, ground), avoid empty sky.")  # fmt: skip
    links = Counter()
    for (a, b), n in pairs.items():
        if n >= 30:
            links[a] += 1
            links[b] += 1
    isolated = [n for n in names if links[n] == 0]
    if len(isolated) > 0.1 * len(names):
        out.append(f"{len(isolated)} frames match no other frame: consecutive frames are too far apart. "
                   "Move slower (about walking pace), turn slowly, and keep overlap between views.")  # fmt: skip
    if models > 1:
        out.append(f"The scene split into {models} disconnected pieces: footage jumps between places with no "
                   "continuous shot linking them. Film one unbroken walk that passes through each area.")  # fmt: skip
    if not out:
        out.append("Views overlap too little or show mostly moving subjects (people, animals). "
                   "Film slow orbits around static structures.")  # fmt: skip
    return out


def solve(
    zone_dir: Path, camera: str, matcher: str, overlap: int, max_size: int, undistort: bool, reuse_db: bool = False
) -> dict:
    t0 = time.time()
    frames = zone_dir / "frames"
    names = sorted(p.name for p in frames.glob("*.jpg"))
    if not names:
        raise SystemExit(f"no frames in {frames}; run extract-frames first")
    masks = zone_dir / "masks" if (zone_dir / "masks").is_dir() else None
    if masks is not None:
        # COLMAP silently skips images that have no mask file: keep-all masks.
        for n in names:
            if not (masks / f"{n}.png").exists():
                img = cv2.imread(str(frames / n), cv2.IMREAD_GRAYSCALE)
                cv2.imwrite(str(masks / f"{n}.png"), np.full(img.shape, 255, np.uint8))
    out = zone_dir / "colmap"
    db = out / "database.db"
    tmp = out / "_sparse"
    if reuse_db and db.is_file():
        # Features and matches are the slow part on CPU; keep them.
        for stale in ("sparse", "undistorted"):
            shutil.rmtree(out / stale, ignore_errors=True)
    else:
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        print(f"[{zone_dir.name}] {len(names)} frames: extracting SIFT features (CPU)...", flush=True)
        extract(db, frames, masks, names, camera, max_size)
        print(f"[{zone_dir.name}] matching ({matcher})...", flush=True)
        match(db, matcher, overlap)

    if reuse_db and tmp.is_dir() and any(tmp.iterdir()):
        print(f"[{zone_dir.name}] loading models from the previous mapping run...", flush=True)
        recs = {i: pycolmap.Reconstruction(d) for i, d in enumerate(sorted(tmp.iterdir()))}
    else:
        print(f"[{zone_dir.name}] mapping...", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        recs = map_scene(db, frames, tmp)

    ordered = sorted(recs.values(), key=lambda r: r.num_reg_images(), reverse=True)
    for i, rec in enumerate(ordered):
        (out / "sparse" / str(i)).mkdir(parents=True)
        rec.write(out / "sparse" / str(i))
    shutil.rmtree(tmp, ignore_errors=True)

    kps, pairs = _db_stats(db)
    best = ordered[0] if ordered else None
    registered = {img.name for img in best.images.values()} if best else set()
    rate = len(registered) / len(names)
    models = [
        {"images": r.num_reg_images(), "points": r.num_points3D(), "mean_reproj_error_px": round(r.compute_mean_reprojection_error(), 3),
         "mean_track_length": round(r.compute_mean_track_length(), 2)}
        for r in ordered
    ]  # fmt: skip
    report = {
        "zone": zone_dir.name,
        "frames": len(names),
        "registered": len(registered),
        "registration_rate": round(rate, 3),
        "target_rate": TARGET_REGISTRATION,
        "models": models,
        "per_video": {
            v: f"{sum(n in registered for n in names if _video_of(n) == v)}/{sum(_video_of(n) == v for n in names)}"
            for v in sorted({_video_of(n) for n in names})
        },
        "median_features": int(np.median(list(kps.values()))) if kps else 0,
        "verified_pairs": len(pairs),
        "settings": {"camera": camera, "matcher": matcher, "overlap": overlap, "max_image_size": max_size, "masks": masks is not None},
        "diagnosis": [] if rate >= TARGET_REGISTRATION else diagnose(names, registered, kps, pairs, len(ordered)),
    }

    if best is not None:
        best.export_PLY(out / "points.ply")
        topdown(best, out / "topdown.jpg")
        if undistort:
            print(f"[{zone_dir.name}] undistorting for training...", flush=True)
            pycolmap.undistort_images(out / "undistorted", out / "sparse" / "0", frames)
    report["seconds"] = round(time.time() - t0, 1)
    (out / "poses_report.json").write_text(json.dumps(report, indent=2))
    return report


def print_report(r: dict) -> None:
    print()
    print(f"Zone {r['zone']}: registered {r['registered']}/{r['frames']} frames "
          f"({r['registration_rate']:.0%}, target {r['target_rate']:.0%}) in {r['seconds']}s")  # fmt: skip
    for i, m in enumerate(r["models"]):
        print(f"  model {i}: {m['images']} images, {m['points']} points, "
              f"reproj {m['mean_reproj_error_px']} px, track {m['mean_track_length']}")  # fmt: skip
    print(f"  per clip: {r['per_video']}")
    for d in r["diagnosis"]:
        print(f"  ! {d}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="solve-poses", description=__doc__.split("\n\n")[0])
    p.add_argument("zone", help="folder name under work/ (zone id or --name from extract-frames)")
    p.add_argument("--camera", choices=["per-video", "single", "per-image"], default="per-video",
                   help="shared intrinsics: per source clip (default), one for all, or per frame")
    p.add_argument("--matcher", choices=["sequential", "exhaustive"], default="sequential",
                   help="sequential suits video; exhaustive is slow but links everything (<200 frames)")
    p.add_argument("--overlap", type=int, default=10)
    p.add_argument("--max-image-size", type=int, default=1600, help="SIFT working resolution (default %(default)s)")
    p.add_argument("--no-undistort", action="store_true")
    p.add_argument("--reuse-db", action="store_true", help="keep existing features/matches (and unsaved models); redo the rest")
    p.add_argument("--work-dir", type=Path, default=WORK_DIR)
    a = p.parse_args(argv)
    r = solve(a.work_dir / a.zone, a.camera, a.matcher, a.overlap, a.max_image_size, not a.no_undistort, a.reuse_db)
    print_report(r)


if __name__ == "__main__":
    main()
