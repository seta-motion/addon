from __future__ import annotations

import logging
import re
import subprocess
from typing import Dict, List, Optional

from .base_driver import BaseCameraDriver


LOGGER = logging.getLogger(__name__)


class GPhoto2CameraDriver(BaseCameraDriver):
    BACKEND = "gphoto2"
    PREVIEW_VIEWFINDER_VALUE = "viewfinder=1"
    PREVIEW_CLEANUP_REGEX = r"gphoto2 .*--capture-movie .*--stdout"
    SETTING_KEY_TO_PATH: Dict[str, str] = {}
    SUPPORTED_SETTINGS: List[str] = []

    def __init__(self, connection_info=None):
        super().__init__(connection_info=connection_info)

    def _port_args(self):
        if self.port:
            return ["--port", self.port]
        return []

    def _resolve_config_path(self, key: str) -> Optional[str]:
        return self.SETTING_KEY_TO_PATH.get(key)

    def connect(self):
        try:
            result = subprocess.run(
                ["gphoto2", *self._port_args(), "--summary"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode == 0:
                LOGGER.info("%s connected (%s)", self.get_driver_id(), self.port or "auto-detect")
                return True

            LOGGER.warning("%s connection error: %s", self.get_driver_id(), result.stderr)
            return False
        except Exception:
            LOGGER.exception("%s connection exception", self.get_driver_id())
            return False

    def capture(self, output_path):
        try:
            result = subprocess.run(
                [
                    "gphoto2",
                    *self._port_args(),
                    "--capture-image-and-download",
                    "--filename",
                    output_path,
                    "--force-overwrite",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if result.returncode == 0:
                LOGGER.info("%s image captured: %s", self.get_driver_id(), output_path)
                return True

            LOGGER.warning("%s capture error: %s", self.get_driver_id(), result.stderr)
            return False
        except Exception:
            LOGGER.exception("%s capture exception", self.get_driver_id())
            return False

    def build_preview_source_cmd(self):
        return [
            "gphoto2",
            *self._port_args(),
            "--set-config",
            self.PREVIEW_VIEWFINDER_VALUE,
            "--capture-movie",
            "--stdout",
        ]

    def get_preview_cleanup_patterns(self):
        return [self.PREVIEW_CLEANUP_REGEX]

    def get_setting(self, key):
        config_path = self._resolve_config_path(key)
        if not config_path:
            return None

        try:
            result = subprocess.run(
                ["gphoto2", *self._port_args(), "--get-config", config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if result.returncode != 0:
                LOGGER.warning("%s read config error: %s", self.get_driver_id(), result.stderr)
                return None

            return self._parse_config_output(result.stdout)
        except Exception:
            LOGGER.exception("%s get_setting exception", self.get_driver_id())
            return None

    def set_setting(self, key, value):
        config_path = self._resolve_config_path(key)
        if not config_path:
            return False

        try:
            result = subprocess.run(
                [
                    "gphoto2",
                    *self._port_args(),
                    "--set-config",
                    f"{config_path}={value}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if result.returncode == 0:
                LOGGER.info("%s set %s -> %s", self.get_driver_id(), key, value)
                return True

            LOGGER.warning("%s set config error: %s", self.get_driver_id(), result.stderr)
            return False
        except Exception:
            LOGGER.exception("%s set_setting exception", self.get_driver_id())
            return False

    def _parse_config_output(self, text):
        lines = text.splitlines()
        current = None
        choices = []

        for line in lines:
            line = line.strip()

            if line.startswith("Current:"):
                current = line.replace("Current:", "").strip()

            if line.startswith("Choice:"):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    choices.append(parts[2].strip())

        return {"current": current, "choices": choices}

    def get_capabilities(self):
        settings = list(self.SUPPORTED_SETTINGS or self.SETTING_KEY_TO_PATH.keys())
        return {
            "backend": self.BACKEND,
            "driver_id": self.get_driver_id(),
            "driver_name": self.get_display_name(),
            "supports_capture": True,
            "supports_preview": True,
            "settings": settings,
            "supported_settings": settings,
        }
