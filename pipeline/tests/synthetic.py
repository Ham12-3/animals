"""Synthetic walkthrough video with known defects, for testing frame selection.

A camera pans across a procedural texture. Segments (seconds):

    0-8    clean pan
    8-10   out of focus (gaussian blur)
    10-14  burnt-in caption
    14-18  camera stopped (duplicates)
    18-20  horizontal motion blur
    20-30  clean pan

A small watermark sits in the top-right corner for the whole video.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

W, H, FPS, DURATION = 1280, 720, 30, 30
SEGMENTS = {
    "clean": [(0, 8), (20, 30)],
    "blur": [(8, 10)],
    "caption": [(10, 14)],
    "still": [(14, 18)],
    "motion_blur": [(18, 20)],
}


def segment_at(t: float) -> str:
    for name, spans in SEGMENTS.items():
        if any(a <= t < b for a, b in spans):
            return name
    return "clean"


def _texture(w: int, h: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    # Roughly 1/f spectrum like real photos, down to per-pixel detail.
    for cell, amp in ((256, 0.5), (64, 0.3), (16, 0.2), (4, 0.15), (2, 0.12), (1, 0.08)):
        noise = rng.random((h // cell + 2, w // cell + 2, 3)).astype(np.float32)
        img += amp * cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)[:h, :w]
    for _ in range(w // 40):  # blobs give the pan distinct landmarks
        c = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        axes = (int(rng.integers(10, 90)), int(rng.integers(10, 90)))
        cv2.ellipse(img, c, axes, float(rng.integers(0, 180)), 0, 360, rng.random(3).tolist(), -1)
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    return np.clip(img / img.max() * 255, 0, 255).astype(np.uint8)


def _outlined_text(img: np.ndarray, text: str, org: tuple[int, int], scale: float) -> None:
    font = cv2.FONT_HERSHEY_DUPLEX
    cv2.putText(img, text, org, font, scale, (0, 0, 0), max(4, int(scale * 6)), cv2.LINE_AA)
    cv2.putText(img, text, org, font, scale, (255, 255, 255), max(2, int(scale * 2)), cv2.LINE_AA)


def make_video(path: Path, seed: int = 7, watermark: bool = True) -> Path:
    speed = 200  # px/s
    canvas = _texture(W + speed * DURATION + 64, H, seed)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    x = 0.0
    motion_kernel = np.zeros((1, 31), np.float32)
    motion_kernel[:] = 1 / 31
    for n in range(FPS * DURATION):
        t = n / FPS
        seg = segment_at(t)
        if seg != "still":
            x += speed / FPS
        frame = canvas[:, int(x) : int(x) + W].copy()
        if seg == "blur":
            frame = cv2.GaussianBlur(frame, (0, 0), 6)
        elif seg == "motion_blur":
            frame = cv2.filter2D(frame, -1, motion_kernel)
        if seg == "caption":
            _outlined_text(frame, "VANTARA WILDLIFE TOUR - EPISODE 3", (190, 650), 1.5)
        if watermark:
            _outlined_text(frame, "@wildcam", (1080, 50), 0.9)
        writer.write(frame)
    writer.release()
    return path
