"""Thin wrappers around ffprobe / ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ and HLG (e.g. iPhone Dolby Vision / HDR)


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    duration: float
    fps: float
    codec: str
    transfer: str
    primaries: str = ""
    matrix: str = ""

    @property
    def is_hdr(self) -> bool:
        return self.transfer in HDR_TRANSFERS


def require_tools() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)} on PATH. Install FFmpeg: https://ffmpeg.org/download.html")


def probe(path: Path) -> VideoInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    data = json.loads(out)
    if not data.get("streams"):
        raise ValueError(f"{path.name}: no video stream")
    s = data["streams"][0]
    num, _, den = s.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    width, height = int(s["width"]), int(s["height"])
    # Phone footage is often stored landscape with a rotation flag; ffmpeg
    # applies it on decode, so report the displayed orientation.
    rotation = 0
    for sd in s.get("side_data_list", []):
        rotation = int(sd.get("rotation", rotation))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    duration = float(s.get("duration") or data.get("format", {}).get("duration") or 0)
    return VideoInfo(
        path, width, height, duration, fps, s.get("codec_name", "?"),
        s.get("color_transfer", ""), s.get("color_primaries", ""), s.get("color_space", ""),
    )  # fmt: skip


def extract_frames(
    info: VideoInfo, out_dir: Path, fps: float, max_size: int, start: float | None = None, end: float | None = None
) -> list[Path]:
    """Decode ``info.path`` (optionally only start..end seconds) at ``fps`` into JPEGs ``000001.jpg``..."""
    out_dir.mkdir(parents=True, exist_ok=True)
    filters = [f"fps={fps}"]
    if info.is_hdr:
        # Tone-map HDR to SDR, otherwise frames come out grey and washed out.
        # Spell out the input colour space: phones don't always tag all of it.
        pin = info.primaries if info.primaries.startswith("bt2020") else "bt2020"
        min_ = info.matrix if info.matrix.startswith("bt2020") else "bt2020nc"
        filters += [
            f"zscale=tin={info.transfer}:pin={pin}:min={min_}:t=linear:npl=100",
            "format=gbrpf32le",
            "zscale=p=bt709",
            "tonemap=tonemap=hable:desat=0",
            "zscale=t=bt709:m=bt709:r=tv",
            "format=yuv420p",
        ]
    if max_size:
        filters.append(
            f"scale=w='min(iw,{max_size})':h='min(ih,{max_size})'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"
        )
    seek = []
    if start:
        seek += ["-ss", f"{start:.3f}"]
    if end is not None:
        seek += ["-t", f"{end - (start or 0):.3f}"]
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        *seek, "-i", str(info.path),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", ",".join(filters),
        "-q:v", "2",
        str(out_dir / "%06d.jpg"),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return sorted(out_dir.glob("*.jpg"))
