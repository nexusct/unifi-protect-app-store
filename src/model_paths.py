"""One persistent model-weight path seam for Docker and bare-metal runs."""
from __future__ import annotations

import os
from pathlib import Path


def model_path(filename: str) -> str:
    if Path(filename).name != filename or not filename:
        raise ValueError("model filename must be a single path component")
    return str(Path(os.environ.get("VISION_MODELS", "/app/models")) / filename)
