"""Shelter Census — overnight bunk-area headcount.

Quiet-hours person count in the bunk zone at the census hour. Shelters
report overnight census to funders daily; this automates it without
identifying anyone.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "shelter-census",
    "name": "Shelter Overnight Census",
    "tagline": "Tuesday census: 47. Reported to the funder automatically.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — bunk area",
        "census_hour": "int (default 2)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.census_hour = int(self.settings.get("census_hour", 2))
        self._done_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("bunks")
        if not zone:
            return
        tm = _t.gmtime(ts)
        if tm.tm_hour != self.census_hour:
            return
        day = _t.strftime("%Y-%m-%d", tm)
        if self._done_day == day:
            return
        self._done_day = day
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        ctx.alerts.fire(
            site=ctx.site, camera=camera, detector=MANIFEST["id"],
            title=f"Overnight census: {count}",
            detail=f"{count} persons in bunk area at census hour on {camera['name']}.",
            frame=None, meta={"census": count})
