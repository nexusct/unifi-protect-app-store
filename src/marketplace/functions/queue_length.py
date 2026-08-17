"""Checkout/service queue person-count estimate.

Counts persons inside a queue zone; when the count exceeds the threshold
for `hold_seconds`, emits a staff review alert.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "queue-length",
    "name": "Queue Length Monitor",
    "tagline": "Flags sustained person-count estimates above a configured queue threshold for staff review.",
    "category": "Retail & QSR",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — queue area (normalized)",
        "max_length": "int — persons before alert (default 4)",
        "hold_seconds": "int — sustained duration (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_len = int(self.settings.get("max_length", 4))
        self.hold = float(self.settings.get("hold_seconds", 30))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("queue")
        if not zone:
            return
        boxes = boxes_of(frame, classes=[0])
        count = sum(1 for (_, cx, cy, *_r) in boxes if in_zone(cx, cy, zone))
        key = camera["id"]
        if count >= self.max_len:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=self.manifest_id(),
                    title=f"Queue count estimate: {count}",
                    detail=f"{count} people in queue zone on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"queue_length": count})
                self._since[key] = ts
        else:
            self._since.pop(key, None)

    def manifest_id(self):
        return MANIFEST["id"]
