"""Wrong-Way Movement — one-way corridor enforcement.

Directional line-crossing: anyone crossing the line in the forbidden
direction fires an alert. Exit-only lanes, sterile corridors, one-way
retail aisles, secure-area egress paths.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "wrong-way",
    "name": "Wrong-Way Movement",
    "tagline": "Flags tracked movement across a configured one-way line in the prohibited direction for human review.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "line": "2-point crossing line",
        "forbidden": "'forward' or 'backward' — which crossing direction alerts",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.forbidden = -1 if self.settings.get("forbidden") == "backward" else 1
        self._prev = {}
        self._counted = set()

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("oneway_line")
        if not line or len(line) != 2:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None or tid in self._counted:
                continue
            d = crossed_line(prev, (cx, cy), line)
            if d == self.forbidden:
                self._counted.add(tid)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Wrong-way movement",
                    detail=f"Person crossed the one-way line in the forbidden direction on {camera['name']}.",
                    frame=frame, meta={"track": tid})
