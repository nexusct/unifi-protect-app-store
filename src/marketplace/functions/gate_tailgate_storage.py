"""Gate Tailgate (storage) — two vehicles through the gate on one code.

Vehicle crossing the gate line twice within the open window = tailgating
entry. Self-storage delinquency and auction-theft both start at the gate.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "gate-tailgate-storage",
    "name": "Storage Gate Tailgate",
    "tagline": "One code, two cars. The gate camera saw it.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "line": "2-point gate crossing line",
        "window_seconds": "int — second-crossing window (default 8)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = float(self.settings.get("window_seconds", 8))
        self._prev = {}
        self._crossings = []

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("gate_line")
        if not line or len(line) != 2:
            return
        self._crossings = [t for t in self._crossings if ts - t < self.window]
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None:
                continue
            if crossed_line(prev, (cx, cy), line) != 0:
                if self._crossings:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="Gate tailgate entry",
                        detail=f"Second vehicle through the gate within {self.window:.0f}s on {camera['name']}.",
                        frame=frame, meta={"track": tid})
                self._crossings.append(ts)
