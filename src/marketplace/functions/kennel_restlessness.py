"""Kennel Restlessness — activity scoring per boarding kennel.

Motion energy per kennel zone over time: a dog pacing all night scores
high; settled scores low. Boarding operators get overnight welfare data
and owners get a "how did he sleep" report worth paying for.
"""
from collections import defaultdict
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "kennel-restlessness",
    "name": "Kennel Restlessness Score",
    "tagline": "Run 12 paced all night. The morning report said so, with numbers.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "kennels": "map of kennel-name → polygon",
        "digest_hour": "int (default 7)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 7))
        self._prev = {}
        self._energy = defaultdict(float)
        self._frames = defaultdict(int)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        kennels = (camera.get("zones") or {}).get("kennels") or {}
        if not kennels:
            return
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        for name, poly in kennels.items():
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            crop = gray[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)]
            if crop.size == 0:
                continue
            key = (camera["id"], name)
            prev = self._prev.get(key)
            self._prev[key] = crop
            if prev is None or prev.shape != crop.shape:
                continue
            e = float(np.mean(cv2.absdiff(crop, prev))) / 255.0
            self._energy[key] += e
            self._frames[key] += 1
        import time as _t
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._energy:
            lines = {k[1]: round(self._energy[k] / max(self._frames[k], 1), 4)
                     for k in self._energy}
            top = sorted(lines.items(), key=lambda x: x[1], reverse=True)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Overnight kennel restlessness",
                detail=" | ".join(f"{n}: {v}" for n, v in top[:8]),
                frame=None, meta={"scores": lines})
            self._energy.clear(); self._frames.clear()
            self._last_day = day
