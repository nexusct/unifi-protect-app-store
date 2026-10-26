"""Operator review context for a doorbell or access-request event.

When Access reports a doorbell press or access request, this module collects
what the camera observed during the review window — people, carried-item
classes, and vehicles — and emits one record for an operator to read before
deciding. It never sends an unlock command; door control stays with the
authenticated /unlock route.
"""
from marketplace.access import DOORBELL, AccessEventFeed, describe
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "visitor-entry-review",
    "name": "Visitor Entry Review Context",
    "tagline": "Collects the people, carried-item classes, and vehicles observed after a doorbell or access-request event and emits one operator review record; it never unlocks a door.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose doorbell or access-request events open the review window.",
        "door_zone": "Polygon for the entry area that observations are limited to; unset uses the whole frame.",
        "review_seconds": "Seconds of observation collected after the event before the record is emitted (default 20).",
        "detection_confidence": "Detection confidence used for the observed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

PERSON = 0
CARRIED_ITEMS = (24, 26, 28)  # backpack, handbag, suitcase
VEHICLES = (2, 3, 5, 7)
MAX_OPEN_REVIEWS = 32


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("review_seconds", 20)))
        self.conf = float(self.settings.get("detection_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"), (DOORBELL,))
        self._open = {}

    def _observe(self, frame, zone):
        people = items = vehicles = 0
        for (cls, cx, cy, *_rest) in boxes_of(frame, conf=self.conf):
            if zone and not in_zone(cx, cy, zone):
                continue
            if cls == PERSON:
                people += 1
            elif cls in CARRIED_ITEMS:
                items += 1
            elif cls in VEHICLES:
                vehicles += 1
        return people, items, vehicles

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("door_zone")
        for seconds, _kind, event in self._feed.poll(ctx, ts, self.window):
            record = describe(event, include_actor=self.include_actor)
            self._open[record["access_event_id"]] = {
                "record": record,
                "started": seconds,
                "frames": 0,
                "max_people": 0,
                "max_items": 0,
                "max_vehicles": 0,
            }
        while len(self._open) > MAX_OPEN_REVIEWS:
            self._open.pop(next(iter(self._open)))
        if not self._open:
            return

        people, items, vehicles = self._observe(frame, zone)
        for state in self._open.values():
            state["frames"] += 1
            state["max_people"] = max(state["max_people"], people)
            state["max_items"] = max(state["max_items"], items)
            state["max_vehicles"] = max(state["max_vehicles"], vehicles)

        for identifier, state in list(self._open.items()):
            if ts - state["started"] < self.window:
                continue
            del self._open[identifier]
            self._emit(camera, frame, ctx, state)

    def _emit(self, camera, frame, ctx, state):
        record = state["record"]
        door = record["door_name"] or record["door_id"] or "the configured door"
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Visitor entry review context",
            detail=(
                f"Access reported a doorbell or entry request at {door}. {camera['name']} observed up to "
                f"{state['max_people']} person(s), {state['max_items']} carried-item detection(s), and "
                f"{state['max_vehicles']} vehicle(s) across {state['frames']} analyzed frame(s). "
                f"Approval remains an operator decision."
            ),
            frame=frame,
            meta={
                **record,
                "max_people": state["max_people"],
                "max_carried_items": state["max_items"],
                "max_vehicles": state["max_vehicles"],
                "frames_analyzed": state["frames"],
                "review_seconds": self.window,
                "auto_unlock": False,
            },
        )
