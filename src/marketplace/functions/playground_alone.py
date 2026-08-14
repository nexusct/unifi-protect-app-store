"""Playground Alone — lone small person in outdoor area outside recess.

A child-height figure alone on the playground/field outside scheduled
recess windows (or after dismissal) fires a staff alert. The "kid left
behind at pickup" and "wandered off at recess" scenarios, covered.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "playground-alone",
    "name": "Playground Alone Alert",
    "tagline": "One small figure on the playground at 3:45pm. Someone should walk out there.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — playground/field",
        "recess_windows": "[[start,end],...] hours (default [[9,11],[13,14]])",
        "max_height_ratio": "float — child proxy (default 0.35)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("recess_windows", [[9, 11], [13, 14]])
        self.max_h = float(self.settings.get("max_height_ratio", 0.35))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("playground")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        in_recess = any(int(w[0]) <= hour < int(w[1]) for w in self.windows)
        if in_recess:
            self._since.clear()
            return
        h = frame.shape[0]
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        children = [b for b in persons if (b[5] - b[3]) / h <= self.max_h]
        key = camera["id"]
        if len(children) == 1 and len(persons) == 1:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= 120:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Lone child outside recess window",
                    detail=f"Single child-height figure on playground on {camera['name']} for 2+ minutes.",
                    frame=frame, meta={"minutes": (ts - self._since[key]) / 60})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
