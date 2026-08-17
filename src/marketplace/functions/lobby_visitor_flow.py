"""Lobby Visitor Flow — arrivals per hour at the front entrance.

Counts person entries through the lobby zone by hour. Property managers
get traffic patterns for staffing and tenant experience reporting;
security gets an anomaly baseline for free.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "lobby-visitor-flow",
    "name": "Lobby Visitor Flow",
    "tagline": "Summarizes estimated lobby occupancy patterns by configured time window.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "line": "2-point entry counting line",
        "digest_hour": "int (default 17)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 17))
        self._prev = {}
        self._counted = set()
        self._by_hour = defaultdict(int)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        line = (camera.get("zones") or {}).get("entry_line")
        if not line or len(line) != 2:
            return
        tm = site_time(ts, ctx)
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None or tid in self._counted:
                continue
            if crossed_line(prev, (cx, cy), line) > 0:
                self._counted.add(tid)
                self._by_hour[tm.tm_hour] += 1
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._by_hour:
            total = sum(self._by_hour.values())
            peak = max(self._by_hour.items(), key=lambda x: x[1])
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Lobby flow: {total} visitors, peak {peak[0]}:00",
                detail=f"{total} entries today on {camera['name']}; busiest hour {peak[0]}:00 ({peak[1]}).",
                frame=None, meta={"total": total, "by_hour": dict(self._by_hour)})
            self._by_hour.clear()
            self._last_day = day
