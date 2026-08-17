"""Detector 9: credential/person-count correlation at a door.

When UniFi Access reports an explicit credential grant for the correlated door,
count visible person detections in the following window. A count above the
configured allowance produces a review snapshot; it does not identify which
person presented a credential or determine authorization.
"""
from detectors.base import Detector, register
from marketplace.contract import boxes_of


@register
class TailgatingDetector(Detector):
    name = "tailgating"

    def __init__(self, settings):
        super().__init__(settings)
        self.door_id = self.settings.get("door_id")
        self.window = float(self.settings.get("window_seconds", 6))
        self.max_per_badge = int(self.settings.get("max_persons_per_badge", 1))
        self._badges = []       # recent badge timestamps for our door
        self._seen_events = set()

    def process(self, camera, frame, ts, ctx):
        # Pull new badge events for our door from the shared access buffer
        valid_events = []
        for ev in list(ctx.access_events):
            if ev.get("credential_granted") is not True:
                continue
            ev_ts = (ev.get("ts") or 0) / 1000.0
            if ev.get("door_id") != self.door_id or ev_ts <= 0 or not 0 <= ts - ev_ts <= self.window:
                continue
            event_id = ev.get("id") or ev.get("event_id") or f"{self.door_id}:{ev.get('ts')}"
            valid_events.append((ev_ts, str(event_id)))
        for ev_ts, event_id in sorted(valid_events):
            if event_id not in self._seen_events:
                self._seen_events.add(event_id)
                self._badges.append(ev_ts)
        self._badges = sorted(badge for badge in self._badges if 0 <= ts - badge <= self.window)

        if not self._badges:
            return
        # Only count during the window after the latest badge
        latest = self._badges[-1]

        count = len(
            boxes_of(
                frame,
                classes=[0],
                conf=0.45,
                tracking_scope=(camera["id"], self.name),
            )
        )
        badge_count = len(self._badges)
        allowance = self.max_per_badge * badge_count
        if count > allowance:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=self.name,
                title="Credential/person-count mismatch",
                detail=f"{count} visible person detections at {camera['name']} versus an allowance of {allowance} across {badge_count} explicit credential grant(s) within {self.window:.0f}s. Review the Access and video records together.",
                frame=frame,
                meta={"persons": count, "badges": badge_count, "allowance": allowance, "door_id": self.door_id},
            )
            self._badges = []  # re-arm after alert
