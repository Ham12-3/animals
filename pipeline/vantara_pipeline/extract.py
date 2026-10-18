"""Phase 2: turn a zone's walkthrough videos into a clean set of training frames.

    uv run extract-frames elephant-care-centre
    uv run extract-frames --all

For each video: FFmpeg samples frames at 2-3 fps, then frames are dropped for
blur, motion blur, burnt-in text overlays and near-duplicates, and the rest is
trimmed to the per-zone budget (150-400). Output goes to pipeline/work/<zone>/:

    frames/               kept frames, named so sort order = walking order
    masks/                COLMAP masks, only if a fixed overlay/logo was found
    rejected/<reason>/    thumbnails of every dropped frame, for review
    contact_sheet.jpg     all kept frames at a glance
    frames.csv            per-frame scores and decisions
    extract_report.json   summary, thresholds and warnings
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import WORK_DIR
from . import ffmpeg
from .quality import (
    ANALYSIS_SIZE,
    gradient_coherence,
    hamming,
    overlay_boxes,
    paint_boxes,
    phash,
    sharpness,
    text_candidates,
    to_analysis_gray,
)
from .zones import Source, load_zones

MOTION_SIZE = 640  # resolution for frame-to-frame comparisons
THUMB_SIZE = 480
REASONS = ("blur", "motion_blur", "text_overlay", "duplicate", "over_budget")


@dataclass
class Config:
    fps: float | None = None  # None: pick 2-3 fps from total footage length
    max_size: int = 2560  # long side of extracted frames; 0 keeps source size
    min_frames: int = 150
    max_frames: int = 400
    blur_floor: float = 20.0  # absolute Laplacian-variance floor
    blur_rel: float = 0.35  # ...and fraction of the video's median sharpness
    local_blur_ratio: float = 0.5  # vs. median of neighbouring frames (shake)
    local_window: int = 3
    motion_coherence: float = 0.2  # gradient coherence that marks directional blur...
    motion_coherence_rel: float = 0.15  # ...and how far above the video's median it must be
    dup_hamming: int = 5  # pHash distance to the previous kept frame
    global_dup_hamming: int = 2  # pHash distance to any kept frame
    text_max_area: float = 0.01  # max share of the frame covered by overlay text
    persistent_ratio: float = 0.5  # overlay in >= this share of a video's frames = fixed logo
    detect_text: bool = True
    audit: bool = True
    keep_raw: bool = False


@dataclass
class Frame:
    video: int
    index: int  # 1-based, as written by ffmpeg
    time: float
    raw: Path
    sharpness: float = 0.0
    coherence: float = 0.0
    phash: int = 0
    overlay_area: float = 0.0
    reason: str | None = None

    @property
    def name(self) -> str:
        return f"v{self.video + 1:02d}_{self.index:06d}.jpg"


@dataclass
class VideoResult:
    file: str
    resolution: str
    duration_s: float
    source_fps: float
    hdr_tonemapped: bool
    extracted: int = 0
    kept: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    fixed_overlay_masked: bool = False


def auto_fps(total_duration: float) -> float:
    """Aim for ~900 raw frames so filtering still leaves 150-400, within 2-3 fps."""
    if total_duration <= 0:
        return 3.0
    return round(min(3.0, max(2.0, 900 / total_duration)), 2)


def _imread_flag(long_side: int) -> int:
    # Let libjpeg decode at reduced size: much faster than full decode + resize.
    if long_side >= 4 * ANALYSIS_SIZE:
        return cv2.IMREAD_REDUCED_GRAYSCALE_4
    if long_side >= 2 * ANALYSIS_SIZE:
        return cv2.IMREAD_REDUCED_GRAYSCALE_2
    return cv2.IMREAD_GRAYSCALE


def analyse_video(frames: list[Frame], long_side: int, cfg: Config) -> np.ndarray | None:
    """Fill in per-frame scores. Returns a fixed-overlay mask (MOTION_SIZE) if any."""
    flag = _imread_flag(long_side)

    def score(f: Frame):
        gray = cv2.imread(str(f.raw), flag)
        if gray is None:
            raise RuntimeError(f"could not read {f.raw}")
        g = to_analysis_gray(gray)
        f.sharpness, f.coherence, f.phash = sharpness(g), gradient_coherence(g), phash(g)
        boxes = text_candidates(g) if cfg.detect_text else []
        return boxes, to_analysis_gray(g, MOTION_SIZE)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        scored = list(pool.map(score, frames))
    if not cfg.detect_text or not frames:
        return None

    small = [m for _, m in scored]
    shape = small[0].shape
    per_frame: list[np.ndarray] = []
    counts = np.zeros(shape, np.int32)
    for i, (boxes, cur) in enumerate(scored):
        nbs = [small[j] for j in (i - 1, i + 1) if 0 <= j < len(small)]
        mask = paint_boxes(overlay_boxes(boxes, cur, nbs), shape)
        per_frame.append(mask)
        counts += mask

    need = max(3, math.ceil(cfg.persistent_ratio * len(frames)))
    fixed = counts >= need
    if fixed.any():
        fixed = cv2.dilate(fixed.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    for f, mask in zip(frames, per_frame):
        # Fixed logos are masked out for COLMAP instead of costing us frames.
        f.overlay_area = float((mask.astype(bool) & ~fixed).mean())
    return fixed if fixed.any() else None


def classify_quality(frames: list[Frame], cfg: Config) -> None:
    """Blur, motion blur and text overlays, judged against the video's own baseline."""
    if not frames:
        return
    s = np.array([f.sharpness for f in frames])
    coh = np.array([f.coherence for f in frames])
    med_s, med_coh = float(np.median(s)), float(np.median(coh))
    soft_below = max(cfg.blur_floor, cfg.blur_rel * med_s)
    directional_above = max(cfg.motion_coherence, med_coh + cfg.motion_coherence_rel)
    w = cfg.local_window
    for i, f in enumerate(frames):
        local = float(np.median(s[max(0, i - w) : i + w + 1]))
        soft = f.sharpness < soft_below or f.sharpness < cfg.local_blur_ratio * local
        directional = f.coherence > directional_above
        if soft:
            f.reason = "motion_blur" if directional else "blur"
        elif directional and f.sharpness < 0.7 * med_s:
            # Smeared in one direction but not soft enough above; a fence or
            # railing is also directional, so only when clearly below par.
            f.reason = "motion_blur"
        elif f.overlay_area > cfg.text_max_area:
            f.reason = "text_overlay"


def drop_sequential_duplicates(frames: list[Frame], cfg: Config) -> None:
    """Group consecutive look-alike frames (camera paused) and keep the sharpest.

    Each frame is compared with the group's first frame, not the latest one, so
    a slow but steady walk is not collapsed into a single frame.
    """
    anchor: Frame | None = None
    best: Frame | None = None
    for f in (f for f in frames if f.reason is None):
        if anchor is not None and hamming(f.phash, anchor.phash) <= cfg.dup_hamming:
            if f.sharpness > best.sharpness:
                best.reason, best = "duplicate", f
            else:
                f.reason = "duplicate"
        else:
            anchor = best = f


def drop_global_duplicates(frames: list[Frame], cfg: Config) -> None:
    """Near-identical frames anywhere in the zone (e.g. the same clip twice)."""
    kept: list[int] = []
    for f in (f for f in frames if f.reason is None):
        if kept:
            d = np.bitwise_count(np.array(kept, dtype=np.uint64) ^ np.uint64(f.phash))
            if int(d.min()) <= cfg.global_dup_hamming:
                f.reason = "duplicate"
                continue
        kept.append(f.phash)


def enforce_budget(frames: list[Frame], cfg: Config) -> None:
    """Over budget: split the walk into equal stretches, keep the sharpest of each."""
    kept = [f for f in frames if f.reason is None]
    if len(kept) <= cfg.max_frames:
        return
    for chunk in np.array_split(np.arange(len(kept)), cfg.max_frames):
        group = [kept[i] for i in chunk]
        best = max(group, key=lambda f: f.sharpness)
        for f in group:
            if f is not best:
                f.reason = "over_budget"


def _thumb(src: Path, dest: Path) -> None:
    img = cv2.imread(str(src), cv2.IMREAD_REDUCED_COLOR_4)
    h, w = img.shape[:2]
    scale = THUMB_SIZE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), img, [cv2.IMWRITE_JPEG_QUALITY, 80])


def contact_sheet(paths: list[Path], dest: Path, cols: int = 16, cell_w: int = 256) -> None:
    if not paths:
        return
    first = cv2.imread(str(paths[0]), cv2.IMREAD_REDUCED_COLOR_8)
    cell_h = round(cell_w * first.shape[0] / first.shape[1])
    rows = math.ceil(len(paths) / cols)
    sheet = np.full((rows * cell_h, cols * cell_w, 3), 24, np.uint8)

    def load(p: Path) -> np.ndarray:
        return cv2.resize(cv2.imread(str(p), cv2.IMREAD_REDUCED_COLOR_4), (cell_w, cell_h), interpolation=cv2.INTER_AREA)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        for i, img in enumerate(pool.map(load, paths)):
            r, c = divmod(i, cols)
            sheet[r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w] = img
    cv2.imwrite(str(dest), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])


def _warnings(results: list[VideoResult], kept: int, fps: float, cfg: Config, rejected: Counter) -> list[str]:
    out = []
    for r in results:
        if max(map(int, r.resolution.split("x"))) < 1280:
            out.append(f"{r.file}: only {r.resolution}. Splats need 1920x1080 or better; 4K is ideal.")
        if r.fixed_overlay_masked:
            out.append(f"{r.file}: fixed logo/watermark/timestamp found; masked in masks/ so COLMAP ignores it.")
    if kept < cfg.min_frames:
        msg = f"Only {kept} frames kept (target {cfg.min_frames}-{cfg.max_frames})."
        top = rejected.most_common(1)
        reason = top[0][0] if top and top[0][1] > 0.25 * (kept + rejected.total()) else None
        hint = {
            "blur": "Most loss is blur: shoot in daylight, move slower, lock focus/exposure, avoid digital zoom.",
            "motion_blur": "Most loss is motion blur: walk slower, pan slower, use stabilisation or a gimbal, faster shutter.",
            "duplicate": "Most loss is duplicates: the camera stood still a lot. Keep walking; aim for steady forward/orbit movement.",
            "text_overlay": "Most loss is burnt-in text: use original clean footage without captions or titles.",
        }.get(reason, "Not enough footage: aim for 3-6 minutes of slow, steady walking per zone, ideally a loop.")
        if fps < 3:
            hint += " Re-running with --fps 3 also helps a little."
        out.append(f"{msg} {hint}")
    return out


def _span(src: Source, info: ffmpeg.VideoInfo) -> float:
    end = info.duration if src.end is None else min(src.end, info.duration or src.end)
    return max(0.0, end - (src.start or 0.0))


def run_extraction(zone_id: str, videos: list[Source | Path], out_dir: Path, cfg: Config) -> dict:
    if not videos:
        raise SystemExit(f"{zone_id}: no videos found. Put footage in pipeline/input/{zone_id}/")
    t0 = time.time()
    sources = [v if isinstance(v, Source) else Source(v) for v in videos]
    probed: dict[Path, ffmpeg.VideoInfo] = {}
    for src in sources:  # several shots of one long video share a probe
        if src.path not in probed:
            probed[src.path] = ffmpeg.probe(src.path)
    infos = [probed[src.path] for src in sources]
    spans = [_span(s, i) for s, i in zip(sources, infos)]
    fps = cfg.fps or auto_fps(sum(spans))
    if not 2 <= fps <= 3:
        print(f"note: {fps} fps is outside the recommended 2-3 fps range", file=sys.stderr)

    for sub in ("frames", "masks", "rejected", "_raw"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
    (out_dir / "frames").mkdir(parents=True)

    all_frames: list[Frame] = []
    results: list[VideoResult] = []
    fixed_masks: dict[int, np.ndarray] = {}
    for vi, (src, info) in enumerate(zip(sources, infos)):
        print(f"[{zone_id}] v{vi + 1:02d} {src.label}: {info.width}x{info.height}, "
              f"{spans[vi]:.0f}s{', HDR -> SDR' if info.is_hdr else ''} -> extracting at {fps} fps")  # fmt: skip
        raw = ffmpeg.extract_frames(info, out_dir / "_raw" / f"v{vi + 1:02d}", fps, cfg.max_size, src.start, src.end)
        t0_src = src.start or 0.0
        frames = [Frame(video=vi, index=i + 1, time=round(t0_src + i / fps, 2), raw=p) for i, p in enumerate(raw)]
        long_side = max(info.width, info.height)
        if cfg.max_size:
            long_side = min(long_side, cfg.max_size)
        mask = analyse_video(frames, long_side, cfg)
        if mask is not None:
            fixed_masks[vi] = mask
        classify_quality(frames, cfg)
        drop_sequential_duplicates(frames, cfg)
        all_frames += frames
        results.append(VideoResult(
            file=src.label, resolution=f"{info.width}x{info.height}", duration_s=round(spans[vi], 1),
            source_fps=round(info.fps, 2), hdr_tonemapped=info.is_hdr, extracted=len(frames),
            fixed_overlay_masked=mask is not None,
        ))  # fmt: skip

    drop_global_duplicates(all_frames, cfg)
    enforce_budget(all_frames, cfg)

    kept = [f for f in all_frames if f.reason is None]
    jobs = []
    for f in all_frames:
        if f.reason is None:
            dest = out_dir / "frames" / f.name
            if cfg.keep_raw:
                shutil.copy2(f.raw, dest)
            else:
                os.replace(f.raw, dest)
        elif cfg.audit:
            jobs.append((f.raw, out_dir / "rejected" / f.reason / f.name))
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        list(pool.map(lambda j: _thumb(*j), jobs))

    if fixed_masks:
        # COLMAP convention: masks/<image name>.png, black = ignore. Once a
        # mask folder is in use COLMAP skips any image without a mask, so
        # frames from clips with no overlay get an all-white one.
        (out_dir / "masks").mkdir()
        sizes: dict[int, tuple[int, int]] = {}
        for f in kept:
            if f.video not in sizes:
                h, w = cv2.imread(str(out_dir / "frames" / f.name)).shape[:2]
                sizes[f.video] = (w, h)
            if f.video in fixed_masks:
                m = cv2.resize(fixed_masks[f.video].astype(np.uint8), sizes[f.video], interpolation=cv2.INTER_NEAREST)
                out = np.where(m > 0, 0, 255).astype(np.uint8)
            else:
                out = np.full(sizes[f.video][::-1], 255, np.uint8)
            cv2.imwrite(str(out_dir / "masks" / f"{f.name}.png"), out)

    if not cfg.keep_raw:
        shutil.rmtree(out_dir / "_raw", ignore_errors=True)

    contact_sheet([out_dir / "frames" / f.name for f in kept], out_dir / "contact_sheet.jpg")

    with open(out_dir / "frames.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "video", "time_s", "sharpness", "coherence", "overlay_area", "decision"])
        for f in all_frames:
            w.writerow([f.name, results[f.video].file, f.time, round(f.sharpness, 1), round(f.coherence, 3),
                        round(f.overlay_area, 4), f.reason or "kept"])  # fmt: skip

    rejected = Counter(f.reason for f in all_frames if f.reason)
    for r_i, r in enumerate(results):
        vf = [f for f in all_frames if f.video == r_i]
        r.kept = sum(f.reason is None for f in vf)
        r.rejected = {k: v for k in REASONS if (v := sum(f.reason == k for f in vf))}

    report = {
        "zone": zone_id,
        "fps": fps,
        "extracted": len(all_frames),
        "kept": len(kept),
        "target": [cfg.min_frames, cfg.max_frames],
        "rejected": {k: rejected[k] for k in REASONS if rejected[k]},
        "videos": [asdict(r) for r in results],
        "warnings": _warnings(results, len(kept), fps, cfg, rejected),
        "config": {k: v for k, v in asdict(cfg).items()},
        "seconds": round(time.time() - t0, 1),
    }
    (out_dir / "extract_report.json").write_text(json.dumps(report, indent=2))
    return report


def print_report(report: dict, out_dir: Path) -> None:
    print()
    print(f"Zone {report['zone']}: kept {report['kept']} of {report['extracted']} frames "
          f"(target {report['target'][0]}-{report['target'][1]}, {report['fps']} fps, {report['seconds']}s)")  # fmt: skip
    print(f"  {'video':<32} {'extracted':>9} {'kept':>6}  rejected")
    for v in report["videos"]:
        rej = ", ".join(f"{k} {n}" for k, n in v["rejected"].items()) or "-"
        print(f"  {v['file'][:32]:<32} {v['extracted']:>9} {v['kept']:>6}  {rej}")
    for w in report["warnings"]:
        print(f"  ! {w}")
    print(f"  -> {out_dir}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="extract-frames", description=__doc__.split("\n\n")[0])
    p.add_argument("zones", nargs="*", help="zone ids from zones.json")
    p.add_argument("--all", action="store_true", help="every zone that has footage")
    p.add_argument("--video", action="append", default=[], metavar="FILE[#t=START,END]",
                   help="ad-hoc run on these videos (repeatable) instead of a zone; needs --name")
    p.add_argument("--name", help="output folder name for an ad-hoc --video run")
    p.add_argument("--fps", type=float, help="sampling rate (default: auto, 2-3 fps)")
    p.add_argument("--max-size", type=int, default=Config.max_size, help="long side in px, 0 = source (default %(default)s)")
    p.add_argument("--min-frames", type=int, default=Config.min_frames)
    p.add_argument("--max-frames", type=int, default=Config.max_frames)
    p.add_argument("--blur-rel", type=float, default=Config.blur_rel, help="drop below this x median sharpness (default %(default)s)")
    p.add_argument("--blur-floor", type=float, default=Config.blur_floor)
    p.add_argument("--dup-hamming", type=int, default=Config.dup_hamming, help="pHash distance for duplicates (default %(default)s)")
    p.add_argument("--text-max-area", type=float, default=Config.text_max_area, help="overlay text share of frame (default %(default)s)")
    p.add_argument("--no-text-filter", action="store_true")
    p.add_argument("--no-audit", action="store_true", help="skip rejected/ thumbnails")
    p.add_argument("--keep-raw", action="store_true", help="keep every extracted frame in _raw/")
    p.add_argument("--work-dir", type=Path, default=WORK_DIR)
    a = p.parse_args(argv)

    ffmpeg.require_tools()
    cfg = Config(
        fps=a.fps, max_size=a.max_size, min_frames=a.min_frames, max_frames=a.max_frames,
        blur_rel=a.blur_rel, blur_floor=a.blur_floor, dup_hamming=a.dup_hamming,
        text_max_area=a.text_max_area, detect_text=not a.no_text_filter,
        audit=not a.no_audit, keep_raw=a.keep_raw,
    )  # fmt: skip
    if a.video:
        if not a.name or a.zones or a.all:
            p.error("--video needs --name and no zone ids")
        out_dir = a.work_dir / a.name
        print_report(run_extraction(a.name, [Source.parse(v) for v in a.video], out_dir, cfg), out_dir)
        return

    zones = load_zones()
    if a.all:
        ids = [z.id for z in zones.values() if z.sources()]
    else:
        ids = a.zones
    if not ids:
        p.error("name at least one zone (or --all). Zones: " + ", ".join(zones))
    unknown = [i for i in ids if i not in zones]
    if unknown:
        p.error(f"unknown zone(s) {unknown}. Zones: {', '.join(zones)}")

    for zid in ids:
        out_dir = a.work_dir / zid
        report = run_extraction(zid, zones[zid].sources(), out_dir, cfg)
        print_report(report, out_dir)


if __name__ == "__main__":
    main()
