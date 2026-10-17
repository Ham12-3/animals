"""Minimal in-place edits of binary glTF (GLB) vertex data."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_JSON, _BIN = 0x4E4F534A, 0x004E4942
_FLOAT, _VEC3 = 5126, "VEC3"


def _chunks(data: bytes) -> tuple[dict, bytearray]:
    magic, version, _ = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError("not a glTF 2.0 binary")
    off, doc, binary = 12, None, bytearray()
    while off < len(data):
        length, kind = struct.unpack_from("<II", data, off)
        body = data[off + 8 : off + 8 + length]
        if kind == _JSON:
            doc = json.loads(body)
        elif kind == _BIN:
            binary = bytearray(body)
        off += 8 + length
    return doc, binary


def _pack(doc: dict, binary: bytes) -> bytes:
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), _JSON) + js
            + struct.pack("<II", len(binary), _BIN) + binary)  # fmt: skip


def rotate_vertices(path: Path, rot: np.ndarray) -> dict:
    """Apply a rotation to every POSITION and NORMAL attribute, in place.

    Rotations keep triangle winding, so indices need no change. Returns the new
    position bounds.
    """
    doc, binary = _chunks(path.read_bytes())
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    done = set()
    for mesh in doc.get("meshes", []):
        for prim in mesh["primitives"]:
            for attr in ("POSITION", "NORMAL"):
                idx = prim["attributes"].get(attr)
                if idx is None or idx in done:
                    continue
                done.add(idx)
                acc = doc["accessors"][idx]
                if acc["componentType"] != _FLOAT or acc["type"] != _VEC3 or acc.get("sparse"):
                    raise ValueError(f"unsupported {attr} accessor layout")
                view = doc["bufferViews"][acc["bufferView"]]
                start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
                stride = view.get("byteStride") or 12
                n = acc["count"]
                # Writable strided float view straight onto the binary chunk.
                cols = np.ndarray((n, 3), np.float32, buffer=binary, offset=start, strides=(stride, 4))
                v = cols @ rot.T.astype(np.float32)
                cols[...] = v
                if attr == "POSITION":
                    acc["min"], acc["max"] = v.min(0).tolist(), v.max(0).tolist()
                    lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    path.write_bytes(_pack(doc, binary))
    return {"min": lo.tolist(), "max": hi.tolist()}
