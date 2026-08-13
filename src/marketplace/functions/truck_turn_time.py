"""Truck Turn Time — arrival-to-departure per carrier at the dock.

Vehicle track enters the yard zone → leaves the yard zone = turn time.
Per-carrier scorecards in the daily digest; detention-fee disputes end
with timestamps instead of arguments.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "truck-turn-time",
    "name": "Truck Turn Time",
    "tagline": "How long each truck actually sat at your dock — per carrier.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — yard/dock area",
        "slow_minutes": "int — alert threshold (default 120)",
    },
}

TRUCKS = (5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_minutes", 120)) * 60
        self._inside = {}
        self._turns = []

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("yard")
        if not zone:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(TRUCKS)):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            present.add(tid)
            self._inside.setdefault(tid, ts)
        for tid, entered in list(self._inside.items()):
            if tid not in present:
                dur = ts - entered
                del self._inside[tid]
                self._turns.append(dur)
                if dur >= self.slow:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Truck turn {dur/60:.0f} min",
                        detail=f"Truck sat {dur/60:.1f} min in yard on {camera['name']}.",
                        frame=frame, meta={"turn_minutes": round(dur / 60, 1)})
