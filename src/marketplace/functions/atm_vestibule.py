"""ATM Vestibule Watch — lingering at the ATM outside branch hours.

Person in the ATM zone past a dwell limit during closed hours, or a
second person hovering during a transaction (shoulder-surf pattern).
Banks and credit unions buy this for cardholder safety + liability.
"""
from marketplace.contract import site_time, MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "atm-vestibule-watch",
    "name": "ATM Vestibule Watch",
    "tagline": "Flags overlapping person detections in a configured ATM vestibule for branch-security review.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — ATM area",
        "closed_hours": "[start,end] (default [22,6])",
        "dwell_minutes": "int (default 5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("closed_hours", [22, 6])
        self.dwell = float(self.settings.get("dwell_minutes", 5)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("atm")
        if not zone:
            return
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        s, e = int(self.hours[0]), int(self.hours[1])
        closed = (hour >= s or hour < e) if s > e else (s <= hour < e)
        boxes = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        if closed and len(boxes) >= 2:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Multiple persons at ATM after hours",
                detail=f"{len(boxes)} people in ATM zone on {camera['name']} during closed hours.",
                frame=frame, meta={"persons": len(boxes)})
        for (cls, cx, cy, *rest, tid) in boxes:
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, _, st = self._tracker.update(key, True, ts)
            if closed and st["since"] and ts - st["since"] >= self.dwell and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Extended ATM vestibule dwell",
                    detail=f"Person at ATM {(ts - st['since'])/60:.0f} min during closed hours on {camera['name']}.",
                    frame=frame, meta={"dwell_min": (ts - st['since']) / 60})
        # clear tracker for people who left
        present = {b[7] for b in boxes if b[7] is not None}
        for key in list(self._tracker.state):
            if key[0] == camera["id"] and key[1] not in present:
                self._tracker.update(key, False, ts)
                self._alerted.discard(key)
