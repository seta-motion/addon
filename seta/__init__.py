# __init__.py

bl_info = {
    "name": "Seta",
    "author": "David",
    "version": (0, 0, 1),
    "blender": (5, 0, 0),
    "location": "VSE > Sidebar > Seta",
    "description": "Stop motion capture inside Blender",
    "category": "Sequencer",
}

import bpy
import importlib

from . import seta_ui
from . import seta_seq
from . import device_discovery
from . import camera_manager
from . import driver_registry
from . import driver_api
from . import gphoto2_driver
from . import preview_controller
from . import vse_preview_controller
from . import shot_controller
from . import shot_mapping
from . import strip_ops
from . import image_processing
from . import process_manager
from . import sequencer_utils
from . import state
from . import sequence_extend
from . import camera_resolution


modules = (
    seta_ui,
    seta_seq,
    device_discovery,
    camera_manager,
    driver_registry,
    driver_api,
    gphoto2_driver,
    preview_controller,
    vse_preview_controller,
    shot_controller,
    shot_mapping,
    strip_ops,
    image_processing,
    process_manager,
    sequencer_utils,
    state,
    sequence_extend,
    camera_resolution,
)


def reload_modules():
    for m in modules:
        importlib.reload(m)


def enum_iso(self, context):
    choices = context.scene.get("seta_iso_choices", [])
    if not choices:
        return [("NONE", "No Data", "")]
    return [(c, c, "") for c in choices]


def enum_shutter(self, context):
    choices = context.scene.get("seta_shutter_choices", [])
    if not choices:
        return [("NONE", "No Data", "")]
    return [(c, c, "") for c in choices]


def enum_aperture(self, context):
    choices = context.scene.get("seta_aperture_choices", [])
    if not choices:
        return [("NONE", "No Data", "")]
    return [(c, c, "") for c in choices]


def enum_lens(self, context):
    choices = context.scene.get("seta_lens_choices", [])
    if not choices:
        return [("NONE", "No Data", "")]
    return [(c, c, "") for c in choices]


def _enum_mobile_setting(context, key):
    choices = context.scene.get(f"seta_mobile_{key}_choices", [])
    if not choices:
        return [("NONE", "No Data", "")]
    return [(c, c, "") for c in choices]


def enum_mobile_lens(self, context):
    return _enum_mobile_setting(context, "lens")


def enum_mobile_iso(self, context):
    return _enum_mobile_setting(context, "iso")


def enum_mobile_focus_distance_choice(self, context):
    return _enum_mobile_setting(context, "focus_distance")


def enum_mobile_exposure_time_choice(self, context):
    return _enum_mobile_setting(context, "exposure_time")


def enum_mobile_white_balance_temperature_choice(self, context):
    return _enum_mobile_setting(context, "white_balance_temperature")


def update_iso(self, context):
    if self.seta_iso != "NONE":
        camera_manager.set_setting("iso", self.seta_iso)


def update_shutter(self, context):
    if self.seta_shutter != "NONE":
        camera_manager.set_setting("shutter_speed", self.seta_shutter)


def update_aperture(self, context):
    if self.seta_aperture != "NONE":
        camera_manager.set_setting("aperture", self.seta_aperture)


def update_lens(self, context):
    if self.seta_lens != "NONE":
        camera_manager.set_setting("lens", self.seta_lens)


def _update_mobile_choice(scene, context, key, attr_name):
    from . import seta_ui

    value = str(getattr(scene, attr_name, "NONE") or "NONE")
    if value == "NONE":
        return
    seta_ui.apply_mobile_setting(context, key, value)


def _update_mobile_range(scene, context, key, attr_name):
    from . import seta_ui

    value = float(getattr(scene, attr_name, 0.0) or 0.0)
    original_value = value

    range_meta = scene.get(f"seta_mobile_{key}_range", {})
    if isinstance(range_meta, dict):
        min_value = range_meta.get("min")
        max_value = range_meta.get("max")

        if isinstance(min_value, (int, float)):
            value = max(float(min_value), value)
        if isinstance(max_value, (int, float)):
            value = min(float(max_value), value)

    if value != original_value:
        setattr(scene, attr_name, value)
        return

    seta_ui.apply_mobile_setting(context, key, value)


def update_mobile_lens(self, context):
    _update_mobile_choice(self, context, "lens", "seta_mobile_lens")


def update_mobile_iso(self, context):
    _update_mobile_choice(self, context, "iso", "seta_mobile_iso")


def update_mobile_lens_range(self, context):
    _update_mobile_range(self, context, "lens", "seta_mobile_lens_range")


def update_mobile_iso_range(self, context):
    _update_mobile_range(self, context, "iso", "seta_mobile_iso_range")


def update_mobile_focus_distance_choice(self, context):
    _update_mobile_choice(
        self, context, "focus_distance", "seta_mobile_focus_distance_choice"
    )


def update_mobile_exposure_time_choice(self, context):
    _update_mobile_choice(
        self, context, "exposure_time", "seta_mobile_exposure_time_choice"
    )


def update_mobile_white_balance_temperature_choice(self, context):
    _update_mobile_choice(
        self,
        context,
        "white_balance_temperature",
        "seta_mobile_white_balance_temperature_choice",
    )


def update_mobile_focus_distance(self, context):
    _update_mobile_range(self, context, "focus_distance", "seta_mobile_focus_distance")


def update_mobile_exposure_time(self, context):
    _update_mobile_range(self, context, "exposure_time", "seta_mobile_exposure_time")


def update_mobile_white_balance_temperature(self, context):
    _update_mobile_range(
        self,
        context,
        "white_balance_temperature",
        "seta_mobile_white_balance_temperature",
    )


def update_vse_preview_alpha(self, context):
    from . import vse_preview_controller

    scene = context.scene if context else self
    strip = vse_preview_controller.get_vse_preview_strip(scene)
    if strip is None:
        return

    try:
        strip.blend_alpha = float(scene.seta_vse_preview_alpha)
    except Exception:
        pass


class SETA_DeviceItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    device_id: bpy.props.StringProperty()
    backend: bpy.props.StringProperty()
    port: bpy.props.StringProperty(default="")
    host: bpy.props.StringProperty(default="")


def register_properties():

    bpy.utils.register_class(SETA_DeviceItem)

    bpy.types.Scene.seta_detected_devices = bpy.props.CollectionProperty(
        type=SETA_DeviceItem
    )

    bpy.types.Scene.seta_selected_device_index = bpy.props.IntProperty(default=-1)

    bpy.types.Scene.seta_connection_status = bpy.props.StringProperty(
        default="Not Connected"
    )

    bpy.types.Scene.seta_connection_mode = bpy.props.EnumProperty(
        name="Connection Mode",
        items=[
            ("USB", "USB", "Use detected USB cameras"),
            ("MOBILE", "MOBILE", "Connect to a mobile camera endpoint"),
        ],
        default="USB",
    )

    bpy.types.Scene.seta_mobile_host = bpy.props.StringProperty(
        name="Host / IP",
        default="",
    )

    bpy.types.Scene.seta_mobile_port = bpy.props.StringProperty(
        name="Port",
        default="8765",
    )

    bpy.types.Scene.seta_iso = bpy.props.EnumProperty(
        name="ISO",
        items=enum_iso,
        update=update_iso,
    )

    bpy.types.Scene.seta_shutter = bpy.props.EnumProperty(
        name="Shutter",
        items=enum_shutter,
        update=update_shutter,
    )

    bpy.types.Scene.seta_aperture = bpy.props.EnumProperty(
        name="Aperture",
        items=enum_aperture,
        update=update_aperture,
    )

    bpy.types.Scene.seta_lens = bpy.props.EnumProperty(
        name="Lens",
        items=enum_lens,
        update=update_lens,
    )

    bpy.types.Scene.seta_mobile_lens = bpy.props.EnumProperty(
        name="Mobile Lens",
        items=enum_mobile_lens,
        update=update_mobile_lens,
    )

    bpy.types.Scene.seta_mobile_iso = bpy.props.EnumProperty(
        name="Mobile ISO",
        items=enum_mobile_iso,
        update=update_mobile_iso,
    )

    bpy.types.Scene.seta_mobile_focus_distance = bpy.props.FloatProperty(
        name="Mobile Focus Distance",
        update=update_mobile_focus_distance,
    )

    bpy.types.Scene.seta_mobile_lens_range = bpy.props.FloatProperty(
        name="Mobile Lens",
        update=update_mobile_lens_range,
    )

    bpy.types.Scene.seta_mobile_iso_range = bpy.props.FloatProperty(
        name="Mobile ISO",
        update=update_mobile_iso_range,
    )

    bpy.types.Scene.seta_mobile_exposure_time = bpy.props.FloatProperty(
        name="Mobile Exposure Time",
        update=update_mobile_exposure_time,
    )

    bpy.types.Scene.seta_mobile_white_balance_temperature = bpy.props.FloatProperty(
        name="Mobile White Balance Temperature",
        update=update_mobile_white_balance_temperature,
    )

    bpy.types.Scene.seta_mobile_focus_distance_choice = bpy.props.EnumProperty(
        name="Mobile Focus Distance",
        items=enum_mobile_focus_distance_choice,
        update=update_mobile_focus_distance_choice,
    )

    bpy.types.Scene.seta_mobile_exposure_time_choice = bpy.props.EnumProperty(
        name="Mobile Exposure Time",
        items=enum_mobile_exposure_time_choice,
        update=update_mobile_exposure_time_choice,
    )

    bpy.types.Scene.seta_mobile_white_balance_temperature_choice = bpy.props.EnumProperty(
        name="Mobile White Balance Temperature",
        items=enum_mobile_white_balance_temperature_choice,
        update=update_mobile_white_balance_temperature_choice,
    )

    bpy.types.Scene.seta_directory = bpy.props.StringProperty(
        name="Stop Motion Directory",
        subtype='DIR_PATH'
    )

    bpy.types.Scene.seta_image_count = bpy.props.IntProperty(
        name="Image Count",
        description="Number of placeholder images used by Create Strip and Enlarge By (excluding 0000 mix frame)",
        default=250,
        min=1,
        max=10000,
    )

    bpy.types.Scene.seta_hold_mode = bpy.props.EnumProperty(
        name="Hold",
        items=[
            ("SINGLE", "Single", ""),
            ("TWOS", "Twos", ""),
            ("THREES", "Threes", ""),
        ],
        default="TWOS",
    )

    bpy.types.Scene.seta_auto_advance = bpy.props.BoolProperty(
        name="Auto Advance",
        description="After a successful shot, reload the strip and advance the playhead",
        default=True,
    )

    bpy.types.Scene.seta_onion_blend_mode = bpy.props.EnumProperty(
        name="Onion Blend Mode",
        items=[
            ("normal", "Mix", ""),
            ("screen", "Screen", ""),
            ("overlay", "Overlay", ""),
        ],
        default="normal",
    )

    bpy.types.Scene.seta_onion_opacity = bpy.props.FloatProperty(
        name="Onion Opacity",
        default=0.5,
        min=0.0,
        max=1.0,
    )

    bpy.types.Scene.seta_camera_native_width = bpy.props.IntProperty(
        name="Camera Native Width",
        default=0,
        min=0,
    )

    bpy.types.Scene.seta_camera_native_height = bpy.props.IntProperty(
        name="Camera Native Height",
        default=0,
        min=0,
    )

    bpy.types.Scene.seta_vse_preview_strip_name = bpy.props.StringProperty(
        name="SETA VSE Preview Strip Name",
        default="",
    )

    bpy.types.Scene.seta_vse_preview_channel = bpy.props.IntProperty(
        name="SETA VSE Preview Channel",
        default=5,
        min=1,
        max=12,
    )

    bpy.types.Scene.seta_vse_preview_width = bpy.props.IntProperty(
        name="SETA VSE Preview Width",
        default=0,
        min=0,
    )

    bpy.types.Scene.seta_vse_preview_height = bpy.props.IntProperty(
        name="SETA VSE Preview Height",
        default=0,
        min=0,
    )

    bpy.types.Scene.seta_vse_preview_alpha = bpy.props.FloatProperty(
        name="Alpha",
        default=1.0,
        min=0.0,
        max=1.0,
        update=update_vse_preview_alpha,
    )


def unregister_properties():

    del bpy.types.Scene.seta_detected_devices
    del bpy.types.Scene.seta_selected_device_index
    del bpy.types.Scene.seta_connection_status

    del bpy.types.Scene.seta_connection_mode
    del bpy.types.Scene.seta_mobile_host
    del bpy.types.Scene.seta_mobile_port

    del bpy.types.Scene.seta_iso
    del bpy.types.Scene.seta_shutter
    del bpy.types.Scene.seta_aperture
    del bpy.types.Scene.seta_lens
    del bpy.types.Scene.seta_mobile_lens
    del bpy.types.Scene.seta_mobile_iso
    del bpy.types.Scene.seta_mobile_focus_distance
    del bpy.types.Scene.seta_mobile_lens_range
    del bpy.types.Scene.seta_mobile_iso_range
    del bpy.types.Scene.seta_mobile_exposure_time
    del bpy.types.Scene.seta_mobile_white_balance_temperature
    del bpy.types.Scene.seta_mobile_focus_distance_choice
    del bpy.types.Scene.seta_mobile_exposure_time_choice
    del bpy.types.Scene.seta_mobile_white_balance_temperature_choice
    del bpy.types.Scene.seta_directory
    del bpy.types.Scene.seta_image_count
    del bpy.types.Scene.seta_hold_mode
    del bpy.types.Scene.seta_auto_advance
    del bpy.types.Scene.seta_onion_blend_mode
    del bpy.types.Scene.seta_onion_opacity
    del bpy.types.Scene.seta_camera_native_width
    del bpy.types.Scene.seta_camera_native_height
    del bpy.types.Scene.seta_vse_preview_strip_name
    del bpy.types.Scene.seta_vse_preview_channel
    del bpy.types.Scene.seta_vse_preview_width
    del bpy.types.Scene.seta_vse_preview_height
    del bpy.types.Scene.seta_vse_preview_alpha

    bpy.utils.unregister_class(SETA_DeviceItem)


def register():
    reload_modules()
    register_properties()
    seta_seq.register()
    strip_ops.register()
    seta_ui.register()


def unregister():
    seta_ui.unregister()
    strip_ops.unregister()
    seta_seq.unregister()
    unregister_properties()
