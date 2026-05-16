# shot_mapping.py

from __future__ import annotations

import os
import re
from typing import Optional, Tuple, List

import bpy


_NUMBERED_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<suffix>\.[^.]+)$")


def _get_active_strip(context) -> Optional[bpy.types.Sequence]:
    seq = context.scene.sequence_editor
    if not seq:
        return None
    return getattr(seq, "active_strip", None)


def get_active_image_strip(context) -> Optional[bpy.types.Sequence]:
    strip = _get_active_strip(context)
    if not strip:
        return None
    if getattr(strip, "type", None) != "IMAGE":
        return None

    elements = getattr(strip, "elements", None)
    directory = getattr(strip, "directory", None)
    if not elements or not directory:
        return None

    base_name = elements[0].filename
    if not base_name:
        return None

    if _NUMBERED_RE.match(base_name) is None:
        return None

    return strip


def has_valid_active_image_strip(context) -> bool:
    return get_active_image_strip(context) is not None


def _parse_numbered_filename(filename: str) -> Optional[Tuple[str, int, int, str]]:
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


def get_hold_count(hold_mode: str) -> int:
    if hold_mode == "SINGLE":
        return 1
    if hold_mode == "THREES":
        return 3
    return 2


def extend_targets_with_next_frame(targets: List[str]) -> List[str]:
    if not targets:
        return targets

    last_target = targets[-1]
    directory = os.path.dirname(last_target)
    basename = os.path.basename(last_target)

    parsed = _parse_numbered_filename(basename)
    if not parsed:
        return targets

    prefix, num, pad, suffix = parsed
    next_filename = f"{prefix}{num + 1:0{pad}d}{suffix}"
    next_target = os.path.join(directory, next_filename)

    return [*targets, next_target]


def resolve_capture_targets(context, hold_mode: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Resolve concrete file paths to write for the current shot.

    Agreed rules:
    - requires active IMAGE strip
    - numbering comes from the strip's first filename
    - playhead may be anywhere inside the strip's CURRENT visible range
      or at most 1 frame ahead of its current visible end
    - target count depends on hold mode:
        SINGLE = 1
        TWOS   = 2
        THREES = 3

    Important distinction:
    - validation of playhead range uses the strip's visible timeline range
      (frame_final_start / frame_final_end)
    - filename numbering still uses the strip's logical start (frame_start)
      plus the parsed base filename
    """
    strip = get_active_image_strip(context)
    if not strip:
        return None, "No valid active IMAGE strip selected."

    elements = getattr(strip, "elements", None)
    directory = getattr(strip, "directory", None)

    base_name = elements[0].filename
    parsed = _parse_numbered_filename(base_name)
    if not parsed:
        return None, "Could not parse strip filename pattern."

    prefix, base_num, pad, suffix = parsed
    dir_abs = bpy.path.abspath(directory)

    scene = context.scene
    current_frame = int(scene.frame_current)

    # Visible strip range right now.
    # frame_final_end is end-exclusive, so last visible frame is end - 1.
    visible_start = int(getattr(strip, "frame_final_start", getattr(strip, "frame_start", 0)))
    visible_end_exclusive = int(getattr(strip, "frame_final_end", visible_start + len(elements)))
    visible_last_frame = visible_end_exclusive - 1

    # Allowed:
    # - anywhere on the strip
    # - or at most 1 frame ahead of the current visible end
    if current_frame < visible_start or current_frame > (visible_last_frame + 1):
        return None, "Out of strip range."

    # Logical numbering anchor:
    logical_start = int(getattr(strip, "frame_start", 0))
    logical_offset = current_frame - logical_start

    target_base_num = base_num + logical_offset
    count = get_hold_count(hold_mode)

    targets: List[str] = []
    for i in range(count):
        seq_num = target_base_num + i
        filename = f"{prefix}{seq_num:0{pad}d}{suffix}"
        targets.append(os.path.join(dir_abs, filename))

    return targets, None
