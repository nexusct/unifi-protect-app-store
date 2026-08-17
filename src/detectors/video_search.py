"""Detector 8: natural-language video search (OpenCLIP embeddings).

Embeds a frame every embed_every_seconds per camera into a persistent
index (data/embeddings/). The /search API then answers "red truck Tuesday"
in one query instead of hours of scrubbing.
"""
import hashlib
import logging
import os
import re
import time
from pathlib import Path

import numpy as np

from detectors.base import Detector, register

log = logging.getLogger("detectors.video_search")

_clip = {"model": None, "preprocess": None, "tokenizer": None}
DATA_DIR = Path(os.environ.get("VISION_DATA", "/app/data"))
EMBED_DIR = DATA_DIR / "embeddings"
_SAFE_CAMERA_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _embedding_directory() -> Path:
    data_root = DATA_DIR.resolve()
    directory = EMBED_DIR.resolve()
    if not directory.is_relative_to(data_root):
        raise ValueError("embedding directory must remain inside VISION_DATA")
    return directory


def _embedding_path(camera_name: str, timestamp: float) -> Path:
    raw_name = str(camera_name)
    legacy_name = raw_name.replace(" ", "_")
    if _SAFE_CAMERA_COMPONENT.fullmatch(legacy_name) and legacy_name not in {".", ".."}:
        component = legacy_name
    else:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._-")[:80] or "camera"
        digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:12]
        component = f"{slug}-{digest}"
    return _embedding_directory() / f"{component}_{int(timestamp)}.npy"


def prune_embeddings(
    directory=EMBED_DIR,
    *,
    max_files: int = 10000,
    retention_days: float = 7,
    now: float | None = None,
):
    """Bound the persistent embedding index by age and file count."""
    current = time.time() if now is None else float(now)
    root = Path(directory)
    files = sorted(
        (path for path in root.glob("*.npy") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if float(retention_days) > 0:
        cutoff = current - float(retention_days) * 86400
        for path in list(files):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        files = [path for path in files if path.exists()]
    for path in files[max(1, int(max_files)):]:
        path.unlink(missing_ok=True)


def _load_clip():
    if _clip["model"] is None:
        import open_clip
        import torch
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        model.eval().to(os.environ.get("VISION_DEVICE", "cuda"))
        _clip["model"] = model
        _clip["preprocess"] = preprocess
        _clip["tokenizer"] = open_clip.get_tokenizer("ViT-B-32")
    return _clip["model"], _clip["preprocess"], _clip["tokenizer"]


def _embed_image(frame) -> np.ndarray:
    import torch
    from PIL import Image
    model, preprocess, _ = _load_clip()
    img = Image.fromarray(frame[:, :, ::-1])  # BGR→RGB
    with torch.no_grad():
        vec = model.encode_image(preprocess(img).unsqueeze(0).to(os.environ.get("VISION_DEVICE", "cuda")))
    vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy()[0]


def _embed_text(text: str) -> np.ndarray:
    import torch
    model, _, tokenizer = _load_clip()
    with torch.no_grad():
        vec = model.encode_text(tokenizer([text]).to(os.environ.get("VISION_DEVICE", "cuda")))
    vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy()[0]


def search(query: str, limit: int = 10):
    """Cosine search over the embedding index. Returns best (camera, ts, score)."""
    if not EMBED_DIR.exists():
        return []
    entries = []
    for f in EMBED_DIR.glob("*.npy"):
        try:
            entries.append((f.stem, np.load(f)))
        except Exception:
            continue
    if not entries:
        return []
    q = _embed_text(query)
    scored = sorted(
        ((name, float(np.dot(q, vec))) for name, vec in entries),
        key=lambda x: x[1], reverse=True,
    )[:limit]
    results = []
    for name, score in scored:
        cam, ts = name.rsplit("_", 1)
        results.append({
            "camera": cam,
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts))),
            "score": round(score, 3),
        })
    return results


@register
class VideoSearchIndexer(Detector):
    name = "video_search"

    def __init__(self, settings):
        super().__init__(settings)
        self.interval = float(self.settings.get("embed_every_seconds", 5))
        self.max_embeddings = int(self.settings.get("max_embeddings", 10000))
        self.retention_days = float(self.settings.get("retention_days", 7))
        self._last = {}
        self._last_prune = 0
        _embedding_directory().mkdir(parents=True, exist_ok=True)

    def process(self, camera, frame, ts, ctx):
        last = self._last.get(camera["id"], 0)
        if ts - last < self.interval:
            return
        self._last[camera["id"]] = ts
        try:
            vec = _embed_image(frame)
            np.save(_embedding_path(camera["name"], ts), vec)
            if ts - self._last_prune >= 60:
                prune_embeddings(
                    EMBED_DIR,
                    max_files=self.max_embeddings,
                    retention_days=self.retention_days,
                    now=ts,
                )
                self._last_prune = ts
        except Exception as exc:
            log.warning("embed failed on %s: %s", camera["name"], exc)
