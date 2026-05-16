from __future__ import annotations

import subprocess
import time


def run_pkill(sig_name: str, pattern: str) -> None:
    try:
        subprocess.run(
            ["pkill", f"-{sig_name}", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2.0,
        )
    except Exception:
        pass


def aggressive_preview_cleanup(driver=None) -> None:
    patterns = []
    if driver:
        patterns.extend(driver.get_preview_cleanup_patterns() or [])

    for pattern in patterns:
        run_pkill("INT", pattern)

    run_pkill("TERM", r"ffplay .*SETA Preview")
    run_pkill("TERM", r"ffmpeg .*blend=all_mode=")
    run_pkill("TERM", r"ffmpeg .*seta_live_preview\.jpg")

    time.sleep(0.8)

    for pattern in patterns:
        run_pkill("KILL", pattern)

    run_pkill("KILL", r"ffplay .*SETA Preview")
    run_pkill("KILL", r"ffmpeg .*blend=all_mode=")
    run_pkill("KILL", r"ffmpeg .*seta_live_preview\.jpg")

    time.sleep(0.3)
