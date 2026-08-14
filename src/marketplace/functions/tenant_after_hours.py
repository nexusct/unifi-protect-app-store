"""Tenant After-Hours — per-tenant-zone presence outside lease hours.

Each tenant suite zone watches itself after its configured hours. Property
managers deliver per-tenant security as an amenity — and document it.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "tenant-after-hours",
    "name": "Per-Tenant After-Hours Watch",
    "tagline": "Suite 410's zone, suite 410's hours, suite 410's alerts.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "suites": "map of suite-name → {polygon, hours: [start,end]}",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        suites = (camera.get("zones") or {}).get("suites") or {}
        if not suites:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        for name, spec in suites.items():
            poly = spec.get("polygon") or spec.get("zone")
            hrs = spec.get("hours", [8, 18])
            if not poly:
                continue
            s, e = int(hrs[0]), int(hrs[1])
            open_now = (s <= hour < e) if s < e else (hour >= s or hour < e)
            if open_now:
                continue
            for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
                if tid is None or not in_zone(cx, cy, poly):
                    continue
                key = (camera["id"], name, tid)
                if ts - self._alerted.get(key, 0) > 900:
                    self._alerted[key] = ts
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"After-hours presence: {name}",
                        detail=f"Person in {name} suite zone outside {s}:00-{e}:00 on {camera['name']}.",
                        frame=frame, meta={"suite": name})
