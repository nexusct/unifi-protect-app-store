"""Sink-zone visit sequence check.

Checks whether the same visual track was recently observed in the configured
sink zone before protected-zone entry. It does not verify handwashing.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "hand-hygiene",
    "name": "Sink-Stop Sequence Check",
    "tagline": "Flags protected-zone entry when the same track was not recently observed in the configured sink zone; it does not verify handwashing.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "sink_zone": "polygon — handwash/sanitizer station",
        "protected_zone": "polygon — kitchen line / patient room",
        "window_seconds": "Maximum time between an observed station-zone visit and protected-zone entry (default: 120 seconds).",
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
                        title="Sink-zone visit not observed",
                        detail=f"A person track entered the protected zone on {camera['name']}; the same track was not observed in the sink zone during the prior {self.window:.0f}s. Review required.",
                        frame=frame, meta={"track": tid})
                    self._sink_visits[tid] = ts  # don't spam per frame
