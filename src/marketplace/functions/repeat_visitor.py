"""Repeat Appearance Pattern — color-signature similarity across observations.

No faces or identity matching: this clusters coarse clothing-color histograms
across hourly observation buckets. Similarity can produce false matches and
always requires human review.
"""
from collections import defaultdict
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, pixel_box

MANIFEST = {
    "id": "repeat-visitor",
    "name": "Repeat Appearance Pattern",
    "tagline": "Clusters similar appearance-color signatures across configured observations for human review; it is not identity matching and may produce false matches.",
    "category": "Intelligence",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "visits_threshold": "Number of separate sessions with a similar appearance before review (default: 3).",
        "window_days": "int (default 7)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.threshold = int(self.settings.get("visits_threshold", 3))
        self.window = float(self.settings.get("window_days", 7)) * 86400
        self._sigs = []  # (ts, signature vec, camera)

    @staticmethod
    def _signature(frame, box):
        import cv2
        x1, y1, x2, y2 = pixel_box(frame, *box)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        hist = cv2.calcHist([crop], [0, 1, 2], None, [4, 4, 4], [0, 256] * 3)
        return cv2.normalize(hist, hist).flatten()

    def process(self, camera, frame, ts, ctx):
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            sig = self._signature(frame, (x1, y1, x2, y2))
            if sig is None:
                continue
            self._sigs = [s for s in self._sigs if ts - s[0] <= self.window]
            matches = [s for s in self._sigs if float(np.dot(sig, s[1])) > 0.85]
            self._sigs.append((ts, sig, camera["id"]))
            distinct_sessions = {int(s[0] // 3600) for s in matches}  # rough hourly session bucketing
            if len(distinct_sessions) >= self.threshold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Repeat appearance-similarity pattern",
                    detail=f"A color-histogram signature exceeded the similarity threshold across {len(distinct_sessions)} observation buckets in {self.window/86400:.0f} days near {camera['name']}; this is not identity matching.",
                    frame=frame, meta={"sessions": len(distinct_sessions)})
                self._sigs = [s for s in self._sigs if float(np.dot(sig, s[1])) <= 0.85]
