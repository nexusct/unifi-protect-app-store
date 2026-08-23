"""Detector 8: natural-language video search (OpenCLIP embeddings).

Embeds a frame every embed_every_seconds per camera into a persistent
index (data/embeddings/). The /search API then answers "red truck Tuesday"
in one query instead of hours of scrubbing.
"""
import logging
import os
import time
from pathlib import Path

import numpy as np

from detectors.base import Detector, register

log = logging.getLogger("detectors.video_search")

_clip = {"model": None, "preprocess": None, "tokenizer": None}
DATA_DIR = Path(os.environ.get("VISION_DATA", "/app/data"))
EMBED_DIR = DATA_DIR / "embeddings"


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
        self._last = {}
        EMBED_DIR.mkdir(parents=True, exist_ok=True)

    def process(self, camera, frame, ts, ctx):
        last = self._last.get(camera["id"], 0)
        if ts - last < self.interval:
            return
        self._last[camera["id"]] = ts
        try:
            vec = _embed_image(frame)
            # Sanitize camera name to prevent path traversal
            safe_name = camera['name'].replace(' ', '_').replace('/', '_').replace('\\', '_').replace('..', '_')
            np.save(EMBED_DIR / f"{safe_name}_{int(ts)}.npy", vec)
        except Exception as exc:
            log.warning("embed failed on %s: %s", camera["name"], exc)
