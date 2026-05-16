# image_processing.py

from __future__ import annotations

import math
import os
import shutil
from typing import Tuple

from PIL import Image


def get_effective_render_size(scene) -> Tuple[int, int]:
    """
    Return the effective render output size, including render percentage.
    Always returns at least 1x1.
    """
    render = scene.render

    base_w = int(getattr(render, "resolution_x", 1920))
    base_h = int(getattr(render, "resolution_y", 1080))
    percentage = int(getattr(render, "resolution_percentage", 100))

    scale = max(1, percentage) / 100.0

    out_w = max(1, int(round(base_w * scale)))
    out_h = max(1, int(round(base_h * scale)))

    return out_w, out_h


def compute_center_crop_box(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
) -> Tuple[int, int, int, int]:
    """
    Compute a centered crop box so the source matches the target aspect ratio
    without distortion.

    Returns:
        (left, top, right, bottom)
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Invalid source image size.")

    if target_w <= 0 or target_h <= 0:
        raise ValueError("Invalid target render size.")

    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if math.isclose(src_ratio, target_ratio, rel_tol=1e-9, abs_tol=1e-9):
        return 0, 0, src_w, src_h

    if src_ratio > target_ratio:
        # Source is wider than target ratio: crop left/right.
        crop_w = int(round(src_h * target_ratio))
        crop_w = max(1, min(crop_w, src_w))
        left = (src_w - crop_w) // 2
        right = left + crop_w
        return left, 0, right, src_h

    # Source is taller than target ratio: crop top/bottom.
    crop_h = int(round(src_w / target_ratio))
    crop_h = max(1, min(crop_h, src_h))
    top = (src_h - crop_h) // 2
    bottom = top + crop_h
    return 0, top, src_w, bottom


def build_working_image_from_path(src_path: str, scene) -> Image.Image:
    """
    Open the original capture, crop it to the render aspect ratio (centered),
    then resize it to the effective render size.

    Returns a new PIL Image object.
    """
    target_w, target_h = get_effective_render_size(scene)

    with Image.open(src_path) as img:
        # Normalize mode only as needed.
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")

        src_w, src_h = img.size
        crop_box = compute_center_crop_box(src_w, src_h, target_w, target_h)

        cropped = img.crop(crop_box)
        working = cropped.resize((target_w, target_h), Image.LANCZOS)

        return working.copy()


def build_ffmpeg_center_crop_filter_for_scene(scene) -> str:
    """
    Build an ffmpeg crop expression that matches the working-image geometry:
    centered crop to the effective render aspect ratio, without scaling.
    """
    target_w, target_h = get_effective_render_size(scene)
    target_ratio = target_w / target_h

    ratio_str = f"{target_ratio:.12f}".rstrip("0").rstrip(".")
    if not ratio_str:
        ratio_str = "1"

    crop_w = f"if(gt(iw/ih\\,{ratio_str})\\,ih*{ratio_str}\\,iw)"
    crop_h = f"if(gt(iw/ih\\,{ratio_str})\\,ih\\,iw/{ratio_str})"

    return (
        f"crop={crop_w}:{crop_h}:"
        f"(iw-ow)/2:(ih-oh)/2"
    )


def save_original_copy(src_path: str, dst_path: str) -> None:
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)


def save_working_image(img: Image.Image, dst_path: str) -> None:
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    ext = os.path.splitext(dst_path)[1].lower()

    if ext in {".jpg", ".jpeg"}:
        save_img = img
        if save_img.mode == "RGBA":
            save_img = save_img.convert("RGB")
        save_img.save(dst_path, quality=95)
        return

    if ext == ".png":
        img.save(dst_path)
        return

    img.save(dst_path)


def get_original_path_for_working_path(working_path: str) -> str:
    """
    Given a working image path:
        /shots/shot_0001.jpg

    Return:
        /shots/_originals/shot_0001.jpg
    """
    working_dir = os.path.dirname(working_path)
    filename = os.path.basename(working_path)
    originals_dir = os.path.join(working_dir, "_originals")
    return os.path.join(originals_dir, filename)