# drivers/canon_eos_3000d_4000d.py

from ..driver_api import GPhoto2CameraDriver


class CanonEOS3000D4000D(GPhoto2CameraDriver):
    DRIVER_ID = "canon_eos_3000d_4000d"
    DISPLAY_NAME = "Canon EOS 3000D / 4000D"
    BACKEND = "gphoto2"
    PRIORITY = 100
    IS_FALLBACK = False
    MATCH_PATTERNS = (
        r"canon.*(3000d|4000d)|(3000d|4000d).*canon",
    )

    SETTING_KEY_TO_PATH = {
        "iso": "/main/imgsettings/iso",
        "shutter_speed": "/main/capturesettings/shutterspeed",
        "aperture": "/main/capturesettings/aperture",
    }
    SUPPORTED_SETTINGS = ["iso", "shutter_speed", "aperture"]
    PREVIEW_VIEWFINDER_VALUE = "viewfinder=1"
    PREVIEW_CLEANUP_REGEX = r"gphoto2 .*--set-config viewfinder=1 .*--capture-movie .*--stdout"
