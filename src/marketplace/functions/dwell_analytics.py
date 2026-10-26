"""Dwell Analytics — how long people spend in each zone.

Tracks person IDs through configured zones and accumulates dwell time,
emitting a daily per-zone summary (the data behind "which displays get
looked at" and "where do customers stall"). Data — not alerts — is the
product here; a daily digest alert carries the summary.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "dwell-analytics",
    "name": "Zone Dwell Analytics",
    "tagline": "Shows which configured zones receive visits and the observed dwell time.",
    "category": "Retail & QSR",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zones": "map of zone-name → polygon",
        "digest_hour": "int — hour (0-23) to emit daily summary (default 21)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 21))
        self._tracker = ZoneTracker()
        self._dwell = defaultdict(float)
        self._visitors = defaultdict(set)
        self._last_ts = {}
        self._last_digest_day = None

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        boxes = boxes_of(frame, classes=[0])
        seen = set()
        for (cls, cx, cy, *rest, tid) in boxes:
            if tid is None:
                continue
            seen.add(tid)
            last = self._last_ts.get(tid, ts)
            dt = max(0.0, ts - last)
            for name, poly in zones.items():
                _, dwell, st = self._tracker.update((camera["id"], name, tid), in_zone(cx, cy, poly), ts)
                if st["in"]:
                    self._dwell[name] += dt
                    self._visitors[name].add(tid)
            self._last_ts[tid] = ts
        import time as _t
        day = _t.strftime("%Y-%m-%d", site_time(ts, ctx))
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        if hour == self.digest_hour and self._last_digest_day != day and self._dwell:
            top = sorted(self._dwell.items(), key=lambda x: x[1], reverse=True)
            lines = [f"{n}: {v/60:.1f} min across {len(self._visitors[n])} visitors" for n, v in top]
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Daily dwell summary",
                detail=" | ".join(lines[:6]),
                frame=None, meta={"dwell_minutes": {n: round(v / 60, 2) for n, v in top},
                                  "visitors": {n: len(s) for n, s in self._visitors.items()}})
            self._dwell.clear(); self._visitors.clear()
            self._last_digest_day = day
