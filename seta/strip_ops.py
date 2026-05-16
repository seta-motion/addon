# strip_ops.py

from __future__ import annotations

from typing import Callable, Optional

import bpy

from . import shot_mapping
from . import sequence_extend
from . import sequencer_utils


ReportFn = Optional[Callable[[set, str], None]]


def _report(report_fn: ReportFn, level: str, msg: str) -> None:
    if not report_fn:
        return
    level = level.upper().strip()
    if level not in {"INFO", "WARNING", "ERROR"}:
        level = "INFO"
    report_fn({level}, msg)


def get_active_image_strip(context):
    return shot_mapping.get_active_image_strip(context)


def ensure_strip_covers_current_shot(context, hold_count: int) -> bool:
    """
    The strip is now created at its real full sequence length from the start.

    We keep this helper because shot_controller already calls it, but for now it
    does not extend or shrink anything. The strip length is treated as fixed.

    Returns True as long as a valid active IMAGE strip exists.
    """
    strip = get_active_image_strip(context)
    return strip is not None


def reload_active_strip(context, report_fn: ReportFn = None) -> bool:
    """
    Refresh the selected strip only.
    Does not move playhead.
    Does not touch preview.
    """
    strip = get_active_image_strip(context)
    if not strip:
        _report(report_fn, "WARNING", "No valid active IMAGE strip selected.")
        return False

    ok = sequencer_utils.reload_strip_transactional(context, strip)
    if ok:
        return True

    _report(report_fn, "WARNING", "Strip reload failed.")
    return False


class SETA_OT_ReloadSelectedStrip(bpy.types.Operator):
    bl_idname = "seta.reload_selected_strip"
    bl_label = "Reload Selected Strip"
    bl_description = "Reload the active selected image strip"

    def execute(self, context):
        strip = get_active_image_strip(context)
        if not strip:
            self.report({'WARNING'}, "No valid active IMAGE strip selected.")
            return {'CANCELLED'}

        ok = reload_active_strip(context, report_fn=self.report)
        if ok:
            self.report({'INFO'}, "Selected strip reloaded.")
            return {'FINISHED'}

        return {'CANCELLED'}


class SETA_OT_EnlargeActiveStrip(bpy.types.Operator):
    bl_idname = "seta.enlarge_active_strip"
    bl_label = "Enlarge By"
    bl_description = "Extend the active image strip by the current Image Count"

    def execute(self, context):
        amount = int(getattr(context.scene, "seta_image_count", 0))

        try:
            sequence_extend.extend_active_strip(context, amount, report_fn=self.report)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        return {'FINISHED'}


classes = (
    SETA_OT_ReloadSelectedStrip,
    SETA_OT_EnlargeActiveStrip,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)