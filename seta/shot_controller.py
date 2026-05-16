# shot_controller.py

from __future__ import annotations

import os
import tempfile
import time
from typing import Callable, Optional, List

import bpy

from .state import STATE, PREVIEW_BACKEND_NONE, PREVIEW_BACKEND_FAST, PREVIEW_BACKEND_VSE
from . import preview_controller
from . import camera_manager
from . import shot_mapping
from . import strip_ops
from . import image_processing
from . import vse_preview_controller


ReportFn = Optional[Callable[[set, str], None]]
_TEST_SHOT_DIRNAME = "seta_motion"
_TEST_SHOT_FILENAME = "test_shot.jpg"


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def _looks_like_usb_busy(text: str) -> bool:
    if not text:
        return False
    return (
        "Could not claim the USB device" in text
        or "Device or resource busy" in text
        or "Error (-53" in text
        or "(-53" in text
    )


def _capture_to_tempfile() -> str:
    fd, temp_path = tempfile.mkstemp(prefix="seta_capture_", suffix=".jpg")
    os.close(fd)
    return temp_path


def _get_test_shot_path() -> str:
    temp_dir = os.path.join(tempfile.gettempdir(), _TEST_SHOT_DIRNAME)
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, _TEST_SHOT_FILENAME)


def _load_test_shot_image(image_path: str):
    normalized = os.path.normcase(os.path.normpath(image_path))

    for img in bpy.data.images:
        existing_path = str(getattr(img, "filepath", "") or "")
        if not existing_path:
            continue
        if os.path.normcase(os.path.normpath(existing_path)) == normalized:
            try:
                img.reload()
            except Exception:
                pass
            return img

    image = bpy.data.images.load(image_path, check_existing=True)
    try:
        image.reload()
    except Exception:
        pass
    return image


def _show_image_in_new_window(context, image):
    windows_before = {w.as_pointer() for w in bpy.context.window_manager.windows}

    bpy.ops.wm.window_new()

    target_window = None
    for win in bpy.context.window_manager.windows:
        if win.as_pointer() not in windows_before:
            target_window = win
            break
    if target_window is None:
        target_window = bpy.context.window

    if target_window is None or target_window.screen is None:
        return False, "Could not resolve target window."

    target_area = target_window.screen.areas[0] if target_window.screen.areas else None
    if target_area is None:
        return False, "Could not resolve target area."

    target_area.type = "IMAGE_EDITOR"
    space = next((s for s in target_area.spaces if s.type == "IMAGE_EDITOR"), None)
    if space is None:
        return False, "Could not initialize IMAGE_EDITOR space."

    space.image = image
    if hasattr(space, "use_image_pin"):
        space.use_image_pin = True

    return True, ""


def _write_capture_to_targets(temp_capture_path: str, targets: List[str], context) -> None:
    """
    For one captured source file:
    - save the original full-res copy to _originals/
    - build one working image (crop to render aspect, then resize to render size)
    - write that working image into every target for the current hold mode
    """
    if not targets:
        return

    # Save original for each concrete target path.
    for target in targets:
        original_path = image_processing.get_original_path_for_working_path(target)
        image_processing.save_original_copy(temp_capture_path, original_path)

    # Build the working image once and reuse it for all hold targets.
    working_img = image_processing.build_working_image_from_path(
        temp_capture_path,
        context.scene,
    )

    try:
        for target in targets:
            image_processing.save_working_image(working_img, target)
    finally:
        try:
            working_img.close()
        except Exception:
            pass


def _advance_playhead(context, count: int) -> None:
    context.scene.frame_current = int(context.scene.frame_current) + int(count)


def _run_post_shot_automation(
    context,
    hold_count: int,
    resume_backend: str,
    report_fn: ReportFn = None,
) -> None:
    scene = context.scene

    if scene.seta_auto_advance:
        strip = shot_mapping.get_active_image_strip(context)
        if strip:
            strip_ops.ensure_strip_covers_current_shot(context, hold_count)
            strip_ops.reload_active_strip(context, report_fn=report_fn)
            _advance_playhead(context, hold_count)
            if resume_backend == PREVIEW_BACKEND_VSE:
                vse_preview_controller.sync_preview_strip_to_current_frame(context)
        else:
            _report(
                report_fn,
                "WARNING",
                "Shot captured, but automatic strip update was skipped because no valid active IMAGE strip was found.",
            )

    if resume_backend != PREVIEW_BACKEND_NONE:
        preview_controller.start_preview(
            context,
            report_fn=report_fn,
            backend=resume_backend,
        )
        STATE.preview_resume_backend = PREVIEW_BACKEND_NONE


def take_shot_provisional(context, report_fn: ReportFn = None) -> bool:
    """
    Current real shot flow:
    - requires valid active IMAGE strip
    - resolves concrete destination files from strip + playhead + hold mode
    - stops preview if it was running
    - captures one temp photo
    - saves original full-res copies in _originals/
    - writes working images (crop + resize to render size) to 1/2/3 target files
      depending on hold mode
    - if auto advance is enabled:
        - ensures strip covers the new shot
        - reloads selected strip
        - advances playhead
    - relaunches preview at the end if it had been running before
    """
    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, shot ignored.")
        return False

    hold_mode = context.scene.seta_hold_mode
    hold_count = shot_mapping.get_hold_count(hold_mode)

    targets, reason = shot_mapping.resolve_capture_targets(context, hold_mode)
    if not targets:
        _report(report_fn, "WARNING", reason or "Could not resolve shot targets.")
        return False

    resume_backend = STATE.preview_backend
    if resume_backend not in {PREVIEW_BACKEND_NONE, PREVIEW_BACKEND_FAST, PREVIEW_BACKEND_VSE}:
        resume_backend = PREVIEW_BACKEND_NONE
    STATE.preview_resume_backend = resume_backend

    write_targets = targets
    if resume_backend == PREVIEW_BACKEND_VSE:
        write_targets = shot_mapping.extend_targets_with_next_frame(targets)

    STATE.camera_busy = True
    temp_capture_path = _capture_to_tempfile()
    shot_written = False

    try:
        if resume_backend != PREVIEW_BACKEND_NONE:
            preview_controller.stop_preview(report_fn=report_fn, manual=False)
            time.sleep(1.5)
        else:
            preview_controller.stop_preview(report_fn=None, manual=False)
            time.sleep(0.5)

        driver = camera_manager.get_active_driver()
        if not driver:
            _report(report_fn, "ERROR", "No active camera driver available for capture.")
            return False

        delays = [0.5, 1.0, 1.5, 2.0]
        last_err = ""

        for attempt in range(len(delays)):
            try:
                ok = driver.capture(temp_capture_path)
                if ok:
                    _write_capture_to_targets(temp_capture_path, write_targets, context)
                    shot_written = True
                    _report(report_fn, "INFO", f"Shot written: {len(write_targets)} frame(s).")
                    last_err = ""
                    break
                last_err = "Shot failed."

            except Exception as e:
                last_err = str(e)

            if _looks_like_usb_busy(last_err):
                preview_controller.stop_preview(report_fn=None, manual=False)

            time.sleep(delays[min(attempt, len(delays) - 1)])

        if last_err and not shot_written:
            _report(report_fn, "ERROR", "Shot failed.")

    finally:
        STATE.camera_busy = False
        try:
            if os.path.exists(temp_capture_path):
                os.remove(temp_capture_path)
        except Exception:
            pass

    if shot_written:
        _run_post_shot_automation(
            context=context,
            hold_count=hold_count,
            resume_backend=resume_backend,
            report_fn=report_fn,
        )
    elif resume_backend != PREVIEW_BACKEND_NONE:
        preview_controller.start_preview(
            context,
            report_fn=report_fn,
            backend=resume_backend,
        )
        STATE.preview_resume_backend = PREVIEW_BACKEND_NONE

    return shot_written


def take_test_shot(context, report_fn: ReportFn = None) -> bool:
    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, test shot ignored.")
        return False

    driver = camera_manager.get_active_driver()
    if not driver:
        _report(report_fn, "ERROR", "No active camera driver available for test shot.")
        return False

    resume_backend = STATE.preview_backend
    if resume_backend not in {PREVIEW_BACKEND_NONE, PREVIEW_BACKEND_FAST, PREVIEW_BACKEND_VSE}:
        resume_backend = PREVIEW_BACKEND_NONE
    STATE.preview_resume_backend = resume_backend

    test_shot_path = _get_test_shot_path()
    shot_written = False
    last_err = ""
    STATE.camera_busy = True

    try:
        if resume_backend != PREVIEW_BACKEND_NONE:
            preview_controller.stop_preview(report_fn=report_fn, manual=False)
            time.sleep(1.5)
        else:
            preview_controller.stop_preview(report_fn=None, manual=False)
            time.sleep(0.5)

        delays = [0.5, 1.0, 1.5]
        for attempt in range(len(delays)):
            try:
                shot_written = bool(driver.capture(test_shot_path))
                if shot_written:
                    break
                last_err = "Test shot failed."
            except Exception as e:
                last_err = str(e)

            if _looks_like_usb_busy(last_err):
                preview_controller.stop_preview(report_fn=None, manual=False)

            time.sleep(delays[min(attempt, len(delays) - 1)])

        if not shot_written:
            _report(report_fn, "ERROR", f"Test shot failed. {last_err}".strip())
            return False

        _report(report_fn, "INFO", "Test shot captured.")
        image = _load_test_shot_image(test_shot_path)
        shown, reason = _show_image_in_new_window(context, image)
        if not shown:
            _report(
                report_fn,
                "WARNING",
                f"Test shot captured but viewer could not be opened. File: {test_shot_path}. Reason: {reason}",
            )

    finally:
        STATE.camera_busy = False
        if resume_backend != PREVIEW_BACKEND_NONE:
            preview_controller.start_preview(
                context,
                report_fn=report_fn,
                backend=resume_backend,
            )
        STATE.preview_resume_backend = PREVIEW_BACKEND_NONE

    return shot_written
