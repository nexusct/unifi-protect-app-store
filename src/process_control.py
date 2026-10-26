"""Guarded in-process restart scheduling for restart-policy containers."""
from __future__ import annotations

import os
import threading
from collections.abc import Callable


def setup_restart_callback(
    *,
    timer_factory=threading.Timer,
    exit_fn: Callable[[int], None] = os._exit,
):
    enabled = os.environ.get("VISION_SETUP_RESTART_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    def request_restart() -> None:
        timer = timer_factory(0.75, lambda: exit_fn(0))
        timer.daemon = True
        timer.start()

    return request_restart
