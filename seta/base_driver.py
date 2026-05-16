import re
from typing import Any, Mapping


class BaseCameraDriver:
    """Minimal contract for camera drivers discovered by SETA."""

    DRIVER_ID = ""
    DISPLAY_NAME = ""
    BACKEND = ""
    MATCH_PATTERNS = ()
    PRIORITY = 0
    IS_FALLBACK = False

    def __init__(self, connection_info=None):
        info = connection_info or {}

        if isinstance(info, Mapping):
            self.connection_info = dict(info)
            self.port = str(self.connection_info.get("port", "") or "")
            self.host = str(self.connection_info.get("host", "") or "")
        else:
            # Backward compatibility in case a driver is instantiated with a raw port.
            self.connection_info = {"port": info, "host": ""}
            self.port = str(info or "")
            self.host = ""

    @classmethod
    def get_driver_id(cls) -> str:
        return str(getattr(cls, "DRIVER_ID", "") or "").strip()

    @classmethod
    def get_display_name(cls) -> str:
        return str(getattr(cls, "DISPLAY_NAME", "") or "").strip()

    @classmethod
    def is_fallback(cls) -> bool:
        raw = getattr(cls, "IS_FALLBACK", False)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", ""}:
            return False
        raise ValueError(f"Invalid IS_FALLBACK value: {raw!r}")

    @classmethod
    def get_priority(cls) -> int:
        return int(getattr(cls, "PRIORITY", 0) or 0)

    @classmethod
    def matches_device(cls, device: Mapping[str, Any]) -> bool:
        if cls.is_fallback():
            return False

        backend = str(getattr(cls, "BACKEND", "") or "").strip().lower()
        if backend:
            device_backend = str(device.get("backend", "") or "").strip().lower()
            if backend != device_backend:
                return False

        name = str(device.get("name", "") or "")
        patterns = tuple(getattr(cls, "MATCH_PATTERNS", ()) or ())
        if not patterns:
            return False

        for pattern in patterns:
            try:
                if re.search(str(pattern), name, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue

        return False

    def connect(self):
        raise NotImplementedError

    def capture(self, output_path):
        raise NotImplementedError

    def build_preview_source_cmd(self):
        raise NotImplementedError

    def get_preview_cleanup_patterns(self):
        raise NotImplementedError

    def get_setting(self, key):
        raise NotImplementedError

    def set_setting(self, key, value):
        raise NotImplementedError

    def get_capabilities(self):
        raise NotImplementedError
