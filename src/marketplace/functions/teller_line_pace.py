"""Teller Line Pace — branch queue + per-transaction timing.

Counts the teller line and measures customer dwell from join to counter.
Credit unions report service-level numbers to their boards — this produces
them without a queue-management system.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "teller-line-pace",
    "name": "Teller Line Pace",
    "tagline": "Average branch wait: 4:12 today. The board report writes itself.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — teller line",
        "digest_hour": "int (default 16)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 16))
        self._tracker = ZoneTracker()
        self._waits = []
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("line")
        if not zone:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, _, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"]:
                present.add(tid)
        for key, st in list(self._tracker.state.items()):
            if key[0] == camera["id"] and st["in"] and key[1] not in present and st["since"]:
                self._waits.append(ts - st["since"])
                st["in"] = False; st["since"] = None
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._waits:
            avg = sum(self._waits) / len(self._waits)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Branch waits: {len(self._waits)} served, {avg/60:.1f} min avg",
                detail=f"{len(self._waits)} customers served on {camera['name']}, average wait {avg/60:.1f} min.",
                frame=None, meta={"served": len(self._waits), "avg_min": round(avg / 60, 1)})
            self._waits = []
            self._last_day = day
