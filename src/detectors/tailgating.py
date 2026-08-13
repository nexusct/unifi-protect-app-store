"""Detector 9: tailgating — badge event ↔ people count through the door.

When a UniFi Access badge/unlock event fires for the correlated door,
count persons crossing the frame in the following window_seconds. More
persons than max_persons_per_badge = tailgating alert with clip snapshot.
Degraded mode (no Access credentials): no badge events → detector idles.
"""
from detectors.base import Detector, get_model, register


@register
class TailgatingDetector(Detector):
    name = "tailgating"

    def __init__(self, settings):
        super().__init__(settings)
        self.door_id = self.settings.get("door_id")
        self.window = float(self.settings.get("window_seconds", 6))
        self.max_per_badge = int(self.settings.get("max_persons_per_badge", 1))
        self._model = None
        self._badges = []       # recent badge timestamps for our door
        self._last_event_ts = 0

    def process(self, camera, frame, ts, ctx):
        # Pull new badge events for our door from the shared access buffer
        for ev in list(ctx.access_events):
            ev_ts = (ev.get("ts") or 0) / 1000.0
            if ev.get("door_id") == self.door_id and ev_ts > self._last_event_ts and ts - ev_ts <= self.window:
                self._badges.append(ev_ts)
                self._last_event_ts = ev_ts
                self._persons_seen = 0

        if not self._badges:
            return
        # Only count during the window after the latest badge
        latest = self._badges[-1]
        if ts - latest > self.window:
            self._badges = [b for b in self._badges if ts - b <= self.window]
            return

        if self._model is None:
            self._model = get_model("yolov8n.pt")
        res = self._model(frame, verbose=False, conf=0.45, classes=[0])[0]
        count = len(res.boxes or [])
        if count > self.max_per_badge:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=self.name,
                title="Possible tailgating",
                detail=f"{count} persons through {camera['name']} on {self.max_per_badge} badge within {self.window:.0f}s.",
                frame=frame,
                meta={"persons": count, "badges": len(self._badges), "door_id": self.door_id},
            )
            self._badges = []  # re-arm after alert
