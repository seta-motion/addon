from __future__ import annotations

import os
import re
from contextlib import nullcontext
from typing import Callable, Dict, List, Optional, Tuple

import bpy

from .seta_seq import create_black_image, ensure_sequence_editor
from . import image_processing
from .sequencer_utils import find_sequencer_override_context


ReportFn = Optional[Callable[[set, str], None]]

SETA_MIX_FRAME_INDEX = 0
_NUMBERED_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<suffix>\.[^.]+)$")


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def _parse_numbered_filename(filename: str) -> Optional[Tuple[str, int, int, str]]:
    m = _NUMBERED_RE.match(filename)
    if not m:
        return None

    prefix = m.group("prefix")
    num_str = m.group("num")
    suffix = m.group("suffix")

    try:
        num = int(num_str)
    except ValueError:
        return None

    return prefix, num, len(num_str), suffix


def _get_sequence_pattern_from_strip(strip) -> Tuple[str, int, str]:
    elements = getattr(strip, "elements", None)
    if not elements:
        raise ValueError("Active strip has no image elements.")

    parsed = _parse_numbered_filename(elements[0].filename)
    if not parsed:
        raise ValueError("Could not parse strip filename pattern.")

    prefix, _num, pad, suffix = parsed
    return prefix, pad, suffix


def _list_matching_sequence_files(directory: str, prefix: str, pad: int, suffix: str) -> List[Tuple[int, str]]:
    matches: List[Tuple[int, str]] = []

    if not os.path.isdir(directory):
        return matches

    for entry in os.listdir(directory):
        parsed = _parse_numbered_filename(entry)
        if not parsed:
            continue

        e_prefix, e_num, e_pad, e_suffix = parsed
        if e_prefix != prefix or e_suffix != suffix or e_pad != pad:
            continue
        if e_num == SETA_MIX_FRAME_INDEX:
            continue

        matches.append((e_num, entry))

    matches.sort(key=lambda item: item[0])
    return matches


def _capture_attr(obj, names: List[str]) -> Dict[str, object]:
    data: Dict[str, object] = {}
    for name in names:
        if not hasattr(obj, name):
            continue
        try:
            data[name] = getattr(obj, name)
        except Exception:
            continue
    return data


def _restore_attr(obj, data: Dict[str, object]) -> None:
    for name, value in data.items():
        if not hasattr(obj, name):
            continue
        try:
            setattr(obj, name, value)
        except Exception:
            continue


def capture_strip_snapshot(strip) -> Dict[str, object]:
    snapshot: Dict[str, object] = {
        "name": getattr(strip, "name", None),
        "frame_start": int(getattr(strip, "frame_start", 0)),
        "channel": int(getattr(strip, "channel", 1)),
        "directory": bpy.path.abspath(getattr(strip, "directory", "")),
        "strip": _capture_attr(
            strip,
            [
                "blend_alpha",
                "blend_type",
                "mute",
                "lock",
                "strobe",
                "use_reverse_frames",
                "use_flip_x",
                "use_flip_y",
                "alpha_mode",
                "color_multiply",
                "animation_offset_start",
                "animation_offset_end",
                "frame_offset_start",
                "frame_offset_end",
            ],
        ),
    }

    transform = getattr(strip, "transform", None)
    if transform:
        snapshot["transform"] = _capture_attr(
            transform,
            [
                "offset_x",
                "offset_y",
                "scale_x",
                "scale_y",
                "rotation",
                "origin",
                "filter",
            ],
        )

    crop = getattr(strip, "crop", None)
    if crop:
        snapshot["crop"] = _capture_attr(
            crop,
            ["min_x", "max_x", "min_y", "max_y"],
        )

    colorspace_settings = getattr(strip, "colorspace_settings", None)
    if colorspace_settings and hasattr(colorspace_settings, "name"):
        try:
            snapshot["colorspace_name"] = colorspace_settings.name
        except Exception:
            pass

    return snapshot


def scan_valid_sequence_files(strip) -> List[Tuple[int, str]]:
    directory = bpy.path.abspath(getattr(strip, "directory", ""))
    if not directory:
        raise ValueError("Active strip has no valid directory.")

    prefix, pad, suffix = _get_sequence_pattern_from_strip(strip)
    return _list_matching_sequence_files(directory, prefix, pad, suffix)


def create_sequence_placeholders(strip, amount: int, scene) -> List[str]:
    if amount <= 0:
        return []

    directory = bpy.path.abspath(getattr(strip, "directory", ""))
    if not directory:
        raise ValueError("Active strip has no valid directory.")

    os.makedirs(directory, exist_ok=True)

    prefix, pad, suffix = _get_sequence_pattern_from_strip(strip)
    existing = _list_matching_sequence_files(directory, prefix, pad, suffix)
    last_index = existing[-1][0] if existing else 0

    width, height = image_processing.get_effective_render_size(scene)

    created: List[str] = []
    for seq_num in range(last_index + 1, last_index + amount + 1):
        filename = f"{prefix}{seq_num:0{pad}d}{suffix}"
        filepath = os.path.join(directory, filename)
        if os.path.exists(filepath):
            continue
        create_black_image(filepath, width, height)
        created.append(filename)

    return created


def _restore_snapshot(new_strip, snapshot: Dict[str, object]) -> None:
    name = snapshot.get("name")
    if name:
        try:
            new_strip.name = name
        except Exception:
            pass

    _restore_attr(new_strip, snapshot.get("strip", {}))

    transform = getattr(new_strip, "transform", None)
    if transform:
        _restore_attr(transform, snapshot.get("transform", {}))

    crop = getattr(new_strip, "crop", None)
    if crop:
        _restore_attr(crop, snapshot.get("crop", {}))

    colorspace_name = snapshot.get("colorspace_name")
    colorspace_settings = getattr(new_strip, "colorspace_settings", None)
    if colorspace_name and colorspace_settings and hasattr(colorspace_settings, "name"):
        try:
            colorspace_settings.name = colorspace_name
        except Exception:
            pass


def rebuild_strip_from_snapshot(context, old_strip, snapshot: Dict[str, object], files: List[str], report_fn: ReportFn = None):
    if not files:
        raise ValueError("No valid sequence files found to rebuild the strip.")

    scene = context.scene
    ensure_sequence_editor(scene)

    directory = snapshot["directory"]
    frame_start = int(snapshot["frame_start"])
    channel = int(snapshot["channel"])

    seq_editor = scene.sequence_editor
    if not seq_editor:
        raise ValueError("Could not access sequence editor.")

    old_name = getattr(old_strip, "name", None)

    try:
        seq_editor.strips.remove(old_strip)
    except Exception as e:
        raise RuntimeError(f"Could not remove original strip: {e}") from e

    try:
        override = find_sequencer_override_context(scene)
        ctx = bpy.context.temp_override(**override) if override else nullcontext()
        with ctx:
            bpy.ops.sequencer.image_strip_add(
                directory=directory,
                files=[{"name": name} for name in files],
                frame_start=frame_start,
                channel=channel,
                move_strips=False,
            )

        new_strip = getattr(scene.sequence_editor, "active_strip", None)
        if not new_strip:
            raise RuntimeError("Could not create rebuilt strip.")

        _restore_snapshot(new_strip, snapshot)

        try:
            new_strip.select = True
            scene.sequence_editor.active_strip = new_strip
        except Exception:
            pass

        return new_strip

    except Exception as e:
        rollback_error = None

        try:
            override = find_sequencer_override_context(scene)
            ctx = bpy.context.temp_override(**override) if override else nullcontext()
            with ctx:
                bpy.ops.sequencer.image_strip_add(
                    directory=directory,
                    files=[{"name": name} for name in files[:1]],
                    frame_start=frame_start,
                    channel=channel,
                    move_strips=False,
                )
            rollback_strip = getattr(scene.sequence_editor, "active_strip", None)
            if rollback_strip:
                if old_name:
                    try:
                        rollback_strip.name = old_name
                    except Exception:
                        pass
                _restore_snapshot(rollback_strip, snapshot)
                _report(report_fn, "WARNING", "Strip rebuild failed; restored a fallback strip from first frame.")
        except Exception as rollback_ex:
            rollback_error = rollback_ex

        if rollback_error:
            raise RuntimeError(
                f"Could not rebuild strip ({e}). Rollback also failed ({rollback_error})."
            ) from e

        raise RuntimeError(f"Could not rebuild strip: {e}") from e


def extend_active_strip(context, amount: int, report_fn: ReportFn = None):
    if amount <= 0:
        raise ValueError("Image Count must be greater than zero.")

    from . import shot_mapping

    strip = shot_mapping.get_active_image_strip(context)
    if not strip:
        raise ValueError("No valid active IMAGE strip selected.")

    snapshot = capture_strip_snapshot(strip)
    created = create_sequence_placeholders(strip, amount, context.scene)
    valid_files = scan_valid_sequence_files(strip)
    ordered_files = [filename for _idx, filename in valid_files]

    if not ordered_files:
        raise ValueError("No valid sequence files found for the active strip.")

    new_strip = rebuild_strip_from_snapshot(context, strip, snapshot, ordered_files, report_fn=report_fn)

    created_count = len(created)
    final_count = len(ordered_files)
    _report(
        report_fn,
        "INFO",
        f"Strip enlarged by {created_count} image(s). New total: {final_count}.",
    )
    return new_strip
