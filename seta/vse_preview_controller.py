from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import signal
from typing import Callable, Optional, Tuple

import bpy
from PIL import Image

from .state import (
    STATE,
    PREVIEW_BACKEND_NONE,
    PREVIEW_BACKEND_VSE,
)
from . import camera_manager
from . import image_processing
from . import process_manager
from . import sequencer_utils


ReportFn = Optional[Callable[[set, str], None]]

SETA_VSE_PREVIEW_STRIP_FALLBACK_NAME = "SETA_VSE_LIVE_PREVIEW"
SETA_VSE_PREVIEW_FILENAME = "seta_live_preview.jpg"
SETA_VSE_CACHE_DIRNAME = "seta_cache"
DEFAULT_VSE_PREVIEW_TIMER_INTERVAL = 0.5
DEFAULT_VSE_PREVIEW_WRITER_FPS = 1


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def _is_running(proc: Optional[subprocess.Popen]) -> bool:
    return bool(proc and proc.poll() is None)


def is_vse_preview_running() -> bool:
    return _is_running(STATE.preview_procs.vse_writer)


def _get_live_preview_dir() -> str:
    cache_dir = os.path.join(tempfile.gettempdir(), SETA_VSE_CACHE_DIRNAME)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _get_live_preview_path() -> str:
    return os.path.join(_get_live_preview_dir(), SETA_VSE_PREVIEW_FILENAME)


def _ensure_placeholder_image(scene, image_path: str) -> None:
    target_w, target_h = image_processing.get_effective_render_size(scene)
    os.makedirs(os.path.dirname(image_path), exist_ok=True)

    img = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    try:
        img.save(image_path, quality=95)
    finally:
        img.close()


def _ensure_sequence_editor(scene):
    if not scene.sequence_editor:
        scene.sequence_editor_create()
    return scene.sequence_editor


def _find_preview_strip(scene):
    seq = scene.sequence_editor
    if not seq:
        return None

    strip_name = getattr(scene, "seta_vse_preview_strip_name", "")
    strip = sequencer_utils.strip_by_name(seq, strip_name)
    if strip is not None:
        return strip

    return sequencer_utils.strip_by_name(seq, SETA_VSE_PREVIEW_STRIP_FALLBACK_NAME)


def get_vse_preview_strip(scene):
    return _find_preview_strip(scene)


def _apply_scene_alpha_to_strip(scene, strip) -> None:
    if scene is None or strip is None or not hasattr(scene, "seta_vse_preview_alpha"):
        return

    try:
        strip.blend_alpha = float(scene.seta_vse_preview_alpha)
    except Exception:
        pass


def sync_preview_strip_to_current_frame(context) -> None:
    strip = _find_preview_strip(context.scene)
    if strip is None:
        return

    try:
        strip.frame_start = int(context.scene.frame_current)
    except Exception:
        pass


def _create_preview_strip(context, image_path: str):
    scene = context.scene
    seq_editor = _ensure_sequence_editor(scene)

    active_name, selected_names = sequencer_utils.capture_selection_snapshot(seq_editor)
    frame_start = int(scene.frame_current)
    channel = int(getattr(scene, "seta_vse_preview_channel", 5) or 5)

    try:
        bpy.ops.sequencer.image_strip_add(
            directory=os.path.dirname(image_path),
            files=[{"name": os.path.basename(image_path)}],
            frame_start=frame_start,
            channel=channel,
            fit_method='ORIGINAL',
            move_strips=False,
        )
    except TypeError:
        bpy.ops.sequencer.image_strip_add(
            directory=os.path.dirname(image_path),
            files=[{"name": os.path.basename(image_path)}],
            frame_start=frame_start,
            channel=channel,
            move_strips=False,
        )

    strip = getattr(scene.sequence_editor, "active_strip", None)
    if strip is None:
        sequencer_utils.restore_selection_snapshot(seq_editor, active_name, selected_names)
        raise RuntimeError("Could not create VSE preview strip.")

    strip.name = SETA_VSE_PREVIEW_STRIP_FALLBACK_NAME
    try:
        strip.frame_final_duration = 1
    except Exception:
        pass

    scene.seta_vse_preview_strip_name = strip.name
    _apply_scene_alpha_to_strip(scene, strip)

    sequencer_utils.restore_selection_snapshot(seq_editor, active_name, selected_names)
    return strip


def _ensure_preview_strip(context):
    strip = _find_preview_strip(context.scene)
    if strip is not None:
        _apply_scene_alpha_to_strip(context.scene, strip)
        return strip
    return _create_preview_strip(context, _get_live_preview_path())


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _update_preview_dimensions_from_file(scene, image_path: str) -> None:
    if scene is None:
        return

    try:
        if not image_path or not os.path.isfile(image_path):
            return
        with Image.open(image_path) as img:
            width, height = img.size
        scene.seta_vse_preview_width = int(width)
        scene.seta_vse_preview_height = int(height)
    except Exception:
        pass


def _start_writer_process(context, output_path: str, report_fn: ReportFn = None) -> bool:
    driver = camera_manager.get_active_driver()
    if driver is None:
        _report(report_fn, "ERROR", "No active camera driver available for VSE preview.")
        return False

    source_cmd = driver.build_preview_source_cmd()
    if not source_cmd:
        _report(report_fn, "ERROR", "Active camera driver does not support VSE preview.")
        return False

    crop_filter = image_processing.build_ffmpeg_center_crop_filter_for_scene(context.scene)
    source = shlex.join(source_cmd)
    output_quoted = shlex.quote(output_path)

    writer_cmd = (
        f"{source} | "
        f"ffmpeg -hide_banner -loglevel warning -f mjpeg -i - "
        f"-vf \"{crop_filter},fps={DEFAULT_VSE_PREVIEW_WRITER_FPS}\" "
        f"-q:v 2 -update 1 -y {output_quoted}"
    )

    try:
        proc = subprocess.Popen(
            ["bash", "-c", "set -m; exec " + writer_cmd],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as ex:
        _report(report_fn, "ERROR", f"Failed to start VSE preview writer: {ex}")
        return False

    STATE.preview_procs.vse_writer = proc
    return True


def _stop_writer_process() -> None:
    proc = STATE.preview_procs.vse_writer
    if proc is None:
        return

    try:
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            try:
                proc.wait(timeout=0.8)
            except Exception:
                pass

        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=0.6)
            except Exception:
                pass

        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            try:
                proc.wait(timeout=0.4)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        STATE.preview_procs.vse_writer = None


def _register_timer() -> None:
    if STATE.vse_preview_timer_registered:
        return
    bpy.app.timers.register(_timer_tick, persistent=False)
    STATE.vse_preview_timer_registered = True


def _unregister_timer() -> None:
    if not STATE.vse_preview_timer_registered:
        return

    try:
        bpy.app.timers.unregister(_timer_tick)
    except Exception:
        pass

    STATE.vse_preview_timer_registered = False


def _timer_tick():
    if STATE.preview_backend != PREVIEW_BACKEND_VSE:
        STATE.vse_preview_timer_registered = False
        return None

    if not is_vse_preview_running():
        stop_vse_preview(report_fn=None, manual=False)
        return None

    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None:
        return DEFAULT_VSE_PREVIEW_TIMER_INTERVAL

    live_path = _get_live_preview_path()
    mtime = _file_mtime(live_path)
    if mtime <= 0.0:
        return DEFAULT_VSE_PREVIEW_TIMER_INTERVAL

    if mtime != STATE.vse_preview_last_mtime:
        strip = _find_preview_strip(scene)
        if strip is None:
            try:
                strip = _ensure_preview_strip(context)
            except Exception:
                strip = None

        if strip is not None and sequencer_utils.reload_strip_transactional(context, strip):
            STATE.vse_preview_last_mtime = mtime
            _update_preview_dimensions_from_file(scene, live_path)

    return DEFAULT_VSE_PREVIEW_TIMER_INTERVAL


def start_vse_preview(context, report_fn: ReportFn = None) -> bool:
    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, VSE preview not started.")
        return False

    driver = camera_manager.get_active_driver()
    if driver is None:
        _report(report_fn, "ERROR", "No active camera driver available for VSE preview.")
        return False
    source_cmd = driver.build_preview_source_cmd()
    if not source_cmd:
        _report(report_fn, "ERROR", "Active camera driver does not support VSE preview.")
        return False

    if STATE.preview_running and STATE.preview_backend == PREVIEW_BACKEND_VSE:
        return True

    context.scene.seta_vse_preview_width = 0
    context.scene.seta_vse_preview_height = 0

    live_path = _get_live_preview_path()
    _ensure_placeholder_image(context.scene, live_path)

    try:
        _ensure_preview_strip(context)
    except Exception as ex:
        _report(report_fn, "ERROR", f"Failed to create VSE preview strip: {ex}")
        return False

    STATE.vse_preview_last_mtime = 0.0

    if not _start_writer_process(context, live_path, report_fn=report_fn):
        return False

    _register_timer()

    STATE.preview_running = True
    STATE.preview_backend = PREVIEW_BACKEND_VSE

    _report(report_fn, "INFO", "VSE preview started.")
    return True


def stop_vse_preview(report_fn: ReportFn = None, manual: bool = True) -> None:
    _unregister_timer()
    _stop_writer_process()

    driver = camera_manager.get_active_driver()
    process_manager.aggressive_preview_cleanup(driver)

    STATE.vse_preview_last_mtime = 0.0
    STATE.preview_procs.vse_writer = None
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene.seta_vse_preview_width = 0
        scene.seta_vse_preview_height = 0

    if STATE.preview_backend == PREVIEW_BACKEND_VSE:
        STATE.preview_running = False
        STATE.preview_backend = PREVIEW_BACKEND_NONE

    if manual:
        _report(report_fn, "INFO", "VSE preview stopped.")


def refresh_vse_preview(context, report_fn: ReportFn = None) -> None:
    if not is_vse_preview_running():
        return

    strip = _find_preview_strip(context.scene)
    if strip is None:
        return

    if sequencer_utils.reload_strip_transactional(context, strip):
        _report(report_fn, "INFO", "VSE preview refreshed.")
