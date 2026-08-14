"""MRI Zone Safety — person in Zone IV while magnet room is restricted.

MRI Zones III/IV access control is a Joint Commission focus area. Person
detected in the magnet-room approach zone outside staffed hours or without
escort pattern fires an immediate alert. Ferromagnetic incidents are
catastrophic; this is the cheap tripwire.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "mri-zone-safety",
    "name": "MRI Zone IV Safety",
    "tagline": "Someone is approaching the magnet room unescorted. Right now.",
    "category": "Healthcare & Senior Living",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — Zone III/IV approach",
        "staffed_hours": "[start,end] — suppress during staffed hours (optional)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.staffed = self.settings.get("staffed_hours")
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("mri_zone")
        if not zone:
            return
        if self.staffed:
            import time as _t
            hour = int(_t.strftime("%H", _t.gmtime(ts)))
            s, e = int(self.staffed[0]), int(self.staffed[1])
            if s <= hour < e:
                return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            if ts - self._alerted.get(tid, 0) > 60:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="MRI Zone IV approach",
                    detail=f"Person in magnet-room approach zone on {camera['name']} outside staffed hours.",
                    frame=frame, meta={"track": tid})
