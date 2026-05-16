#camera_manager.py

from __future__ import annotations

import logging
from typing import Mapping

from .driver_registry import DEFAULT_DRIVER_REGISTRY
from .state import STATE, ActiveCameraState


LOGGER = logging.getLogger(__name__)

_active_driver = None
_active_capabilities = {}


def _clear_active_camera():
    global _active_driver, _active_capabilities
    _active_driver = None
    _active_capabilities = {}
    STATE.active_camera = None
    STATE.active_capabilities = {}


def _build_active_camera(device, selected_driver_id: str):
    return ActiveCameraState(
        name=_device_value(device, "name"),
        device_id=_device_value(device, "device_id"),
        backend=_device_value(device, "backend"),
        driver_id=selected_driver_id,
        port=_device_value(device, "port"),
        host=_device_value(device, "host"),
    )


def _device_value(device, key: str):
    if isinstance(device, Mapping):
        return str(device.get(key, "") or "")
    return str(getattr(device, key, "") or "")


def _to_device_dict(device) -> Mapping[str, str]:
    return {
        "name": _device_value(device, "name"),
        "device_id": _device_value(device, "device_id"),
        "backend": _device_value(device, "backend"),
        "port": _device_value(device, "port"),
        "host": _device_value(device, "host"),
    }


def connect(device):
    global _active_driver, _active_capabilities

    _clear_active_camera()

    device_info = _to_device_dict(device)
    LOGGER.info(
        "Detected device: name='%s' backend='%s' host='%s' port='%s' device_id='%s'",
        device_info.get("name", ""),
        device_info.get("backend", ""),
        device_info.get("host", ""),
        device_info.get("port", ""),
        device_info.get("device_id", ""),
    )

    candidates = DEFAULT_DRIVER_REGISTRY.resolve_connection_candidates(device_info)

    if not candidates:
        LOGGER.warning("No usable drivers discovered for detected device.")
        return False

    for driver_class in candidates:
        driver_id = driver_class.get_driver_id()
        is_fallback = driver_class.is_fallback()
        LOGGER.info(
            "Trying driver '%s' (fallback=%s, priority=%s)",
            driver_id,
            is_fallback,
            driver_class.get_priority(),
        )

        try:
            driver = driver_class(device_info)
        except Exception as exc:
            LOGGER.exception("Failed to instantiate driver '%s': %s", driver_id, exc)
            continue

        try:
            if not driver.connect():
                LOGGER.warning("Driver '%s' could not connect device.", driver_id)
                continue
        except Exception as exc:
            LOGGER.exception("Driver '%s' raised during connect: %s", driver_id, exc)
            continue

        _active_driver = driver
        _active_capabilities = _active_driver.get_capabilities() or {}
        STATE.active_capabilities = dict(_active_capabilities)
        STATE.active_camera = _build_active_camera(device_info, selected_driver_id=driver_id)
        LOGGER.info("Selected driver '%s' for device '%s'.", driver_id, device_info.get("name", ""))
        return True

    LOGGER.error("No driver managed to connect the detected device.")
    _clear_active_camera()
    return False


def get_active_driver():
    return _active_driver


def get_setting(key):
    if _active_driver:
        return _active_driver.get_setting(key)
    return None


def set_setting(key, value):
    if _active_driver:
        return _active_driver.set_setting(key, value)
    return False


def get_capabilities():
    if _active_driver is None:
        return {}
    return dict(_active_capabilities)
