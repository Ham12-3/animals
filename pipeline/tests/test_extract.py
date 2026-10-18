import json
from collections import Counter

import cv2
import numpy as np
import pytest

from vantara_pipeline.extract import Config, run_extraction
from vantara_pipeline.quality import hamming, phash

from .synthetic import make_video, segment_at


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("zone")
    video = make_video(tmp / "walk.mp4")
    out = tmp / "work"
    cfg = Config(fps=2.5, min_frames=10, max_frames=400)
    report = run_extraction("test-zone", [video], out, cfg)
    rows = [line.split(",") for line in (out / "frames.csv").read_text().splitlines()[1:]]
    by_segment: dict[str, Counter] = {}
    for name, _video, t, *_scores, decision in rows:
        by_segment.setdefault(segment_at(float(t)), Counter())[decision] += 1
    return report, out, by_segment


def test_clean_frames_are_kept(result):
    _, _, seg = result
    clean = seg["clean"]
    assert clean["kept"] / clean.total() >= 0.9, clean


def test_out_of_focus_frames_dropped(result):
    blur = result[2]["blur"]
    assert blur["kept"] <= 1 and blur["blur"] >= 3, blur


def test_motion_blur_dropped(result):
    mb = result[2]["motion_blur"]
    assert mb["kept"] <= 1 and mb["motion_blur"] >= 3, mb


def test_caption_frames_dropped(result):
    cap = result[2]["caption"]
    assert cap["kept"] <= 1 and cap["text_overlay"] >= 8, cap


def test_still_camera_deduplicated(result):
    still = result[2]["still"]
    assert still["kept"] <= 2 and still["duplicate"] >= 7, still


def test_fixed_watermark_masked_not_dropped(result):
    report, out, _ = result
    assert report["videos"][0]["fixed_overlay_masked"]
    masks = sorted((out / "masks").glob("*.png"))
    assert len(masks) == report["kept"]
    m = cv2.imread(str(masks[0]), cv2.IMREAD_GRAYSCALE)
    assert m[30, 1150] == 0  # watermark ignored
    assert m[360, 640] == 255  # scene kept


def test_outputs(result):
    report, out, _ = result
    assert len(list((out / "frames").glob("*.jpg"))) == report["kept"]
    assert (out / "contact_sheet.jpg").is_file()
    assert json.loads((out / "extract_report.json").read_text())["kept"] == report["kept"]
    assert not (out / "_raw").exists()
    names = sorted(p.name for p in (out / "frames").glob("*.jpg"))
    assert names[0].startswith("v01_")


def test_budget_trims_evenly(tmp_path):
    video = make_video(tmp_path / "walk.mp4")
    report = run_extraction("z", [video], tmp_path / "w", Config(fps=2.5, min_frames=5, max_frames=20))
    assert report["kept"] == 20
    assert report["rejected"]["over_budget"] > 0


def test_phash_is_stable_and_discriminative():
    rng = np.random.default_rng(0)
    a = (rng.random((360, 640)) * 255).astype(np.uint8)
    a = cv2.GaussianBlur(a, (0, 0), 3)
    b = cv2.convertScaleAbs(a, alpha=1.1, beta=5)  # exposure change only
    c = np.roll(a, 200, axis=1)
    assert hamming(phash(a), phash(b)) <= 4
    assert hamming(phash(a), phash(c)) > 10


def test_time_range_source(tmp_path):
    from vantara_pipeline.zones import Source

    video = make_video(tmp_path / "walk.mp4")
    src = Source.parse(f"{video}#t=20,28")
    assert (src.start, src.end) == (20.0, 28.0)
    report = run_extraction("z", [src], tmp_path / "w", Config(fps=2.5, min_frames=5))
    assert report["extracted"] == 20  # 8 s at 2.5 fps, all from the clean stretch
    assert report["kept"] >= 18
    assert report["videos"][0]["file"] == "walk.mp4#t=20,28"


def test_find_shots_splits_at_cuts(tmp_path):
    import subprocess

    from vantara_pipeline.shots import find_shots

    # Two different "places" joined with a hard cut at 30 s.
    a, b = make_video(tmp_path / "a.mp4"), make_video(tmp_path / "b.mp4", seed=11)
    joined = tmp_path / "joined.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(a), "-i", str(b), "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", str(joined)], check=True)  # fmt: skip
    shots, _ = find_shots(joined)
    starts = [s.start for s in shots]
    assert any(abs(t - 30.5) < 0.6 for t in starts), starts
    # The synthetic clip's own blur/caption/pause segments are not cuts.
    assert len(shots) <= 3, starts


def test_every_kept_frame_gets_a_mask_when_any_clip_needs_one(tmp_path):
    # COLMAP skips images without a mask file once masks/ is used.
    a = make_video(tmp_path / "a.mp4")
    b = make_video(tmp_path / "b.mp4", seed=11, watermark=False)
    report = run_extraction("z", [a, b], tmp_path / "w", Config(fps=2.5, min_frames=5))
    masks = {m.name for m in (tmp_path / "w" / "masks").glob("*.png")}
    frames = {f"{f.name}.png" for f in (tmp_path / "w" / "frames").glob("*.jpg")}
    assert masks == frames and len(frames) == report["kept"]
    plain = cv2.imread(str(tmp_path / "w" / "masks" / sorted(m for m in masks if m.startswith("v02"))[0]), 0)
    assert (plain == 255).all()
