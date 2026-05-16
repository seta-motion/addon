from __future__ import annotations

import importlib.util
import inspect
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Type

from .base_driver import BaseCameraDriver


LOGGER = logging.getLogger(__name__)


def _iter_unique_paths(paths: Iterable[Path]) -> Iterable[Path]:
    seen = set()
    for raw_path in paths:
        path = raw_path.expanduser()
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        yield path


class DriverRegistry:
    def __init__(self, external_dirs: Optional[Sequence[str]] = None):
        package_root = Path(__file__).resolve().parent
        addon_root = package_root.parent

        self.internal_dir = package_root / "drivers"
        self.sibling_external_dir = addon_root / "drivers"

        configured_external = [str(self.sibling_external_dir)]
        configured_external.extend(list(external_dirs or []))

        env_dirs = os.environ.get("SETA_DRIVERS_DIR", "")
        if env_dirs:
            configured_external.extend([p for p in env_dirs.split(os.pathsep) if p.strip()])

        configured_external.append(str(Path.home() / ".seta" / "drivers"))

        self.external_dirs = [Path(p) for p in configured_external if p]
        self._drivers: List[Type[BaseCameraDriver]] = []
        self._loaded = False

    def discover(self, force_reload: bool = False) -> List[Type[BaseCameraDriver]]:
        if self._loaded and not force_reload:
            return list(self._drivers)

        self._drivers = []
        self._loaded = True

        for driver_file in self._iter_driver_files():
            module = self._safe_import_module(driver_file)
            if not module:
                continue
            self._register_module_drivers(module, driver_file)

        LOGGER.info("SETA driver discovery completed: %d driver class(es)", len(self._drivers))
        return list(self._drivers)

    def resolve_connection_candidates(self, device: Mapping[str, str]) -> List[Type[BaseCameraDriver]]:
        self.discover()

        specific: List[Type[BaseCameraDriver]] = []
        fallbacks: List[Type[BaseCameraDriver]] = []
        device_backend = str(device.get("backend", "") or "").strip().lower()

        for driver_cls in self._drivers:
            try:
                if driver_cls.is_fallback():
                    driver_backend = str(getattr(driver_cls, "BACKEND", "") or "").strip().lower()
                    if device_backend and driver_backend != device_backend:
                        continue
                    fallbacks.append(driver_cls)
                elif driver_cls.matches_device(device):
                    specific.append(driver_cls)
            except Exception as exc:
                LOGGER.exception("Driver '%s' failed during matching: %s", driver_cls.get_driver_id(), exc)

        specific.sort(key=lambda c: c.get_priority(), reverse=True)
        fallbacks.sort(key=lambda c: c.get_priority(), reverse=True)

        return [*specific, *fallbacks]

    def resolve_best_driver(self, device: Mapping[str, str]) -> Optional[Type[BaseCameraDriver]]:
        candidates = self.resolve_connection_candidates(device)
        return candidates[0] if candidates else None

    def _iter_driver_files(self) -> Iterable[Path]:
        all_dirs = [self.internal_dir, *self.external_dirs]
        for folder in _iter_unique_paths(all_dirs):
            if not folder.exists():
                LOGGER.debug("Driver directory not found (skipped): %s", folder)
                continue
            if not folder.is_dir():
                LOGGER.warning("Driver path is not a directory (skipped): %s", folder)
                continue

            LOGGER.info("Discovering drivers in: %s", folder)

            for path in sorted(folder.glob("*.py")):
                if path.name.startswith("_") or path.name == "__init__.py":
                    continue
                yield path

    def _safe_import_module(self, path: Path) -> Optional[ModuleType]:
        module_name = f"seta.dynamic_driver.{path.stem}_{abs(hash(str(path)))}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                LOGGER.error("Could not create import spec for driver file: %s", path)
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as exc:
            LOGGER.exception("Failed to import driver file '%s': %s", path, exc)
            return None

    def _validate_driver_class(self, cls: Type[BaseCameraDriver], source_path: Path) -> Tuple[bool, str]:
        driver_id = str(getattr(cls, "DRIVER_ID", "") or "").strip()
        if not driver_id:
            return False, "DRIVER_ID must be a non-empty string"

        display_name = str(getattr(cls, "DISPLAY_NAME", "") or "").strip()
        if not display_name:
            return False, "DISPLAY_NAME must be a non-empty string"

        backend = str(getattr(cls, "BACKEND", "") or "").strip()
        if not backend:
            return False, "BACKEND must be a non-empty string"

        try:
            cls.get_priority()
        except Exception:
            return False, "PRIORITY must be interpretable as int"

        try:
            cls.is_fallback()
        except Exception:
            return False, "IS_FALLBACK must be interpretable as bool"

        if not cls.is_fallback():
            patterns = tuple(getattr(cls, "MATCH_PATTERNS", ()) or ())
            custom_match = "matches_device" in cls.__dict__
            if not patterns and not custom_match:
                return False, "specific drivers need MATCH_PATTERNS or custom matches_device"

        required_methods = [
            "connect",
            "capture",
            "build_preview_source_cmd",
            "get_preview_cleanup_patterns",
            "get_setting",
            "set_setting",
            "get_capabilities",
        ]
        for method_name in required_methods:
            method = getattr(cls, method_name, None)
            if not callable(method):
                return False, f"missing callable method: {method_name}"

            base_method = getattr(BaseCameraDriver, method_name, None)
            if method is base_method:
                return False, f"method '{method_name}' is not implemented"

        return True, ""

    def _register_module_drivers(self, module: ModuleType, source_path: Path) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseCameraDriver or not issubclass(obj, BaseCameraDriver):
                continue
            if obj.__module__ != module.__name__:
                continue

            valid, reason = self._validate_driver_class(obj, source_path)
            if not valid:
                LOGGER.warning("Driver class rejected from %s (%s): %s", source_path, obj.__name__, reason)
                continue

            driver_id = obj.get_driver_id()
            if any(existing.get_driver_id() == driver_id for existing in self._drivers):
                LOGGER.warning("Duplicate driver_id '%s' ignored from %s", driver_id, source_path)
                continue

            self._drivers.append(obj)
            LOGGER.info(
                "Registered driver: id='%s' fallback=%s priority=%s source=%s",
                obj.get_driver_id(),
                obj.is_fallback(),
                obj.get_priority(),
                source_path,
            )


DEFAULT_DRIVER_REGISTRY = DriverRegistry()
