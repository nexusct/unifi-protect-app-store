"""Observed context during a forced-open or held-open Access door alarm.

The Access controller raises the door-state alarm. This module reports what
the camera observed while the alarm was open — people, vehicles, other
detected objects, and the longest continuous person dwell in the door zone —
so staff can tell a delivery or a maintenance visit from an unexplained one.
"""
from marketplace.access import DOOR_STATE_ALARMS, AccessEventFeed, describe
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "door-alarm-verification",
    "name": "Forced/Held-Open Video Verification",
    "tagline": "Summarizes the people, vehicles, other detected objects, and longest person dwell observed while an Access forced-open or held-open door alarm was active.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose door-state alarms open the observation window.",
        "door_zone": "Polygon for the door area that person dwell is measured in; unset measures the whole frame.",
        "observe_seconds": "Seconds of observation collected after the alarm before the summary is emitted (default 30).",
        "detection_confidence": "Detection confidence used for the observed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

PERSON = 0
VEHICLES = (2, 3, 5, 7)
MAX_OPEN_ALARMS = 32


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("observe_seconds", 30)))
        self.conf = float(self.settings.get("detection_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"), DOOR_STATE_ALARMS)
        self._zone_tracker = ZoneTracker()
        self._open = {}

    def _observe(self, frame, zone, ts):
        people = vehicles = objects = 0
        longest = 0.0
        for (cls, cx, cy, *_rest, track_id) in boxes_of(frame, conf=self.conf):
            inside = in_zone(cx, cy, zone) if zone else True
            if not inside:
                continue
            if cls == PERSON:
                people += 1
                _entered, dwell, _state = self._zone_tracker.update(track_id, True, ts)
                longest = max(longest, dwell)
            elif cls in VEHICLES:
                vehicles += 1
            else:
                objects += 1
        return people, vehicles, objects, longest

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("door_zone")
        for seconds, kind, event in self._feed.poll(ctx, ts, self.window):
            record = describe(event, include_actor=self.include_actor)
            self._open[record["access_event_id"]] = {
                "record": record,
                "kind": kind,
                "started": seconds,
                "frames": 0,
                "max_people": 0,
                "max_vehicles": 0,
                "max_objects": 0,
                "longest_dwell": 0.0,
            }
        while len(self._open) > MAX_OPEN_ALARMS:
            self._open.pop(next(iter(self._open)))
        if not self._open:
            return

        people, vehicles, objects, longest = self._observe(frame, zone, ts)
        for state in self._open.values():
            state["frames"] += 1
            state["max_people"] = max(state["max_people"], people)
            state["max_vehicles"] = max(state["max_vehicles"], vehicles)
            state["max_objects"] = max(state["max_objects"], objects)
            state["longest_dwell"] = max(state["longest_dwell"], longest)

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
            title=f"Door alarm observed: {label}",
            detail=(
                f"Access reported {label} at {door}. During {self.window:.0f}s on {camera['name']} the camera "
                f"observed up to {state['max_people']} person(s), {state['max_vehicles']} vehicle(s), and "
                f"{state['max_objects']} other detected object(s), with the longest person dwell at "
                f"{state['longest_dwell']:.0f}s across {state['frames']} analyzed frame(s)."
            ),
            frame=frame,
            meta={
                **record,
                "max_people": state["max_people"],
                "max_vehicles": state["max_vehicles"],
                "max_objects": state["max_objects"],
                "longest_dwell_seconds": round(state["longest_dwell"], 1),
                "frames_analyzed": state["frames"],
                "observe_seconds": self.window,
            },
        )
