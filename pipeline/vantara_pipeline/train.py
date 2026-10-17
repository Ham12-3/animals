"""Phase 4: train a Gaussian splat from a solved zone with Brush (no CUDA needed).

    uv run train-splat <zone-or-name>                 # 30k steps, exports PLY
    uv run train-splat <zone-or-name> --prepare-only  # just build the dataset
    uv run train-splat <zone-or-name> --zip           # dataset zip for Colab

Brush (https://github.com/ArthurBrussee/brush) trains on any GPU via WebGPU
(DX12/Vulkan/Metal). Point BRUSH_BIN at the executable, or unpack the Windows
release into pipeline/tools/brush/.

Writes work/<zone>/splat/:

    dataset/          images/, masks/, sparse/0/ (pinhole, undistorted)
    exports/          Brush checkpoints, <step>.ply
    <zone>.ply        final splat
    train.log         Brush output
    train_report.json steps, time, splat count, size
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pycolmap

from . import PIPELINE_DIR, WORK_DIR

TOOLS_DIR = PIPELINE_DIR / "tools"


def find_brush() -> Path:
    if env := os.environ.get("BRUSH_BIN"):
        return Path(env)
    hits = sorted(TOOLS_DIR.glob("brush*/**/brush*.exe")) + sorted(TOOLS_DIR.glob("brush*/**/brush_app"))
    if not hits:
        raise SystemExit(
            "Brush not found. Download brush-app-x86_64-pc-windows-msvc.zip from "
            "https://github.com/ArthurBrussee/brush/releases, unzip it into pipeline/tools/brush/, "
            "or set BRUSH_BIN."
        )
    return hits[0]


def _undistort_mask(mask: np.ndarray, src: pycolmap.Camera, dst: pycolmap.Camera) -> np.ndarray:
    """Warp a mask from the distorted source camera into the undistorted one."""
    u, v = np.meshgrid(np.arange(dst.width, dtype=np.float64), np.arange(dst.height, dtype=np.float64))
    norm = dst.cam_from_img(np.stack([u.ravel(), v.ravel()], 1))
    xy = src.img_from_cam(np.c_[norm, np.ones(len(norm))], check_cheirality=False)
    maps = xy.reshape(dst.height, dst.width, 2).astype(np.float32)
    return cv2.remap(mask, maps[..., 0], maps[..., 1], cv2.INTER_NEAREST, borderValue=0)


def prepare(zone_dir: Path) -> Path:
    """Lay out the undistorted COLMAP model the way Brush and gsplat expect."""
    colmap = zone_dir / "colmap"
    und = colmap / "undistorted"
    if not (und / "sparse" / "cameras.bin").is_file():
        raise SystemExit(f"no undistorted model in {und}; run solve-poses first")
    ds = zone_dir / "splat" / "dataset"
    shutil.rmtree(ds, ignore_errors=True)
    (ds / "sparse" / "0").mkdir(parents=True)
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.copy2(und / "sparse" / f, ds / "sparse" / "0" / f)
    shutil.copytree(und / "images", ds / "images")

    masks = zone_dir / "masks"
    if masks.is_dir():
        # COLMAP masks are named <image>.png and match the distorted frames;
        # Brush wants masks/<image stem>.png matching the undistorted ones.
        src_rec = pycolmap.Reconstruction(colmap / "sparse" / "0")
        dst_rec = pycolmap.Reconstruction(und / "sparse")
        src_by_name = {img.name: src_rec.cameras[img.camera_id] for img in src_rec.images.values()}
        (ds / "masks").mkdir()
        any_masked = False
        for img in dst_rec.images.values():
            m = cv2.imread(str(masks / f"{img.name}.png"), cv2.IMREAD_GRAYSCALE)
            if m is None or m.min() == 255:
                continue  # nothing to ignore in this frame
            any_masked = True
            warped = _undistort_mask(m, src_by_name[img.name], dst_rec.cameras[img.camera_id])
            cv2.imwrite(str(ds / "masks" / f"{Path(img.name).stem}.png"), warped)
        if not any_masked:
            (ds / "masks").rmdir()
    return ds


def zip_dataset(ds: Path) -> Path:
    out = ds.parent / f"{ds.parent.parent.name}-dataset.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:  # JPEGs don't compress further
        for p in sorted(ds.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(ds))
    return out


def ply_splat_count(path: Path) -> int:
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("ascii", "replace").strip()
            if line.startswith("element vertex"):
                return int(line.split()[-1])
            if line == "end_header":
                break
    return 0


def _checkpoints(exports: Path) -> list[Path]:
    return sorted((p for p in exports.glob("*.ply") if p.stem.isdigit()), key=lambda p: int(p.stem))


def train(
    zone_dir: Path, ds: Path, steps: int, max_res: int, export_every: int, eval_every: int,
    extra: list[str], resume: bool = False, viewer: bool = False, max_attempts: int = 100,
) -> dict:  # fmt: skip
    """Run Brush; after a crash, resume from the latest checkpoint.

    Brush 0.3.0 can panic in its console progress bar (indicatif ETA turning
    NaN), which kills training at a random step. A single ``init.ply`` in the
    dataset folder plus ``--start-iter`` lets it pick up where it stopped
    (optimizer moments restart, which costs little). Old checkpoints are pruned
    to the newest two.

    On slow GPUs that panic comes every few minutes (the bar's speed estimate
    decays to zero between steps). ``viewer=True`` trains in Brush's GUI window
    instead, which has no such progress bar.
    """
    brush = find_brush()
    out = zone_dir / "splat"
    exports = out / "exports"
    if not resume:
        shutil.rmtree(exports, ignore_errors=True)
    exports.mkdir(parents=True, exist_ok=True)
    base = [
        str(brush), str(ds),
        "--total-steps", str(steps),
        "--max-resolution", str(max_res),
        "--export-every", str(export_every),
        "--export-path", str(exports),
        "--export-name", "{iter}.ply",
        "--eval-split-every", "10",
        "--eval-every", str(eval_every),
        *extra,
    ]  # fmt: skip
    t0 = time.time()
    attempts, crashes, stalls = 0, [], 0
    log_path = out / "train.log"

    def latest_step() -> int:
        done = _checkpoints(exports)
        return int(done[-1].stem) if done else 0  # Brush zero-pads: "02500.ply"

    while (start := latest_step()) < steps:
        init = ds / "init.ply"
        init.unlink(missing_ok=True)
        cmd = list(base)
        if start:
            shutil.copy2(_checkpoints(exports)[-1], init)
            cmd += ["--start-iter", str(start)]
        if viewer:
            cmd.append("--with-viewer")
        attempts += 1
        print(f"[{zone_dir.name}] Brush attempt {attempts}, from step {start}", flush=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as log:
            log.write(f"\n===== attempt {attempts}, start step {start}: {' '.join(cmd)} =====\n")
            log.flush()
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            if viewer:
                # The viewer stays open after training: close it once the
                # final checkpoint exists and has finished writing.
                last_size = -1
                while proc.poll() is None:
                    time.sleep(15)
                    done = _checkpoints(exports)
                    if done and int(done[-1].stem) >= steps:
                        size = done[-1].stat().st_size
                        if size == last_size:
                            proc.terminate()
                            proc.wait()
                            proc.returncode = 0
                            break
                        last_size = size
            proc.wait()
        init.unlink(missing_ok=True)
        if proc.returncode != 0:
            crashes.append({"attempt": attempts, "from_step": start, "exit": proc.returncode})
        # Keep going while checkpoints advance; give up after repeated runs that don't.
        stalls = 0 if latest_step() > start else stalls + 1
        if stalls >= 3 or attempts >= max_attempts:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise SystemExit(f"Brush stopped at step {latest_step()} after {attempts} attempts "
                             f"(last exit {proc.returncode}). Log tail:\n{tail}")  # fmt: skip
        # Checkpoints grow to hundreds of MB: keep the newest two.
        for old in _checkpoints(exports)[:-2]:
            old.unlink()
    seconds = time.time() - t0

    plys = _checkpoints(exports)
    final = out / f"{zone_dir.name}.ply"
    shutil.copy2(plys[-1], final)
    report = {
        "zone": zone_dir.name,
        "trainer": f"brush ({brush.name})",
        "steps": int(plys[-1].stem),
        "target_steps": steps,
        "max_resolution": max_res,
        "training_images": len(list((ds / "images").iterdir())),
        "masked_images": len(list((ds / "masks").iterdir())) if (ds / "masks").is_dir() else 0,
        "splats": ply_splat_count(final),
        "ply_mb": round(final.stat().st_size / 1e6, 1),
        "minutes_this_run": round(seconds / 60, 1),
        "attempts": attempts,
        "crashes": crashes,
        "checkpoints": [p.name for p in plys],
    }
    (out / "train_report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="train-splat", description=__doc__.split("\n\n")[0])
    p.add_argument("zone", help="folder name under work/")
    p.add_argument("--steps", type=int, default=30000)
    p.add_argument("--max-resolution", type=int, default=1600, help="training image long side (default %(default)s)")
    p.add_argument("--export-every", type=int, default=1000, help="checkpoint interval; also the most a crash can lose")
    p.add_argument("--eval-every", type=int, default=5000)
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--resume", action="store_true", help="continue from the latest checkpoint in exports/")
    p.add_argument("--viewer", action="store_true",
                   help="train in Brush's window (avoids its console progress-bar crash on slow GPUs)")
    p.add_argument("--zip", action="store_true", help="also write a dataset zip to upload to the Colab notebook")
    p.add_argument("--work-dir", type=Path, default=WORK_DIR)
    a, extra = p.parse_known_args(argv)  # anything else goes straight to Brush
    zone_dir = a.work_dir / a.zone
    ds = prepare(zone_dir)
    n_masks = len(list((ds / "masks").iterdir())) if (ds / "masks").is_dir() else 0
    print(f"[{a.zone}] dataset: {len(list((ds / 'images').iterdir()))} images, {n_masks} masks -> {ds}")
    if a.zip:
        print(f"[{a.zone}] zip for Colab: {zip_dataset(ds)}")
    if a.prepare_only:
        return
    r = train(zone_dir, ds, a.steps, a.max_resolution, a.export_every, a.eval_every, extra, a.resume, a.viewer)
    print(f"\nZone {r['zone']}: {r['splats']:,} splats after {r['steps']} steps "
          f"({r['minutes_this_run']} min, {r['attempts']} attempt(s)), "
          f"{r['ply_mb']} MB -> {zone_dir / 'splat' / (r['zone'] + '.ply')}")  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
