"""Read mutable runtime settings written by the authenticated setup flow."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_RUNTIME_SETTINGS = "/config/runtime-settings.json"
_MAX_SETTINGS_BYTES = 64 * 1024


def load_runtime_settings(path: str | Path | None = None) -> dict[str, Any]:
    settings_path = Path(path or os.environ.get("VISION_RUNTIME_SETTINGS", DEFAULT_RUNTIME_SETTINGS))
    try:
        if not settings_path.is_file() or settings_path.stat().st_size > _MAX_SETTINGS_BYTES:
            return {}
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def runtime_setting(name: str, default: Any = None, *, required: bool = False) -> Any:
    """Return a non-empty environment value or its protected-file fallback."""
    environment_value = os.environ.get(name)
    if environment_value is not None and environment_value.strip():
        value: Any = environment_value
    else:
        value = load_runtime_settings().get(name, default)
    if required and (value is None or (isinstance(value, str) and not value.strip())):
        raise RuntimeError(f"required runtime setting is missing: {name}")
    return value
