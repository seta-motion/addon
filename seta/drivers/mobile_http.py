from __future__ import annotations

import json
import logging
import os
import shlex
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..driver_api import BaseCameraDriver


LOGGER = logging.getLogger(__name__)


class MobileHttpCameraDriver(BaseCameraDriver):
    DRIVER_ID = "mobile_http"
    DISPLAY_NAME = "SETA Mobile HTTP"
    BACKEND = "mobile_http"
    PRIORITY = 100
    IS_FALLBACK = False
    MATCH_PATTERNS = ()

    DEFAULT_TIMEOUT = 5.0
    SUPPORTED_SETTING_TYPES = {"choice", "boolean", "range"}

    def __init__(self, connection_info=None):
        super().__init__(connection_info=connection_info)

        self.timeout = self.DEFAULT_TIMEOUT
        self.base_url = self._build_base_url(self.host, self.port)

        self._status_data: dict[str, Any] = {}
        self._capabilities_data: dict[str, Any] = {}
        self._settings_data: dict[str, Any] = {}
        self._declared_settings_keys: list[str] = []

    @classmethod
    def matches_device(cls, device):
        backend = str(device.get("backend", "") or "").strip().lower()
        return backend == cls.BACKEND

    def _build_base_url(self, host: str, port: str) -> str:
        raw_host = str(host or "").strip()
        raw_port = str(port or "").strip()

        if not raw_host:
            return ""

        if raw_host.startswith("http://") or raw_host.startswith("https://"):
            parsed = urllib.parse.urlparse(raw_host)
        else:
            parsed = urllib.parse.urlparse(f"http://{raw_host}")

        scheme = parsed.scheme or "http"
        netloc = parsed.netloc or parsed.path
        path = parsed.path if parsed.netloc else ""

        if not netloc:
            return ""

        has_explicit_port = parsed.port is not None
        if raw_port and not has_explicit_port:
            netloc = f"{netloc}:{raw_port}"

        return urllib.parse.urlunparse((scheme, netloc, path.rstrip("/"), "", "", "")).rstrip("/")

    def _api_url(self, suffix: str) -> str:
        suffix = str(suffix or "").strip()
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        return f"{self.base_url}/api/v1{suffix}"

    def _json_request(self, method: str, suffix: str, payload=None):
        url = self._api_url(suffix)
        data = None
        headers = {
            "Accept": "application/json",
        }

        if method.upper() == "POST":
            if payload is None:
                data = b""
            else:
                data = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url=url,
            data=data,
            method=method.upper(),
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error for {url}: {exc}") from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON response from {url}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected JSON envelope from {url}")

        if not parsed.get("ok", False):
            error_obj = parsed.get("error", {})
            if isinstance(error_obj, dict):
                code = str(error_obj.get("code", "") or "").strip()
                message = str(error_obj.get("message", "") or "").strip()
                details = error_obj.get("details")
                raise RuntimeError(
                    f"Backend returned ok=false for {url}: "
                    f"code={code or 'UNKNOWN'} message={message or 'no message'} details={details!r}"
                )

            raise RuntimeError(f"Backend returned ok=false for {url}")

        data_obj = parsed.get("data", {})
        if isinstance(data_obj, dict):
            return data_obj
        return {}

    def _binary_request(self, method: str, suffix: str) -> bytes:
        url = self._api_url(suffix)
        req = urllib.request.Request(
            url=url,
            method=method.upper(),
            headers={"Accept": "*/*"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error for {url}: {exc}") from exc

    def _refresh_status(self):
        self._status_data = dict(self._json_request("GET", "/status"))
        return dict(self._status_data)

    def _refresh_capabilities(self):
        self._capabilities_data = dict(self._json_request("GET", "/capabilities"))
        return dict(self._capabilities_data)

    def _refresh_settings(self):
        settings = self._json_request("GET", "/settings")
        self._settings_data = dict(settings)

        keys = settings.get("keys", [])
        self._declared_settings_keys = [str(k or "") for k in keys] if isinstance(keys, list) else []

        return dict(self._settings_data)

    def _get_values_map(self) -> dict[str, Any]:
        values = self._settings_data.get("values", {})
        return values if isinstance(values, dict) else {}

    def _get_setting_block(self, key: str):
        values = self._get_values_map()
        block = values.get(key)
        return block if isinstance(block, dict) else None

    def _normalize_setting_value(self, setting_type: str, value):
        if setting_type == "choice":
            return str(value or "").strip()

        if setting_type == "boolean":
            if isinstance(value, bool):
                return value
            return None

        if setting_type == "range":
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return float(value)
            return None

        return None

    def _validate_setting_value(self, key: str, block: dict[str, Any], value):
        setting_type = str(block.get("type", "") or "").strip().lower()
        normalized = self._normalize_setting_value(setting_type, value)
        if normalized is None:
            LOGGER.warning(
                "%s rejected value for setting '%s': unsupported or invalid type '%s' value=%r",
                self.get_driver_id(),
                key,
                setting_type,
                value,
            )
            return False, None

        if setting_type == "choice":
            choices = block.get("choices", [])
            if not isinstance(choices, list):
                choices = []
            choices = [str(choice or "").strip() for choice in choices if str(choice or "").strip()]
            if normalized not in choices:
                LOGGER.warning(
                    "%s rejected invalid choice '%s' for setting '%s'. Valid choices: %s",
                    self.get_driver_id(),
                    normalized,
                    key,
                    choices,
                )
                return False, None
            return True, normalized

        if setting_type == "range":
            min_value = block.get("min")
            max_value = block.get("max")

            if isinstance(min_value, (int, float)) and normalized < float(min_value):
                LOGGER.warning(
                    "%s rejected value %s for setting '%s': below min %s",
                    self.get_driver_id(),
                    normalized,
                    key,
                    min_value,
                )
                return False, None

            if isinstance(max_value, (int, float)) and normalized > float(max_value):
                LOGGER.warning(
                    "%s rejected value %s for setting '%s': above max %s",
                    self.get_driver_id(),
                    normalized,
                    key,
                    max_value,
                )
                return False, None

            return True, normalized

        if setting_type == "boolean":
            return True, normalized

        return False, None

    def _build_setting_response(self, key: str, block: dict[str, Any]):
        setting_type = str(block.get("type", "") or "").strip().lower()
        if setting_type not in self.SUPPORTED_SETTING_TYPES:
            return None

        response = {
            "type": setting_type,
            "current": block.get("current"),
        }

        if setting_type == "choice":
            choices = block.get("choices", [])
            if not isinstance(choices, list):
                choices = []
            response["choices"] = [str(choice or "").strip() for choice in choices if str(choice or "").strip()]

        elif setting_type == "range":
            if isinstance(block.get("min"), (int, float)):
                response["min"] = float(block["min"])
            if isinstance(block.get("max"), (int, float)):
                response["max"] = float(block["max"])

        elif setting_type == "boolean":
            response["current"] = bool(block.get("current", False))

        return response

    def _collect_supported_settings_meta(self):
        if not self._settings_data:
            try:
                self._refresh_settings()
            except Exception as exc:
                LOGGER.warning("%s could not refresh settings metadata: %s", self.get_driver_id(), exc)
                return {}, []

        settings_meta = {}
        supported_settings = []

        for key in self._declared_settings_keys:
            block = self._get_setting_block(key)
            if not block:
                continue

            normalized = self._build_setting_response(key, block)
            if not normalized:
                continue

            settings_meta[key] = normalized
            supported_settings.append(key)

        return settings_meta, supported_settings

    def connect(self):
        if not self.base_url:
            LOGGER.warning("%s missing base URL (host/port).", self.get_driver_id())
            return False

        try:
            status = self._refresh_status()
            capabilities = self._refresh_capabilities()

            try:
                self._refresh_settings()
            except Exception as exc:
                LOGGER.warning("%s could not read /settings: %s", self.get_driver_id(), exc)
                self._settings_data = {}
                self._declared_settings_keys = []

            if not bool(status.get("serverRunning", False)):
                LOGGER.warning("%s serverRunning=false at %s", self.get_driver_id(), self.base_url)
                return False

            if not bool(status.get("cameraOpen", False)):
                LOGGER.warning("%s cameraOpen=false at %s", self.get_driver_id(), self.base_url)
                return False

            LOGGER.info("%s connected to %s", self.get_driver_id(), self.base_url)
            LOGGER.info(
                "%s capabilities: capture=%s preview=%s format=%s settings=%s",
                self.get_driver_id(),
                bool(capabilities.get("supportsCapture", False)),
                bool(capabilities.get("supportsPreview", False)),
                str(capabilities.get("previewFormat", "") or ""),
                self._declared_settings_keys,
            )
            return True

        except Exception as exc:
            LOGGER.exception("%s connect exception: %s", self.get_driver_id(), exc)
            return False

    def capture(self, output_path):
        supports_capture = bool(self._capabilities_data.get("supportsCapture", True))
        if not supports_capture:
            LOGGER.warning("%s capture not supported by backend.", self.get_driver_id())
            return False

        try:
            capture_meta = self._json_request("POST", "/capture")
            capture_id = str(capture_meta.get("captureId", "") or "").strip()
            if not capture_id:
                LOGGER.warning("%s capture response missing captureId.", self.get_driver_id())
                return False

            safe_capture_id = urllib.parse.quote(capture_id, safe="")
            image_bytes = self._binary_request("GET", f"/capture/{safe_capture_id}")
            if not image_bytes:
                LOGGER.warning("%s capture download returned empty payload.", self.get_driver_id())
                return False

            target_dir = os.path.dirname(output_path) or "."
            os.makedirs(target_dir, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                prefix="seta_mobile_capture_",
                suffix=".jpg",
                dir=target_dir,
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(image_bytes)
                os.replace(tmp_path, output_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

            self._status_data["lastCaptureId"] = capture_id
            LOGGER.info("%s image captured: %s", self.get_driver_id(), output_path)
            return True

        except Exception as exc:
            LOGGER.exception("%s capture exception: %s", self.get_driver_id(), exc)
            return False

    def build_preview_source_cmd(self):
        supports_preview = bool(self._capabilities_data.get("supportsPreview", True))
        preview_format = str(self._capabilities_data.get("previewFormat", "") or "").strip().lower()

        if not supports_preview:
            LOGGER.warning("%s preview not supported by backend.", self.get_driver_id())
            return []

        if preview_format and preview_format != "mjpeg":
            LOGGER.warning(
                "%s preview format '%s' is not supported by current SETA preview pipeline.",
                self.get_driver_id(),
                preview_format,
            )
            return []

        try:
            self._json_request("POST", "/preview/start")
        except Exception as exc:
            LOGGER.exception("%s preview/start exception: %s", self.get_driver_id(), exc)
            return []

        preview_url = self._api_url("/preview")
        stop_url = self._api_url("/preview/stop")

        quoted_preview_url = shlex.quote(preview_url)
        quoted_stop_url = shlex.quote(stop_url)

        script = (
            "set -u\n"
            f"trap 'curl -fsS -X POST --max-time 2 {quoted_stop_url} >/dev/null 2>&1 || true' EXIT INT TERM\n"
            f"ffmpeg -hide_banner -loglevel warning -fflags nobuffer -flags low_delay "
            f"-i {quoted_preview_url} -an -c:v mjpeg -f mjpeg -\n"
        )

        return ["bash", "-lc", script]

    def get_preview_cleanup_patterns(self):
        preview_url = self._api_url("/preview")
        stop_url = self._api_url("/preview/stop")

        quoted_preview_url = shlex.quote(preview_url)
        quoted_stop_url = shlex.quote(stop_url)

        return [
            rf"ffmpeg .*{quoted_preview_url}",
            rf"curl .*{quoted_stop_url}",
        ]

    def get_setting(self, key):
        key = str(key or "").strip()
        if not key:
            return None

        if not self._settings_data:
            try:
                self._refresh_settings()
            except Exception as exc:
                LOGGER.warning("%s get_setting refresh failed: %s", self.get_driver_id(), exc)
                return None

        block = self._get_setting_block(key)
        if not block:
            return None

        return self._build_setting_response(key, block)

    def set_setting(self, key, value):
        key = str(key or "").strip()
        if not key:
            return False

        if not self._settings_data:
            try:
                self._refresh_settings()
            except Exception as exc:
                LOGGER.warning("%s set_setting refresh failed: %s", self.get_driver_id(), exc)
                return False

        block = self._get_setting_block(key)
        if not block:
            LOGGER.info("%s set_setting('%s') not supported by backend.", self.get_driver_id(), key)
            return False

        ok, normalized_value = self._validate_setting_value(key, block, value)
        if not ok:
            return False

        try:
            self._json_request("POST", "/settings", {key: normalized_value})
            self._refresh_settings()
            try:
                self._refresh_status()
            except Exception:
                pass

            refreshed = self.get_setting(key)
            if not refreshed:
                LOGGER.warning("%s could not confirm setting '%s' after apply.", self.get_driver_id(), key)
                return False

            refreshed_current = refreshed.get("current")
            if refreshed.get("type") == "range":
                try:
                    if abs(float(refreshed_current) - float(normalized_value)) <= 1e-3:
                        LOGGER.info("%s set %s -> %s", self.get_driver_id(), key, normalized_value)
                        return True
                except Exception:
                    pass
            else:
                if refreshed_current == normalized_value:
                    LOGGER.info("%s set %s -> %s", self.get_driver_id(), key, normalized_value)
                    return True

            LOGGER.warning(
                "%s set_setting('%s') applied request but confirmation did not match requested value %r.",
                self.get_driver_id(),
                key,
                normalized_value,
            )
            return False

        except Exception as exc:
            LOGGER.exception("%s set_setting exception: %s", self.get_driver_id(), exc)
            return False

    def get_capabilities(self):
        raw_supports_capture = bool(self._capabilities_data.get("supportsCapture", True))
        raw_supports_preview = bool(self._capabilities_data.get("supportsPreview", True))
        preview_format = str(self._capabilities_data.get("previewFormat", "") or "").strip().lower()

        supports_preview = raw_supports_preview and (not preview_format or preview_format == "mjpeg")
        settings_meta, supported_settings = self._collect_supported_settings_meta()

        return {
            "backend": self.BACKEND,
            "driver_id": self.get_driver_id(),
            "driver_name": self.get_display_name(),
            "supports_capture": raw_supports_capture,
            "supports_preview": supports_preview,
            "preview_format": preview_format,
            "settings": list(supported_settings),
            "supported_settings": list(supported_settings),
            "settings_meta": dict(settings_meta),
            "declared_settings": list(self._declared_settings_keys),
            "connection_info": {
                "host": self.host,
                "port": self.port,
                "base_url": self.base_url,
            },
            "status": {
                "activeLens": str(self._status_data.get("activeLens", "") or ""),
                "previewRemoteRunning": bool(self._status_data.get("previewRemoteRunning", False)),
                "previewLocalRunning": bool(self._status_data.get("previewLocalRunning", False)),
            },
        }