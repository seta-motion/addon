from __future__ import annotations

import os
import tempfile
import time
from typing import Callable, Optional, Tuple

from PIL import Image

from .state import STATE
from . import camera_manager
from . import preview_controller


ReportFn = Optional[Callable[[set, str], None]]


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def get_cached_native_resolution(scene) -> Optional[Tuple[int, int]]:
    width = int(getattr(scene, "seta_camera_native_width", 0) or 0)
    height = int(getattr(scene, "seta_camera_native_height", 0) or 0)

    if width <= 0 or height <= 0:
        return None

    return width, height


def _set_cached_native_resolution(scene, width: int, height: int) -> None:
    scene.seta_camera_native_width = max(0, int(width))
    scene.seta_camera_native_height = max(0, int(height))


def _capture_tempfile_path() -> str:
    fd, temp_path = tempfile.mkstemp(prefix="seta_probe_", suffix=".jpg")
    os.close(fd)
    return temp_path


def _measure_image_size(path: str) -> Tuple[int, int]:
    with Image.open(path) as img:
        width, height = img.size

    width = int(width)
    height = int(height)

    if width <= 0 or height <= 0:
        raise ValueError("Measured image has invalid size.")

    return width, height


def _measure_camera_capture(context, report_fn: ReportFn = None) -> Optional[Tuple[int, int]]:
    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, camera resolution not measured.")
        return None

    driver = camera_manager.get_active_driver()
    if not driver:
        _report(report_fn, "ERROR", "No active camera driver available for measurement.")
        return None

    was_preview_running = preview_controller.is_preview_running()
    resume_backend = preview_controller.get_running_preview_backend() if was_preview_running else None
    temp_capture_path = _capture_tempfile_path()
    measured_size: Optional[Tuple[int, int]] = None

    STATE.camera_busy = True

    try:
        if was_preview_running:
            preview_controller.stop_preview(report_fn=None, manual=False)
            time.sleep(1.5)

        delays = [0.5, 1.0, 1.5]

        for delay in delays:
            ok = False
            try:
                ok = bool(driver.capture(temp_capture_path))
            except Exception:
                ok = False

            if ok and os.path.exists(temp_capture_path):
                try:
                    measured_size = _measure_image_size(temp_capture_path)
                except Exception:
                    measured_size = None
                if measured_size:
                    _set_cached_native_resolution(context.scene, *measured_size)
                    break

            time.sleep(delay)

        if not measured_size:
            _report(report_fn, "ERROR", "Could not measure camera capture resolution.")

    finally:
        STATE.camera_busy = False

        try:
            if os.path.exists(temp_capture_path):
                os.remove(temp_capture_path)
        except Exception:
            pass

        if was_preview_running and resume_backend:
            preview_controller.start_preview(context, report_fn=report_fn, backend=resume_backend)

    return measured_size


def _scaled_dimensions(width: int, height: int, scale: float) -> Tuple[int, int]:
    scaled_w = max(1, int(round(float(width) * float(scale))))
    scaled_h = max(1, int(round(float(height) * float(scale))))
    return scaled_w, scaled_h


def _apply_render_size(context, width: int, height: int) -> None:
    render = context.scene.render
    render.resolution_x = int(width)
    render.resolution_y = int(height)
    render.resolution_percentage = 100


def apply_camera_resolution_scale(
    context,
    scale: float,
    report_fn: ReportFn = None,
    force_remeasure: bool = False,
) -> bool:
    try:
        scale = float(scale)
    except Exception:
        _report(report_fn, "ERROR", "Invalid camera scale value.")
        return False

    if scale <= 0.0:
        _report(report_fn, "ERROR", "Camera scale must be greater than zero.")
        return False

    native_size = None if force_remeasure else get_cached_native_resolution(context.scene)
    if not native_size:
        native_size = _measure_camera_capture(context, report_fn=report_fn)

    if not native_size:
        return False

    native_w, native_h = native_size
    target_w, target_h = _scaled_dimensions(native_w, native_h, scale)

    _apply_render_size(context, target_w, target_h)

    percent = int(round(scale * 100.0))
    _report(
        report_fn,
        "INFO",
        f"Render size set to {target_w} x {target_h} from camera native {native_w} x {native_h} ({percent}%).",
    )
    return True
