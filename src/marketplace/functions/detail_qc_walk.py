"""Detail QC Walk — post-wash vehicle inspection flag.

Vehicle in the QC zone gets a quick surface-change scan vs its entry
state: obvious missed spots (foam residue, heavy dirt contrast) flag a
re-touch before delivery. Express-detail operators protect reviews this way.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "detail-qc-walk",
    "name": "Detail QC Flag",
    "tagline": "Foam still on the rear quarter at delivery. Flagged before the customer saw it.",
    "category": "Automotive & Parking",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — QC/delivery area",
        "residue_ratio": "float — bright-patch threshold (default 0.06)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("residue_ratio", 0.06))
        self._tracker = ZoneTracker()
        self._checked = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("qc_zone")
        if not zone:
            return
        import cv2
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            entered, _, _ = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if not entered or tid in self._checked:
                continue
            self._checked.add(tid)
            crop = frame[int(y1):int(y2), int(x1):int(x2)]
            if crop.size == 0:
                continue
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            bright = cv2.inRange(hsv, (0, 0, 235), (180, 40, 255))
            ratio = float(np.count_nonzero(bright)) / bright.size
            if ratio >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Possible wash residue at delivery",
                    detail=f"Bright-patch ratio {ratio:.2f} on vehicle in QC zone on {camera['name']}.",
                    frame=frame, meta={"ratio": round(ratio, 3)})
