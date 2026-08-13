"""Table Turn Tracker — occupancy state per table for restaurants.

Each table zone flips occupied/free as persons arrive/leave. Emits
turn-time summaries (how long tables sat occupied, how long they sat
empty between parties) — the input to faster turns and honest wait quotes.
"""
import time as _t
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "table-turn",
    "name": "Table Turn Tracker",
    "tagline": "Which tables turn fast, which sit empty, and for how long.",
    "category": "Retail & QSR",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "tables": "map of table-name → polygon",
        "empty_alert_minutes": "int — table empty this long during open hours (default 45)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.empty_alert = float(self.settings.get("empty_alert_minutes", 45)) * 60
        self._state = defaultdict(lambda: {"occupied": False, "since": None})
        self._turns = defaultdict(list)

    def process(self, camera, frame, ts, ctx):
        tables = (camera.get("zones") or {}).get("tables") or {}
        if not tables:
            return
        boxes = boxes_of(frame, classes=[0])
        for name, poly in tables.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            st = self._state[(camera["id"], name)]
            if occupied and not st["occupied"]:
                if st["since"] is not None:
                    self._turns[name].append(("empty", ts - st["since"]))
                st["occupied"] = True; st["since"] = ts
            elif not occupied and st["occupied"]:
                self._turns[name].append(("occupied", ts - st["since"]))
                st["occupied"] = False; st["since"] = ts
            elif not occupied and st["since"] and ts - st["since"] >= self.empty_alert:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Table {name} empty {(ts - st['since'])/60:.0f} min",
                    detail=f"Table {name} on {camera['name']} has sat unseated past threshold.",
                    frame=None, meta={"table": name})
                st["since"] = ts  # re-arm
