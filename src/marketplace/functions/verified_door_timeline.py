"""One consolidated review record per UniFi Access door event.

Access supplies the door event (granted, denied, forced-open, held-open,
doorbell, remote unlock). This module attaches what the correlated camera
observed during the review window so every door event lands in one place.
"""
from marketplace.access import KINDS, AccessEventFeed, describe
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "verified-door-timeline",
    "name": "Verified Door Incident Timeline",
    "tagline": "Joins each configured Access door event with the person counts observed on the correlated camera during the review window and emits one consolidated record.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name to correlate; unset correlates every door in the event buffer.",
        "door_zone": "Polygon for the doorway area counted during the review window; unset counts the whole frame.",
        "review_seconds": "Seconds of observation collected after each door event before the record is emitted (default 12).",
        "event_kinds": "Access kinds to record from granted, denied, forced_open, held_open, doorbell, unlock_command, door_closed (default all).",
        "person_confidence": "Person-detection confidence used for the observed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

MAX_OPEN_RECORDS = 64


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("review_seconds", 12)))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(
            self.settings.get("door_id"),
            self._selected_kinds(self.settings.get("event_kinds")),
        )
        self._open = {}

    @staticmethod
    def _selected_kinds(configured):
        if not configured:
            return None
        wanted = {str(kind).strip().casefold() for kind in configured}
        return [kind for kind in KINDS if kind in wanted] or None

    def _observed_people(self, frame, zone):
        detections = boxes_of(frame, classes=[0], conf=self.conf)
        if not zone:
            return len(detections)
        return sum(1 for (_cls, cx, cy, *_rest) in detections if in_zone(cx, cy, zone))

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("door_zone")
        for seconds, kind, event in self._feed.poll(ctx, ts, self.window):
            record = describe(event, include_actor=self.include_actor)
            self._open[record["access_event_id"]] = {
                "record": record,
                "kind": kind,
                "started": seconds,
                "frames": 0,
                "people_at_event": None,
                "max_people": 0,
            }
        while len(self._open) > MAX_OPEN_RECORDS:
            self._open.pop(next(iter(self._open)))
        if not self._open:
            return

        observed = self._observed_people(frame, zone)
        for state in self._open.values():
            state["frames"] += 1
            state["max_people"] = max(state["max_people"], observed)
            if state["people_at_event"] is None:
                state["people_at_event"] = observed

        for identifier, state in list(self._open.items()):
            if ts - state["started"] < self.window:
                continue
            del self._open[identifier]
            self._emit(camera, frame, ctx, state)

    def _emit(self, camera, frame, ctx, state):
        record = state["record"]
        label = state["kind"].replace("_", " ")
        door = record["door_name"] or record["door_id"] or "the configured door"
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title=f"Door event recorded: {label}",
            detail=(
                f"Access reported {label} at {door}; {state['people_at_event']} person(s) observed on "
                f"{camera['name']} on the first analyzed frame and up to {state['max_people']} across "
                f"{state['frames']} analyzed frame(s) in the {self.window:.0f}s review window."
            ),
            frame=frame,
            meta={
                **record,
                "people_at_event": state["people_at_event"],
                "max_people": state["max_people"],
                "frames_analyzed": state["frames"],
                "review_seconds": self.window,
            },
        )
