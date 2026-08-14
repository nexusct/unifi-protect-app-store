"""Pump Turns — per-pump vehicle sessions per day.

Counts each vehicle session at each pump zone: the forecourt throughput
KPI. Feeds staffing, pump-maintenance prioritization, and site comparison
for multi-site operators.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "pump-turns",
    "name": "Pump Turn Counter",
    "tagline": "Pump 2 turned 41 cars today. Pump 5 turned 9. Now you know why the line forms.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "pumps": "map of pump-name → polygon",
        "digest_hour": "int (default 22)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 22))
        self._tracker = ZoneTracker()
        self._turns = defaultdict(int)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        pumps = (camera.get("zones") or {}).get("pumps") or {}
        if not pumps:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            for name, poly in pumps.items():
                entered, _, _ = self._tracker.update((camera["id"], name, tid), in_zone(cx, cy, poly), ts)
                if entered:
                    self._turns[name] += 1
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._turns:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Daily pump turns",
                detail=" | ".join(f"{n}: {c}" for n, c in sorted(self._turns.items())),
                frame=None, meta={"turns": dict(self._turns)})
            self._turns.clear()
            self._last_day = day
