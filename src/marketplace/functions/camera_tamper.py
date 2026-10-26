"""Camera Tamper — view blocked, sprayed, or redirected.

Compares live frames to a rolling reference: a sudden structural drop
(edge-density collapse) or a large persistent frame-diff = covered,
sprayed, or moved camera. The camera you can't trust is worse than none.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "camera-tamper",
    "name": "Camera View Change Alert",
    "tagline": "Flags substantial edge-density loss or frame change from the learned reference; confirm detection and delivery timing during commissioning.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "edge_drop_ratio": "float vs baseline (default 0.6)",
        "diff_ratio": "float persistent-diff (default 0.5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.edge_drop = float(self.settings.get("edge_drop_ratio", 0.6))
        self.diff_limit = float(self.settings.get("diff_ratio", 0.5))
        self._baseline = {}
        self._samples = {}
        self._ref = {}

    def process(self, camera, frame, ts, ctx):
        import cv2
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
        edges = float(np.count_nonzero(cv2.Canny(gray, 60, 160))) / gray.size
        key = camera["id"]
        if key not in self._baseline:
            self._samples.setdefault(key, []).append((edges, gray))
            if len(self._samples[key]) >= 30:
                self._baseline[key] = float(np.mean([e for e, _ in self._samples[key]]))
                self._ref[key] = self._samples[key][-1][1]
            return
        base = self._baseline[key]
        tampered = base > 0 and (base - edges) / base >= self.edge_drop
        if not tampered and key in self._ref:
            diff = float(np.mean(cv2.absdiff(gray, self._ref[key]))) / 255.0
            tampered = diff >= self.diff_limit
        if tampered:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Camera view obstructed or moved",
                detail=f"Edge density {edges:.3f} vs baseline {base:.3f} on {camera['name']}.",
                frame=frame, meta={"edges": round(edges, 4), "baseline": round(base, 4)})
