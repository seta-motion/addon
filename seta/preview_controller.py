from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from typing import Callable, Optional, Tuple

import bpy

from .state import (
    STATE,
    PREVIEW_BACKEND_NONE,
    PREVIEW_BACKEND_FAST,
    PREVIEW_BACKEND_VSE,
)
from . import camera_manager
from . import image_processing
from . import process_manager
from . import shot_mapping
from . import vse_preview_controller


ReportFn = Optional[Callable[[set, str], None]]


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def _is_running(proc: Optional[subprocess.Popen]) -> bool:
    return bool(proc and proc.poll() is None)


def _clear_fast_preview_procs() -> None:
    STATE.preview_procs.source = None
    STATE.preview_procs.ffplay = None


def _kill_pgid(proc: Optional[subprocess.Popen], sig) -> None:
    if not proc:
        return
    try:
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), sig)
    except Exception:
        pass


def _ensure_fast_preview_state_is_honest() -> None:
    if STATE.preview_backend != PREVIEW_BACKEND_FAST:
        return

    if not STATE.preview_running:
        return

    pipeline_proc = STATE.preview_procs.ffplay
    if not _is_running(pipeline_proc):
        _clear_fast_preview_procs()
        STATE.preview_running = False
        STATE.preview_backend = PREVIEW_BACKEND_NONE


def _is_fast_preview_running() -> bool:
    _ensure_fast_preview_state_is_honest()
    return STATE.preview_backend == PREVIEW_BACKEND_FAST and STATE.preview_running


def get_running_preview_backend() -> str:
    if STATE.preview_backend == PREVIEW_BACKEND_FAST and _is_fast_preview_running():
        return PREVIEW_BACKEND_FAST
    if STATE.preview_backend == PREVIEW_BACKEND_VSE and vse_preview_controller.is_vse_preview_running():
        return PREVIEW_BACKEND_VSE
    return PREVIEW_BACKEND_NONE


def is_preview_running() -> bool:
    return get_running_preview_backend() != PREVIEW_BACKEND_NONE


def _stop_fast_preview(report_fn: ReportFn = None, manual: bool = True, silent: bool = False) -> None:
    pipeline_proc = STATE.preview_procs.ffplay

    if _is_running(pipeline_proc):
        _kill_pgid(pipeline_proc, signal.SIGINT)
        try:
            pipeline_proc.wait(timeout=0.8)
        except Exception:
            pass

        if _is_running(pipeline_proc):
            _kill_pgid(pipeline_proc, signal.SIGTERM)
            try:
                pipeline_proc.wait(timeout=0.6)
            except Exception:
                pass

        if _is_running(pipeline_proc):
            _kill_pgid(pipeline_proc, signal.SIGKILL)
            try:
                pipeline_proc.wait(timeout=0.4)
            except Exception:
                pass

    process_manager.aggressive_preview_cleanup(camera_manager.get_active_driver())

    _clear_fast_preview_procs()
    STATE.preview_running = False
    if STATE.preview_backend == PREVIEW_BACKEND_FAST:
        STATE.preview_backend = PREVIEW_BACKEND_NONE

    if not silent:
        _report(report_fn, "INFO", "Preview stopped.")


def stop_preview(report_fn: ReportFn = None, manual: bool = True) -> None:
    backend = STATE.preview_backend

    if backend == PREVIEW_BACKEND_FAST:
        _stop_fast_preview(report_fn=report_fn, manual=manual, silent=False)
        return

    if backend == PREVIEW_BACKEND_VSE:
        vse_preview_controller.stop_vse_preview(report_fn=report_fn, manual=manual)
        return

    backend = get_running_preview_backend()

    if backend == PREVIEW_BACKEND_FAST:
        _stop_fast_preview(report_fn=report_fn, manual=manual, silent=False)
        return

    if backend == PREVIEW_BACKEND_VSE:
        vse_preview_controller.stop_vse_preview(report_fn=report_fn, manual=manual)
        return

    STATE.preview_running = False
    STATE.preview_backend = PREVIEW_BACKEND_NONE


def _get_active_strip(context) -> Optional[bpy.types.Sequence]:
    seq = context.scene.sequence_editor
    if not seq:
        return None
    return getattr(seq, "active_strip", None)


_NUMBERED_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<suffix>\.[^.]+)$")


def _parse_numbered_filename(filename: str):
    m = _NUMBERED_RE.match(filename)
    if not m:
        return None
    prefix = m.group("prefix")
    num_str = m.group("num")
    suffix = m.group("suffix")
    try:
        n = int(num_str)
    except ValueError:
        return None
    pad = len(num_str)
    return prefix, n, pad, suffix


def _resolve_previous_image_path(context) -> Tuple[Optional[str], Optional[str]]:
    strip = _get_active_strip(context)
    if not strip:
        return None, "No active strip selected, blend disabled."

    if getattr(strip, "type", None) != "IMAGE":
        return None, "Active strip is not an IMAGE strip, blend disabled."

    elements = getattr(strip, "elements", None)
    directory = getattr(strip, "directory", None)
    if not elements or not directory:
        return None, "No image sequence data found in active strip, blend disabled."

    targets, reason = shot_mapping.resolve_capture_targets(context, "SINGLE")
    if not targets:
        return None, reason or "No previous image found, blend disabled."
    cur_path = targets[0]
    base_name = os.path.basename(cur_path)
    dir_abs = os.path.dirname(cur_path)
    if not base_name or not dir_abs:
        return None, "No previous image found, blend disabled."

    parsed = _parse_numbered_filename(base_name)
    if not parsed:
        return None, "No previous image found, blend disabled."

    prefix, cur_num, pad, suffix = parsed
    prev_num = cur_num - 1
    if prev_num < 0:
        return None, "No previous image found, blend disabled."

    prev_name = f"{prefix}{prev_num:0{pad}d}{suffix}"
    prev_path = os.path.join(dir_abs, prev_name)

    if not os.path.exists(prev_path):
        return None, "No previous image found, blend disabled."

    return prev_path, None


def _build_center_crop_filter(context) -> str:
    return image_processing.build_ffmpeg_center_crop_filter_for_scene(context.scene)


def _ffplay_flags() -> str:
    return (
        "-hide_banner -loglevel warning "
        "-fflags nobuffer -flags low_delay -framedrop "
        "-avioflags direct -probesize 32 -analyzeduration 0"
    )


def _ffmpeg_raw_pipe_out() -> str:
    return "-an -c:v rawvideo -pix_fmt yuv420p -f nut -"


def _bash_pipeline_cmd(context, ref_image_path: Optional[str], source_cmd: list) -> list:
    ffplay_flags = _ffplay_flags()
    raw_pipe_out = _ffmpeg_raw_pipe_out()
    source = shlex.join(source_cmd)
    crop_filter = _build_center_crop_filter(context)

    if not ref_image_path:
        cmd_str = (
            f"{source} | "
            f"ffmpeg -hide_banner -loglevel warning -f mjpeg -i - "
            f"-vf \"{crop_filter},format=yuv420p\" "
            f"{raw_pipe_out} | "
            f"ffplay {ffplay_flags} -window_title 'SETA Preview' -"
        )
        return ["bash", "-c", "set -m; exec " + cmd_str]

    scene = context.scene
    blend_mode = scene.seta_onion_blend_mode
    blend_factor = scene.seta_onion_opacity
    ref_quoted = shlex.quote(ref_image_path)

    cmd_str = (
        f"{source} | "
        f"ffmpeg -hide_banner -loglevel warning -f mjpeg -i - -loop 1 -i {ref_quoted} "
        f"-filter_complex "
        f"\"[0:v]{crop_filter},format=yuv420p[cam];"
        f"[1:v]format=yuv420p[bg];"
        f"[bg][cam]scale2ref[bg_scaled][cam_ref];"
        f"[cam_ref][bg_scaled]blend=all_mode={blend_mode}:all_opacity={blend_factor},format=yuv420p\" "
        f"{raw_pipe_out} | "
        f"ffplay {ffplay_flags} -window_title 'SETA Preview (Blend)' -"
    )
    return ["bash", "-c", "set -m; exec " + cmd_str]


def _refresh_fast_preview(context, report_fn: ReportFn = None) -> None:
    _ensure_fast_preview_state_is_honest()

    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, preview not refreshed.")
        return

    if _is_fast_preview_running():
        _stop_fast_preview(report_fn=None, manual=False, silent=True)

    _start_fast_preview(context, report_fn=report_fn)


def refresh_preview(context, report_fn: ReportFn = None) -> None:
    backend = get_running_preview_backend()

    if backend == PREVIEW_BACKEND_FAST:
        _refresh_fast_preview(context, report_fn=report_fn)
        return

    if backend == PREVIEW_BACKEND_VSE:
        vse_preview_controller.refresh_vse_preview(context, report_fn=report_fn)
        return


def _start_fast_preview(context, report_fn: ReportFn = None) -> bool:
    _ensure_fast_preview_state_is_honest()

    if _is_fast_preview_running():
        return True

    if STATE.camera_busy:
        _report(report_fn, "WARNING", "Camera is busy, preview not started.")
        return False

    driver = camera_manager.get_active_driver()
    if not driver:
        _report(report_fn, "ERROR", "No active camera driver available for preview.")
        return False

    source_cmd = driver.build_preview_source_cmd()
    if not source_cmd:
        _report(report_fn, "ERROR", "Active camera driver does not support preview.")
        return False


    process_manager.aggressive_preview_cleanup(driver)

    ref_path = None
    try:
        ref_path, reason = _resolve_previous_image_path(context)
        if reason:
            _report(report_fn, "INFO", reason)
    except Exception as e:
        ref_path = None
        _report(report_fn, "WARNING", f"Blend resolver error, blend disabled. ({e})")

    cmd = _bash_pipeline_cmd(context, ref_path, source_cmd)

    try:
        proc = subprocess.Popen(
            cmd,
            preexec_fn=os.setsid,
            stdout=None,
            stderr=None,
        )

        time.sleep(0.15)
        if proc.poll() is not None:
            _clear_fast_preview_procs()
            STATE.preview_running = False
            STATE.preview_backend = PREVIEW_BACKEND_NONE
            _report(report_fn, "ERROR", "Preview failed to start (pipeline exited immediately).")
            return False

        STATE.preview_procs.ffplay = proc
        STATE.preview_procs.source = proc
        STATE.preview_running = True
        STATE.preview_backend = PREVIEW_BACKEND_FAST
        return True

    except Exception as e:
        _clear_fast_preview_procs()
        STATE.preview_running = False
        STATE.preview_backend = PREVIEW_BACKEND_NONE
        _report(report_fn, "ERROR", f"Failed to start preview: {e}")
        return False


def start_preview(context, report_fn: ReportFn = None, backend: str = PREVIEW_BACKEND_FAST) -> bool:
    backend = (backend or PREVIEW_BACKEND_FAST).upper().strip()

    if backend == PREVIEW_BACKEND_VSE:
        if STATE.preview_backend == PREVIEW_BACKEND_FAST or get_running_preview_backend() == PREVIEW_BACKEND_FAST:
            _stop_fast_preview(report_fn=report_fn, manual=False, silent=True)
        return vse_preview_controller.start_vse_preview(context, report_fn=report_fn)

    if backend == PREVIEW_BACKEND_FAST:
        if STATE.preview_backend == PREVIEW_BACKEND_VSE or get_running_preview_backend() == PREVIEW_BACKEND_VSE:
            vse_preview_controller.stop_vse_preview(report_fn=report_fn, manual=False)
        return _start_fast_preview(context, report_fn=report_fn)

    _report(report_fn, "WARNING", f"Unknown preview backend: {backend}")
    return False
