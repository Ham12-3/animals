"""Load zones.json and resolve each zone's source videos."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import INPUT_DIR, ZONES_FILE

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts"}
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Source:
    """A video, or a time range of one: ``tour.mp4#t=95,131`` (media-fragment syntax)."""

    path: Path
    start: float | None = None
    end: float | None = None

    @classmethod
    def parse(cls, spec: str | Path, base: Path | None = None) -> Source:
        file, _, frag = str(spec).partition("#t=")
        path = Path(file) if base is None else base / file
        if not frag:
            return cls(path)
        a, _, b = frag.partition(",")
        return cls(path, float(a) if a else None, float(b) if b else None)

    @property
    def label(self) -> str:
        if self.start is None and self.end is None:
            return self.path.name
        return f"{self.path.name}#t={self.start or 0:g},{'' if self.end is None else f'{self.end:g}'}"


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    videos: tuple[str, ...]

    @property
    def input_dir(self) -> Path:
        return INPUT_DIR / self.id

    def sources(self) -> list[Source]:
        """Videos listed in zones.json, or every video in the folder (by name)."""
        if self.videos:
            sources = [Source.parse(v, self.input_dir) for v in self.videos]
            missing = sorted({s.path.name for s in sources if not s.path.is_file()})
            if missing:
                raise FileNotFoundError(f"{self.id}: listed in zones.json but missing in {self.input_dir}: {missing}")
            return sources
        if not self.input_dir.is_dir():
            return []
        return [Source(p) for p in sorted(self.input_dir.iterdir()) if p.suffix.lower() in VIDEO_EXTS]


def load_zones(path: Path = ZONES_FILE) -> dict[str, Zone]:
    data = json.loads(path.read_text(encoding="utf-8"))
    zones: dict[str, Zone] = {}
    for z in data["zones"]:
        if not _ID_RE.match(z["id"]):
            raise ValueError(f"zone id {z['id']!r} must be kebab-case")
        if z["id"] in zones:
            raise ValueError(f"duplicate zone id {z['id']!r}")
        for axis in ("x", "y"):
            if not 0 <= z["map"][axis] <= 1:
                raise ValueError(f"{z['id']}: map.{axis} must be within 0..1")
        zones[z["id"]] = Zone(id=z["id"], name=z["name"], videos=tuple(z.get("videos", [])))
    return zones
