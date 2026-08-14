"""Viewing Room Privacy — entry to a viewing room outside scheduled visitation.

Funeral homes schedule visitations tightly; a person entering a viewing
room zone outside its scheduled window (preparation in progress, another
family's time) gets a quiet staff alert. Discretion and dignity, enforced.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "viewing-room-privacy",
    "name": "Viewing Room Privacy Window",
    "tagline": "Someone entered viewing room B during setup. Staff knew before the door opened.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — viewing room entry",
        "scheduled_windows": "[[start,end],...] hours open to visitors (default [])",
        "suppress_staff_hours": "[start,end] optional staff-only hours that never alert",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("scheduled_windows", [])
        self.staff = self.settings.get("suppress_staff_hours")
        self._tracker = ZoneTracker()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("viewing_room")
        if not zone:
            return
        import time as _t
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        if any(int(w[0]) <= hour < int(w[1]) for w in self.windows):
            return  # open to visitors — no alerts
        if self.staff and int(self.staff[0]) <= hour < int(self.staff[1]):
            return  # staff-only hours — preparation expected
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            entered, _, _ = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if entered:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Viewing room entry outside schedule",
                    detail=f"Person entered viewing room on {camera['name']} outside scheduled windows.",
                    frame=frame, meta={"track": tid})
