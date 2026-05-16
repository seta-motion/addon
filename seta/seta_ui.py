# seta_ui.py

import bpy
from bpy.types import Panel, Operator, UIList

from .state import PREVIEW_BACKEND_FAST, PREVIEW_BACKEND_VSE

MOBILE_UI_KEYS = (
    "lens",
    "focus_distance",
    "iso",
    "exposure_time",
    "white_balance_temperature",
)
_MOBILE_UI_SYNC_GUARD = False


def _is_mobile_http_active(scene) -> bool:
    from . import camera_manager

    if str(getattr(scene, "seta_connection_mode", "USB") or "USB") != "MOBILE":
        return False
    capabilities = camera_manager.get_capabilities() or {}
    backend = str(capabilities.get("backend", "") or "").strip().lower()
    driver_id = str(capabilities.get("driver_id", "") or "").strip().lower()
    return backend == "mobile_http" or driver_id == "mobile_http"


def clear_mobile_ui_state(scene):
    scene["seta_mobile_supported_settings"] = []
    scene["seta_mobile_settings_meta"] = {}
    for key in MOBILE_UI_KEYS:
        scene[f"seta_mobile_{key}_choices"] = []
        scene[f"seta_mobile_{key}_range"] = {}


def sync_mobile_ui_settings(scene, context=None):
    from . import camera_manager

    global _MOBILE_UI_SYNC_GUARD

    if _MOBILE_UI_SYNC_GUARD:
        return
    if not _is_mobile_http_active(scene):
        clear_mobile_ui_state(scene)
        return

    _MOBILE_UI_SYNC_GUARD = True
    try:
        capabilities = camera_manager.get_capabilities() or {}
        supported_settings = set(capabilities.get("settings") or capabilities.get("supported_settings") or [])
        scene["seta_mobile_supported_settings"] = [k for k in MOBILE_UI_KEYS if k in supported_settings]

        mobile_meta = {}
        for key in MOBILE_UI_KEYS:
            scene[f"seta_mobile_{key}_choices"] = []
            scene[f"seta_mobile_{key}_range"] = {}
            if key not in supported_settings:
                continue

            setting = camera_manager.get_setting(key) or {}
            setting_type = str(setting.get("type", "") or "").strip().lower()
            if setting_type not in {"choice", "range"}:
                continue

            current = setting.get("current")
            meta = {"type": setting_type}
            if setting_type == "choice":
                choices = [str(c or "").strip() for c in (setting.get("choices") or []) if str(c or "").strip()]
                scene[f"seta_mobile_{key}_choices"] = choices
                meta["choices"] = choices
                if current in choices:
                    if key == "lens":
                        scene.seta_mobile_lens = current
                    elif key == "iso":
                        scene.seta_mobile_iso = current
                    elif key == "focus_distance":
                        scene.seta_mobile_focus_distance_choice = current
                    elif key == "exposure_time":
                        scene.seta_mobile_exposure_time_choice = current
                    elif key == "white_balance_temperature":
                        scene.seta_mobile_white_balance_temperature_choice = current
            elif setting_type == "range":
                min_value = setting.get("min")
                max_value = setting.get("max")
                range_meta = {}
                if isinstance(min_value, (int, float)):
                    range_meta["min"] = float(min_value)
                if isinstance(max_value, (int, float)):
                    range_meta["max"] = float(max_value)
                scene[f"seta_mobile_{key}_range"] = range_meta
                meta.update(range_meta)
                try:
                    current_value = float(current)
                except Exception:
                    continue
                if key == "lens":
                    scene.seta_mobile_lens_range = current_value
                elif key == "iso":
                    scene.seta_mobile_iso_range = current_value
                elif key == "focus_distance":
                    scene.seta_mobile_focus_distance = current_value
                elif key == "exposure_time":
                    scene.seta_mobile_exposure_time = current_value
                elif key == "white_balance_temperature":
                    scene.seta_mobile_white_balance_temperature = current_value
            meta["current"] = current
            mobile_meta[key] = meta

        scene["seta_mobile_settings_meta"] = mobile_meta
    finally:
        _MOBILE_UI_SYNC_GUARD = False


def apply_mobile_setting(context, key: str, value):
    from . import camera_manager

    scene = context.scene if context else bpy.context.scene
    if _MOBILE_UI_SYNC_GUARD:
        return
    if not _is_mobile_http_active(scene):
        return

    ok = camera_manager.set_setting(key, value)
    sync_mobile_ui_settings(scene, context=context)
    return ok


def _has_valid_active_image_strip(context) -> bool:
    from . import shot_mapping
    return shot_mapping.has_valid_active_image_strip(context)


class SETA_UL_DeviceList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon='CAMERA_DATA')


class SETA_OT_DetectCameras(Operator):
    bl_idname = "seta.detect_cameras"
    bl_label = "Detect Cameras"

    def execute(self, context):
        from . import device_discovery

        scene = context.scene
        scene.seta_detected_devices.clear()

        devices = device_discovery.detect_all()

        for dev in devices:
            item = scene.seta_detected_devices.add()
            item.name = dev.get("name", "Unknown")
            item.device_id = dev.get("device_id", "")
            item.backend = dev.get("backend", "")
            item.port = dev.get("port", "")
            item.host = dev.get("host", "")

        if devices:
            scene.seta_selected_device_index = 0
            scene.seta_connection_status = "Devices detected"
        else:
            scene.seta_selected_device_index = -1
            scene.seta_connection_status = "No devices found"

        return {'FINISHED'}


class SETA_OT_ConnectCamera(Operator):
    bl_idname = "seta.connect_camera"
    bl_label = "Connect"

    def execute(self, context):
        from . import camera_manager

        scene = context.scene
        mode = str(getattr(scene, "seta_connection_mode", "USB") or "USB")

        if mode == "MOBILE":
            host = str(getattr(scene, "seta_mobile_host", "") or "").strip()
            port = str(getattr(scene, "seta_mobile_port", "") or "").strip()
            backend = "mobile_http"

            if not host or not port:
                scene.seta_connection_status = "Mobile host and port are required"
                self.report({'ERROR'}, "Mobile host and port are required")
                return {'CANCELLED'}

            device = {
                "name": f"SETA Mobile ({host}:{port})",
                "device_id": f"{backend}://{host}:{port}",
                "backend": backend,
                "host": host,
                "port": port,
            }
        else:
            idx = scene.seta_selected_device_index
            if idx < 0 or idx >= len(scene.seta_detected_devices):
                scene.seta_connection_status = "No USB device selected"
                self.report({'ERROR'}, "No USB device selected")
                return {'CANCELLED'}
            device = scene.seta_detected_devices[idx]

        success = camera_manager.connect(device)

        if not success:
            scene.seta_connection_status = "Connection failed"
            scene.seta_camera_native_width = 0
            scene.seta_camera_native_height = 0
            clear_mobile_ui_state(scene)
            scene["seta_iso_choices"] = []
            scene["seta_shutter_choices"] = []
            scene["seta_aperture_choices"] = []
            scene["seta_lens_choices"] = []
            return {'CANCELLED'}

        device_name = device.get("name", "") if isinstance(device, dict) else device.name
        scene.seta_connection_status = f"Connected: {device_name}"
        scene.seta_camera_native_width = 0
        scene.seta_camera_native_height = 0

        capabilities = camera_manager.get_capabilities() or {}
        supported_settings = set(capabilities.get("settings") or capabilities.get("supported_settings") or [])

        scene["seta_iso_choices"] = []
        scene["seta_shutter_choices"] = []
        scene["seta_aperture_choices"] = []
        scene["seta_lens_choices"] = []

        if _is_mobile_http_active(scene):
            scene["seta_iso_choices"] = []
            scene["seta_shutter_choices"] = []
            scene["seta_aperture_choices"] = []
            scene["seta_lens_choices"] = []
            sync_mobile_ui_settings(scene, context=context)
        else:
            clear_mobile_ui_state(scene)
            if "iso" in supported_settings:
                iso = camera_manager.get_setting("iso")
                scene["seta_iso_choices"] = iso["choices"] if iso else []
                if iso and iso["current"] in iso["choices"]:
                    scene.seta_iso = iso["current"]

            if "shutter_speed" in supported_settings:
                shutter = camera_manager.get_setting("shutter_speed")
                scene["seta_shutter_choices"] = shutter["choices"] if shutter else []
                if shutter and shutter["current"] in shutter["choices"]:
                    scene.seta_shutter = shutter["current"]

            if "aperture" in supported_settings:
                aperture = camera_manager.get_setting("aperture")
                scene["seta_aperture_choices"] = aperture["choices"] if aperture else []
                if aperture and aperture["current"] in aperture["choices"]:
                    scene.seta_aperture = aperture["current"]

            if "lens" in supported_settings:
                lens = camera_manager.get_setting("lens")
                scene["seta_lens_choices"] = lens["choices"] if lens else []
                if lens and lens["current"] in lens["choices"]:
                    scene.seta_lens = lens["current"]

        return {'FINISHED'}


class SETA_OT_ApplyCameraResolutionScale(Operator):
    bl_idname = "seta.apply_camera_resolution_scale"
    bl_label = "Apply Camera Resolution Scale"

    scale_factor: bpy.props.FloatProperty(default=1.0)

    def execute(self, context):
        from . import camera_resolution
        ok = camera_resolution.apply_camera_resolution_scale(
            context,
            self.scale_factor,
            report_fn=self.report,
        )
        return {'FINISHED'} if ok else {'CANCELLED'}


class SETA_OT_Preview(Operator):
    bl_idname = "seta.preview"
    bl_label = "Preview"

    def execute(self, context):
        from . import preview_controller
        ok = preview_controller.start_preview(
            context,
            report_fn=self.report,
            backend=PREVIEW_BACKEND_FAST,
        )
        return {'FINISHED'} if ok else {'CANCELLED'}


class SETA_OT_VSEPreview(Operator):
    bl_idname = "seta.vse_preview"
    bl_label = "VSE Preview"

    def execute(self, context):
        from . import preview_controller
        ok = preview_controller.start_preview(
            context,
            report_fn=self.report,
            backend=PREVIEW_BACKEND_VSE,
        )
        return {'FINISHED'} if ok else {'CANCELLED'}


class SETA_OT_StopPreview(Operator):
    bl_idname = "seta.stop_preview"
    bl_label = "Stop Preview"

    def execute(self, context):
        from . import preview_controller
        preview_controller.stop_preview(report_fn=self.report, manual=True)
        return {'FINISHED'}


class SETA_OT_RefreshPreview(Operator):
    bl_idname = "seta.refresh_preview"
    bl_label = "Refresh Preview"

    def execute(self, context):
        from . import preview_controller
        preview_controller.refresh_preview(context, report_fn=self.report)
        return {'FINISHED'}


class SETA_OT_ScaleVSEPreviewToRender(Operator):
    bl_idname = "seta.scale_vse_preview_to_render"
    bl_label = "Match Render Width"

    def execute(self, context):
        from . import image_processing
        from . import sequencer_utils
        from . import vse_preview_controller

        scene = context.scene
        strip = vse_preview_controller.get_vse_preview_strip(scene)
        if strip is None:
            self.report({'ERROR'}, "VSE preview strip not found.")
            return {'CANCELLED'}

        preview_w = int(getattr(scene, "seta_vse_preview_width", 0) or 0)
        if preview_w <= 0:
            self.report({'ERROR'}, "VSE preview width not measured yet.")
            return {'CANCELLED'}

        render_w, _ = image_processing.get_effective_render_size(scene)
        if render_w <= 0:
            self.report({'ERROR'}, "Invalid render width.")
            return {'CANCELLED'}

        factor = float(render_w) / float(preview_w)
        if not sequencer_utils.scale_strip_uniform(strip, factor):
            self.report({'ERROR'}, "Could not scale VSE preview strip.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Applied scale factor {factor:.4f}.")
        return {'FINISHED'}


class SETA_OT_Shot(Operator):
    bl_idname = "seta.shot"
    bl_label = "Shot"

    def execute(self, context):
        from . import shot_controller
        ok = shot_controller.take_shot_provisional(context, report_fn=self.report)
        return {'FINISHED'} if ok else {'CANCELLED'}


class SETA_OT_TestShot(Operator):
    bl_idname = "seta.test_shot"
    bl_label = "Test Shot"

    def execute(self, context):
        from . import shot_controller
        ok = shot_controller.take_test_shot(context, report_fn=self.report)
        return {'FINISHED'} if ok else {'CANCELLED'}


class SETA_PT_MainPanel(Panel):
    bl_label = "Seta"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Seta"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        from . import camera_manager
        has_active_driver = camera_manager.get_active_driver() is not None

        box = layout.box()
        box.label(text="Camera Connection")
        box.prop(scene, "seta_connection_mode", text="Mode (USB/Mobile)")

        if scene.seta_connection_mode == "USB":
            usb_box = box.box()
            usb_box.label(text="Camera Detection")
            usb_box.operator("seta.detect_cameras")
            usb_box.template_list(
                "SETA_UL_DeviceList",
                "",
                scene,
                "seta_detected_devices",
                scene,
                "seta_selected_device_index",
                rows=3,
            )
        else:
            mobile_box = box.box()
            mobile_box.label(text="Mobile Connection")
            mobile_box.prop(scene, "seta_mobile_host")
            mobile_box.prop(scene, "seta_mobile_port")

        box.operator("seta.connect_camera")
        test_shot_row = box.row()
        test_shot_row.enabled = has_active_driver
        test_shot_row.operator("seta.test_shot")

        layout.label(text=f"Status: {scene.seta_connection_status}")

        box = layout.box()
        box.label(text="Camera Settings")
        is_mobile_active = _is_mobile_http_active(scene)

        if is_mobile_active:
            mobile_meta = scene.get("seta_mobile_settings_meta", {})
            mobile_box = box.box()
            mobile_box.label(text="Mobile Settings")

            for key in MOBILE_UI_KEYS:
                meta = mobile_meta.get(key)
                if not meta:
                    continue
                setting_type = meta.get("type")
                label = key.replace("_", " ").title()
                if setting_type == "choice":
                    if key == "lens":
                        mobile_box.prop(scene, "seta_mobile_lens", text=label)
                    elif key == "iso":
                        mobile_box.prop(scene, "seta_mobile_iso", text=label)
                    elif key == "focus_distance":
                        mobile_box.prop(scene, "seta_mobile_focus_distance_choice", text=label)
                    elif key == "exposure_time":
                        mobile_box.prop(scene, "seta_mobile_exposure_time_choice", text=label)
                    elif key == "white_balance_temperature":
                        mobile_box.prop(scene, "seta_mobile_white_balance_temperature_choice", text=label)
                elif setting_type == "range":
                    if key == "lens":
                        mobile_box.prop(scene, "seta_mobile_lens_range", text=label)
                    elif key == "iso":
                        mobile_box.prop(scene, "seta_mobile_iso_range", text=label)
                    elif key == "focus_distance":
                        mobile_box.prop(scene, "seta_mobile_focus_distance", text=label)
                    elif key == "exposure_time":
                        mobile_box.prop(scene, "seta_mobile_exposure_time", text=label)
                    elif key == "white_balance_temperature":
                        mobile_box.prop(scene, "seta_mobile_white_balance_temperature", text=label)

                    range_meta = scene.get(f"seta_mobile_{key}_range", {})
                    if isinstance(range_meta, dict):
                        min_value = range_meta.get("min")
                        max_value = range_meta.get("max")
                        has_min = isinstance(min_value, (int, float))
                        has_max = isinstance(max_value, (int, float))
                        if has_min and has_max:
                            mobile_box.label(
                                text=f"Range: {float(min_value)} - {float(max_value)}"
                            )
                        elif has_min:
                            mobile_box.label(text=f"Range: min {float(min_value)}")
                        elif has_max:
                            mobile_box.label(text=f"Range: max {float(max_value)}")
        else:
            if scene.get("seta_iso_choices"):
                box.prop(scene, "seta_iso")

            if scene.get("seta_shutter_choices"):
                box.prop(scene, "seta_shutter")

            if scene.get("seta_aperture_choices"):
                box.prop(scene, "seta_aperture")

            if scene.get("seta_lens_choices"):
                box.prop(scene, "seta_lens")

        box = layout.box()
        box.label(text="Stop Motion Sequence")
        box.prop(scene, "seta_directory")

        action_row = box.row(align=True)
        op = action_row.operator("seta.create_strip", text="Create Strip")
        op.directory = scene.seta_directory

        enlarge_row = action_row.row(align=True)
        enlarge_row.enabled = _has_valid_active_image_strip(context)
        enlarge_row.operator("seta.enlarge_active_strip", text="Enlarge By")

        box.prop(scene, "seta_image_count")

        reload_row = box.row()
        reload_row.enabled = _has_valid_active_image_strip(context)
        reload_row.operator("seta.reload_selected_strip", text="Reload Selected Strip")

        box = layout.box()
        box.label(text="Capture Hold")
        box.prop(scene, "seta_hold_mode", expand=True)
        box.prop(scene, "seta_auto_advance")

        box = layout.box()
        box.label(text="Live View")

        preview_box = box.box()
        preview_box.label(text="Preview")

        preview_actions = preview_box.row(align=True)
        preview_actions.operator("seta.preview", text="Launch")
        preview_actions.operator("seta.stop_preview", text="Stop")

        preview_box.prop(scene, "seta_onion_blend_mode")

        onion_row = preview_box.row(align=True)
        onion_row.prop(scene, "seta_onion_opacity")
        onion_row.operator("seta.refresh_preview", text="", icon='FILE_REFRESH')

        vse_box = box.box()
        vse_box.label(text="VSE Preview")

        vse_actions = vse_box.row(align=True)
        vse_actions.operator("seta.vse_preview", text="Launch")
        vse_actions.operator("seta.stop_preview", text="Stop")

        from . import image_processing
        preview_w = int(getattr(scene, "seta_vse_preview_width", 0) or 0)
        preview_h = int(getattr(scene, "seta_vse_preview_height", 0) or 0)
        if preview_w > 0 and preview_h > 0:
            render_w, render_h = image_processing.get_effective_render_size(scene)
            vse_box.label(text=f"VSE Preview: {preview_w} x {preview_h}")
            vse_box.label(text=f"Render: {render_w} x {render_h}")
        else:
            vse_box.label(text="VSE Preview: not measured yet")

        vse_box.operator("seta.scale_vse_preview_to_render", text="Match Render Width")
        vse_box.prop(scene, "seta_vse_preview_alpha")

        native_box = layout.box()
        native_box.label(text="Camera Aspect Ratio")

        native_row = native_box.row(align=True)
        native_row.enabled = has_active_driver

        op = native_row.operator("seta.apply_camera_resolution_scale", text="100%")
        op.scale_factor = 1.0
        op = native_row.operator("seta.apply_camera_resolution_scale", text="50%")
        op.scale_factor = 0.5
        op = native_row.operator("seta.apply_camera_resolution_scale", text="25%")
        op.scale_factor = 0.25

        native_w = int(getattr(scene, "seta_camera_native_width", 0) or 0)
        native_h = int(getattr(scene, "seta_camera_native_height", 0) or 0)
        if native_w > 0 and native_h > 0:
            native_box.label(text=f"Native: {native_w} x {native_h}")
        else:
            native_box.label(text="Native: not measured yet")

        shot_row = box.row()
        shot_row.enabled = _has_valid_active_image_strip(context)
        shot_row.operator("seta.shot", text="Shot")


classes = (
    SETA_UL_DeviceList,
    SETA_OT_DetectCameras,
    SETA_OT_ConnectCamera,
    SETA_OT_ApplyCameraResolutionScale,
    SETA_OT_Preview,
    SETA_OT_VSEPreview,
    SETA_OT_StopPreview,
    SETA_OT_RefreshPreview,
    SETA_OT_ScaleVSEPreviewToRender,
    SETA_OT_Shot,
    SETA_OT_TestShot,
    SETA_PT_MainPanel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
