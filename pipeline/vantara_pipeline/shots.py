"""Split an edited video (vlog, documentary) into shots, to find usable footage.

    uv run find-shots path/to/video.webm

Edited footage cuts between places, talking heads and B-roll every few
seconds. Splats need long, continuous camera moves through one place, so this
finds the cuts and scores each shot. Writes next to the video:

    <video>.shots.json   every shot: start/end, camera motion, sharpness
    <video>.shots.jpg    one numbered thumbnail per candidate shot

Pick shots that show the same place and feed them to extract-frames as
``video.webm#t=START,END``.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from . import ffmpeg

SAMPLE_FPS = 6
W, H = 320, 180


@dataclass
class Shot:
    index: int
    start: float
    end: float
    motion: float  # median frame-to-frame change: ~0 tripod/talking head, high = moving camera
    sharpness: float
    candidate: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


def _frames(path: Path):
    """Yield (time, gray 320x180) at SAMPLE_FPS via an ffmpeg pipe."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
        "-map", "0:v:0", "-vf", f"fps={SAMPLE_FPS},scale={W}:{H}:flags=area,format=gray",
        "-f", "rawvideo", "-",
    ]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = 0
    try:
        while buf := proc.stdout.read(W * H):
            if len(buf) < W * H:
                break
            yield n / SAMPLE_FPS, np.frombuffer(buf, np.uint8).reshape(H, W)
            n += 1
    finally:
        proc.stdout.close()
        proc.wait()


def find_shots(path: Path, min_len: float = 4.0, cut_ratio: float = 1.8) -> tuple[list[Shot], dict[int, np.ndarray]]:
    times, diffs, hists, sharp, thumbs = [], [], [], [], []
    prev = None
    for t, g in _frames(path):
        small = cv2.GaussianBlur(g, (5, 5), 0)
        times.append(t)
        diffs.append(0.0 if prev is None else float(np.abs(small.astype(np.int16) - prev).mean()))
        hists.append(cv2.calcHist([g], [0], None, [32], [0, 256]).ravel())
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        thumbs.append(g)
        prev = small.astype(np.int16)
    if not times:
        raise SystemExit(f"{path}: no frames decoded")

    d = np.array(diffs)
    # A cut is an isolated spike: well above the typical change both before and
    # after it, and above both neighbouring frames. A fast pan raises the
    # change gradually, so it doesn't qualify.
    w = 2 * SAMPLE_FPS
    cuts = [0]
    for i in range(1, len(d)):
        before = float(np.median(d[max(1, i - w) : i])) if i > 1 else 0.0
        after = float(np.median(d[i + 1 : i + 1 + w])) if i + 1 < len(d) else 0.0
        neighbours = max(d[i - 1] if i > 1 else 0.0, d[i + 1] if i + 1 < len(d) else 0.0)
        corr = cv2.compareHist(hists[i - 1], hists[i], cv2.HISTCMP_CORREL)
        need = cut_ratio if corr > 0.7 else 0.8 * cut_ratio  # a tone change needs less evidence
        if d[i] > max(12.0, need * max(before, after)) and d[i] > 1.5 * neighbours and i - cuts[-1] >= 2:
            cuts.append(i)
    cuts.append(len(times))

    shots, mids = [], {}
    for k, (a, b) in enumerate(zip(cuts[:-1], cuts[1:])):
        inner = d[a + 1 : b]
        shot = Shot(
            index=k,
            start=round(times[a], 2),
            end=round(times[b - 1] + 1 / SAMPLE_FPS, 2),
            motion=round(float(np.median(inner)) if inner.size else 0.0, 2),
            sharpness=round(float(np.median(sharp[a:b])), 1),
        )
        # Skip the first/last 0.5 s: dissolves and fades live there.
        trim = int(0.5 * SAMPLE_FPS)
        shot.start, shot.end = round(shot.start + trim / SAMPLE_FPS, 2), round(shot.end - trim / SAMPLE_FPS, 2)
        shot.candidate = shot.duration >= min_len and shot.motion >= 2.0
        shots.append(shot)
        mids[k] = thumbs[(a + b) // 2]
    return shots, mids


def shot_sheet(shots: list[Shot], mids: dict[int, np.ndarray], dest: Path, cols: int = 6) -> None:
    picks = [s for s in shots if s.candidate]
    if not picks:
        return
    rows = math.ceil(len(picks) / cols)
    sheet = np.full((rows * (H + 22), cols * W), 20, np.uint8)
    for i, s in enumerate(picks):
        r, c = divmod(i, cols)
        y, x = r * (H + 22), c * W
        sheet[y : y + H, x : x + W] = mids[s.index]
        label = f"#{s.index} {s.start:.0f}-{s.end:.0f}s m{s.motion:.0f}"
        cv2.putText(sheet, label, (x + 4, y + H + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 235, 1, cv2.LINE_AA)
    cv2.imwrite(str(dest), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="find-shots", description=__doc__.split("\n\n")[0])
    p.add_argument("videos", nargs="+", type=Path)
    p.add_argument("--min-len", type=float, default=4.0, help="shortest useful shot in seconds (default %(default)s)")
    a = p.parse_args(argv)
    ffmpeg.require_tools()
    for v in a.videos:
        shots, mids = find_shots(v, a.min_len)
        cand = [s for s in shots if s.candidate]
        v.with_suffix(".shots.json").write_text(json.dumps([asdict(s) | {"duration": round(s.duration, 2)} for s in shots], indent=2))
        shot_sheet(shots, mids, v.with_suffix(".shots.jpg"))
        print(f"{v.name}: {len(shots)} shots, {len(cand)} candidates "
              f"({sum(s.duration for s in cand):.0f}s of moving footage >= {a.min_len:.0f}s)")  # fmt: skip


if __name__ == "__main__":
    main()
