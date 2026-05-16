#device_discovery.py

import logging
import platform
import re
import subprocess


LOGGER = logging.getLogger(__name__)


def detect_all():
    """
    Detect available camera devices using available backends.
    Currently supports gphoto2 (Linux / macOS).
    Returns a list of dictionaries.
    """

    devices = []

    system = platform.system()

    if system in ["Linux", "Darwin"]:
        try:
            result = subprocess.run(
                ["gphoto2", "--auto-detect"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout.splitlines()
            row_pattern = re.compile(r"^(?P<name>.+?)\s{2,}(?P<port>[^\s].+)$")

            for line in output[2:]:
                line = line.rstrip()
                if not line:
                    continue

                match = row_pattern.match(line)
                if not match:
                    continue

                name = match.group("name").strip()
                port = match.group("port").strip()
                if not name or not port:
                    continue

                device = {
                    "name": name,
                    "device_id": port,
                    "backend": "gphoto2",
                    "port": port,
                }
                devices.append(device)
                LOGGER.info(
                    "Detected device: name='%s' backend='%s' port='%s'",
                    name,
                    device["backend"],
                    port,
                )

        except FileNotFoundError:
            LOGGER.warning("gphoto2 not found on system")
        except Exception:
            LOGGER.exception("Unexpected error while detecting cameras")

    if system == "Windows":
        pass

    return devices
