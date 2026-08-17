"""Med Spa Room Turn — treatment-room cycle time between clients.

Occupied → empty → occupied timing per treatment room. Clinics optimize
room turns like restaurants optimize tables; this measures the actual
turn time and idle gaps.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "medspa-room-turn",
    "name": "Treatment Room Turn",
    "tagline": "Measures occupied and idle intervals for configured treatment-room zones.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "rooms": "map of room-name → polygon",
        "idle_alert_minutes": "int (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.idle_limit = float(self.settings.get("idle_alert_minutes", 30)) * 60
        self._state = defaultdict(lambda: {"occupied": False, "since": None})
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        rooms = (camera.get("zones") or {}).get("rooms") or {}
        if not rooms:
            return
        boxes = boxes_of(frame, classes=[0])
        for name, poly in rooms.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            key = (camera["id"], name)
            st = self._state[key]
            if occupied and not st["occupied"]:
                st["occupied"] = True; st["since"] = ts
                self._alerted.discard(key)
            elif not occupied and st["occupied"]:
                st["occupied"] = False; st["since"] = ts
            elif not occupied and st["since"] and ts - st["since"] >= self.idle_limit and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Room {name} idle {(ts - st['since'])/60:.0f} min",
                    detail=f"Treatment room {name} unoccupied past idle threshold on {camera['name']}.",
                    frame=None, meta={"room": name})
