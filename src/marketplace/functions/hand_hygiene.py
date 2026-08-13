"""Hand Hygiene Compliance — sink-stop before zone entry.

Person enters a protected zone (kitchen line, patient room) — did their
track visit the sink/sanitizer zone within the prior window? No stop =
compliance gap. Healthcare surveyors and food-safety auditors both ask
for exactly this evidence.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "hand-hygiene",
    "name": "Hand Hygiene Compliance",
    "tagline": "Entered the kitchen without the sink stop. Logged.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "sink_zone": "polygon — handwash/sanitizer station",
        "protected_zone": "polygon — kitchen line / patient room",
        "window_seconds": "int — sink-within window (default 120)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = float(self.settings.get("window_seconds", 120))
        self._sink_visits = {}

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        sink, protected = zones.get("sink"), zones.get("protected")
        if not sink or not protected:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            if in_zone(cx, cy, sink):
                self._sink_visits[tid] = ts
            if in_zone(cx, cy, protected):
                last_sink = self._sink_visits.get(tid)
                if last_sink is None or ts - last_sink > self.window:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="Hygiene gap: no sink stop",
                        detail=f"Person entered protected zone on {camera['name']} without a sink visit in {self.window:.0f}s.",
                        frame=frame, meta={"track": tid})
                    self._sink_visits[tid] = ts  # don't spam per frame
