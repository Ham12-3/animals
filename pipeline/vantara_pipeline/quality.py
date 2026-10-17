"""Per-frame image quality measures used to pick training frames.

All measures run on a downscaled grayscale copy (``ANALYSIS_SIZE`` on the long
side) so scores are comparable across videos of different resolutions.
"""

from __future__ import annotations

import cv2
import numpy as np

ANALYSIS_SIZE = 960
# Box = (x, y, w, h) normalised to 0..1 of the frame.
Box = tuple[float, float, float, float]


def to_analysis_gray(img: np.ndarray, size: int = ANALYSIS_SIZE) -> np.ndarray:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = size / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return gray


def sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian: low means soft / out of focus / blurred."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def gradient_coherence(gray: np.ndarray) -> float:
    """0 = gradients in every direction, 1 = all gradients share one direction.

    Motion blur smears detail along the motion direction, so only gradients
    perpendicular to it survive and coherence of the whole-frame structure
    tensor rises sharply.
    """
    g = gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    jxx, jyy, jxy = float((gx * gx).mean()), float((gy * gy).mean()), float((gx * gy).mean())
    trace = jxx + jyy
    if trace < 1e-6:
        return 0.0
    diff = np.sqrt((jxx - jyy) ** 2 + 4 * jxy * jxy)
    return float(diff / trace)


def phash(gray: np.ndarray) -> int:
    """64-bit DCT perceptual hash."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    low = cv2.dct(small)[:8, :8].flatten()
    bits = low > np.median(low[1:])
    return int(np.packbits(bits).view(">u8")[0])


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def text_candidates(gray: np.ndarray) -> list[Box]:
    """Regions that look like lines of high-contrast text.

    Classic morphology approach: strong gradients, joined horizontally into
    line-shaped blobs, then filtered by size, fill and stroke density. It also
    fires on real signage in the scene; ``overlay_boxes`` separates burnt-in
    overlays (which stay fixed on screen while the camera moves) from those.
    """
    h_img, w_img = gray.shape
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    otsu, _ = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Overlays are rendered with hard, high-contrast edges.
    bw = (grad > max(otsu, 80)).astype(np.uint8) * 255
    # Keep only glyph/word-sized pieces so long scene edges can't merge into a line.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    glyph = (
        (stats[:, cv2.CC_STAT_HEIGHT] >= 0.012 * h_img)
        & (stats[:, cv2.CC_STAT_HEIGHT] <= 0.10 * h_img)
        & (stats[:, cv2.CC_STAT_WIDTH] <= 0.4 * w_img)
    )
    glyph[0] = False  # background
    bw = np.where(glyph[labels], 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w_img // 80), 1))
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[Box] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # A scene detail touching the line stretches its box; trim to the
        # longest run of rows that carry most of the ink.
        rows = np.count_nonzero(bw[y : y + h, x : x + w], axis=1)
        if rows.max() == 0:
            continue
        dense = np.flatnonzero(np.diff(np.r_[0, (rows > 0.3 * rows.max()).astype(np.int8), 0]))
        starts, ends = dense[::2], dense[1::2]
        k = int(np.argmax(ends - starts))
        y, h = y + int(starts[k]), int(ends[k] - starts[k])
        cols = np.flatnonzero(np.count_nonzero(bw[y : y + h, x : x + w], axis=0))
        if cols.size == 0:
            continue
        x, w = x + int(cols[0]), int(cols[-1] - cols[0] + 1)
        if not (0.012 * h_img <= h <= 0.10 * h_img):
            continue
        if w < 2.0 * h or w < 0.03 * w_img:
            continue
        roi = bw[y : y + h, x : x + w]
        fill = cv2.countNonZero(roi) / (w * h)
        if not 0.25 <= fill <= 0.9:
            continue
        # Glyphs give many on/off transitions along the line's middle row.
        mid = roi[h // 2] > 0
        transitions = int(np.count_nonzero(mid[1:] != mid[:-1]))
        if transitions < 1.5 * w / h:
            continue
        boxes.append((x / w_img, y / h_img, w / w_img, h / h_img))
    return boxes


def _box_slice(box: Box, shape: tuple[int, int]) -> tuple[slice, slice]:
    h, w = shape
    x0, y0 = int(box[0] * w), int(box[1] * h)
    x1, y1 = max(x0 + 1, int((box[0] + box[2]) * w)), max(y0 + 1, int((box[1] + box[3]) * h))
    return slice(y0, y1), slice(x0, x1)


def overlay_boxes(
    boxes: list[Box],
    cur: np.ndarray,
    neighbours: list[np.ndarray],
    *,
    min_motion: float = 8.0,
    static_ratio: float = 0.3,
) -> list[Box]:
    """Text boxes that stay put on screen while the rest of the frame moves.

    ``cur`` and ``neighbours`` are same-size grayscale frames from the same
    video. With a moving camera, scene text shifts between frames; a burnt-in
    caption, logo or timestamp does not. Differences are measured only on edge
    pixels: flat areas look unchanged under motion and would hide the shift.
    """
    if not boxes:
        return []
    grad = cv2.morphologyEx(cur, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    edges = grad > 40
    # Camera motion is judged outside the candidates, which may all be overlays.
    scene_edges = edges & (paint_boxes(boxes, cur.shape) == 0)
    if scene_edges.sum() < 0.001 * edges.size:
        return []
    cur_f = cur.astype(np.int16)
    pairs = []
    for nb in neighbours:
        diff = np.abs(cur_f - nb.astype(np.int16))
        motion = float(diff[scene_edges].mean())
        if motion >= min_motion:  # a static camera gives no evidence either way
            pairs.append((diff, motion))
    out = []
    for box in boxes:
        sl = _box_slice(box, cur.shape)
        box_edges = edges[sl]
        if not box_edges.any():
            continue
        # Median: glyph edges dominate an overlay box; scene edges between glyphs don't count.
        if any(float(np.median(diff[sl][box_edges])) < static_ratio * motion for diff, motion in pairs):
            out.append(box)
    return out


def paint_boxes(boxes: list[Box], shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    for box in boxes:
        mask[_box_slice(box, shape)] = 1
    return mask
