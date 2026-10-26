"""Persistent Object Review — tracked object remains near one image position.

Flags an object-class track after limited image-space movement and no nearby
person-class detection for the configured duration. Human review is required;
the signal does not determine ownership or abandonment.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "abandoned-object",
    "name": "Persistent Object Review",
    "tagline": "Flags a stationary object after the configured dwell threshold for human review; detection and delivery latency vary by deployment.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — public area",
        "abandon_seconds": "int (default 45)",
        "object_classes": "list of COCO ids (default bags/luggage)",
    },
}

DEFAULT_OBJS = [24, 26, 28, 30, 31, 32]  # backpack, handbag, tie?, suitcase, frisbee?, skis?


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("abandon_seconds", 45))
        self.classes = self.settings.get("object_classes", DEFAULT_OBJS)
        self._objects = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("public")
        if not zone:
            return
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(self.classes)):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            key = (camera["id"], tid)
            self._objects.setdefault(key, {"since": ts, "pos": (cx, cy)})
            st = self._objects[key]
            moved = ((cx - st["pos"][0]) ** 2 + (cy - st["pos"][1]) ** 2) ** 0.5
            if moved > 0.03:
                st["since"] = ts
                st["pos"] = (cx, cy)
                continue
            near_person = any(abs(cx - pcx) < 0.08 and abs(cy - pcy) < 0.12 for (_, pcx, pcy, *_r, _t) in persons)
            if not near_person and ts - st["since"] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Stationary object review",
                    detail=f"Object track had limited image-space movement for {ts - st['since']:.0f}s with no nearby person-class detection on {camera['name']}.",
                    frame=frame, meta={"seconds": ts - st["since"]})
                self._objects.pop(key, None)
