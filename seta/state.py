from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import subprocess


PREVIEW_BACKEND_NONE = "NONE"
PREVIEW_BACKEND_FAST = "FAST"
PREVIEW_BACKEND_VSE = "VSE"


@dataclass
class ActiveCameraState:
    name: str
    device_id: str
    backend: str
    driver_id: str
    port: str
    host: str


@dataclass
class PreviewProcessHandles:
    source: Optional[subprocess.Popen] = None
    ffplay: Optional[subprocess.Popen] = None
    vse_writer: Optional[subprocess.Popen] = None


@dataclass
class SetaState:
    # Preview runtime
    preview_running: bool = False
    preview_procs: PreviewProcessHandles = field(default_factory=PreviewProcessHandles)

    # Camera lock
    camera_busy: bool = False

    # Active connected camera
    active_camera: Optional[ActiveCameraState] = None
    active_capabilities: dict = field(default_factory=dict)

    # Preview backend runtime
    preview_backend: str = PREVIEW_BACKEND_NONE
    preview_resume_backend: str = PREVIEW_BACKEND_NONE

    # VSE preview runtime
    vse_preview_timer_registered: bool = False
    vse_preview_last_mtime: float = 0.0


STATE = SetaState()
