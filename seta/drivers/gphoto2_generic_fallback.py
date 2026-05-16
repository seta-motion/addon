# drivers/gphoto2_generic_fallback.py

from ..driver_api import GPhoto2CameraDriver


class GenericGPhoto2FallbackDriver(GPhoto2CameraDriver):
    DRIVER_ID = "gphoto2_generic_fallback"
    DISPLAY_NAME = "Generic gphoto2 fallback"
    BACKEND = "gphoto2"
    PRIORITY = 10
    IS_FALLBACK = True
    MATCH_PATTERNS = ()

    SETTING_KEY_TO_PATH = {}
    SUPPORTED_SETTINGS = []
    PREVIEW_VIEWFINDER_VALUE = "viewfinder=1"
