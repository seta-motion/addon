from __future__ import annotations

from contextlib import nullcontext
from typing import Optional, Tuple

import bpy


def all_strips(seq_editor):
    strips = getattr(seq_editor, "strips", None)
    if strips is not None:
        return strips
    return getattr(seq_editor, "sequences_all", None)


def strip_by_name(seq_editor, strip_name: str):
    if not strip_name:
        return None

    strips = all_strips(seq_editor)
    if not strips:
        return None

    getter = getattr(strips, "get", None)
    if callable(getter):
        return getter(strip_name)

    for strip in strips:
        if getattr(strip, "name", "") == strip_name:
            return strip
    return None


def capture_selection_snapshot(seq_editor) -> Tuple[Optional[str], list[str]]:
    original_active = getattr(seq_editor, "active_strip", None)
    active_name = getattr(original_active, "name", None)

    selected_names: list[str] = []
    strips = all_strips(seq_editor)
    if strips:
        for strip in strips:
            if getattr(strip, "select", False):
                selected_names.append(strip.name)

    return active_name, selected_names


def restore_selection_snapshot(seq_editor, active_name: Optional[str], selected_names: list[str]) -> None:
    strips = all_strips(seq_editor)
    if not strips:
        return

    for strip in strips:
        try:
            strip.select = False
        except Exception:
            pass

    for name in selected_names:
        strip = strip_by_name(seq_editor, name)
        if strip is not None:
            try:
                strip.select = True
            except Exception:
                pass

    if active_name:
        active_strip = strip_by_name(seq_editor, active_name)
        if active_strip is not None:
            try:
                seq_editor.active_strip = active_strip
            except Exception:
                pass


def find_sequencer_override_context(target_scene=None):
    window_manager = getattr(bpy.context, "window_manager", None)
    if not window_manager:
        return None

    fallback_override = None
    for window in window_manager.windows:
        window_scene = getattr(window, "scene", None)
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'SEQUENCE_EDITOR':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            override = {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
            }
            if target_scene is not None and window_scene == target_scene:
                return override
            if fallback_override is None:
                fallback_override = override
    return fallback_override


def reload_strip_transactional(context, strip) -> bool:
    scene = context.scene
    seq_editor = getattr(scene, "sequence_editor", None)
    if seq_editor is None or strip is None:
        return False

    active_name, selected_names = capture_selection_snapshot(seq_editor)

    try:
        strips = all_strips(seq_editor)
        if strips:
            for other in strips:
                try:
                    other.select = False
                except Exception:
                    pass

        strip.select = True
        try:
            seq_editor.active_strip = strip
        except Exception:
            pass

        override = find_sequencer_override_context(scene)
        ctx = bpy.context.temp_override(**override) if override else nullcontext()
        with ctx:
            bpy.ops.sequencer.reload()
        return True

    except Exception:
        return False

    finally:
        restore_selection_snapshot(seq_editor, active_name, selected_names)


def scale_strip_uniform(strip, factor: float) -> bool:
    if strip is None or factor <= 0:
        return False

    try:
        transform = getattr(strip, "transform", None)
        if transform is not None:
            transform.scale_x = factor
            transform.scale_y = factor
            return True
    except Exception:
        pass

    try:
        strip.scale_x = factor
        strip.scale_y = factor
        return True
    except Exception:
        return False
