"""Observed context for a valid credential grant outside configured hours.

The credential was accepted by Access; this module only reports the unusual
conditions the camera observed alongside it — how many people, which way they
crossed, whether a vehicle was present, and how close the nearest second
person was. It does not classify the entry as unauthorized.
"""
from marketplace.access import GRANTED, AccessEventFeed, describe
from marketplace.contract import (
    MarketplaceFunction,
    boxes_of,
    crossed_line,
    site_time,
)

MANIFEST = {
    "id": "after-hours-entry-verification",
    "name": "After-Hours Entry Verification",
    "tagline": "Reports the person count, crossing direction, vehicle presence, and nearest second-person distance observed when a credential grant lands outside configured open hours.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose credential grants are checked against the schedule.",
        "door_line": "Two-point line across the doorway that crossing direction is counted against.",
        "open_hours": "Site-local [start, end] hours treated as open; grants outside them open a verification window (default [7, 19]).",
        "window_seconds": "Seconds of observation collected after the grant before the record is emitted (default 20).",
        "escort_distance": "Normalized frame distance under which a second person is reported as close by (default 0.25).",
        "person_confidence": "Person-detection confidence used for the observed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

VEHICLES = (2, 3, 5, 7)
MAX_TRACKED_POSITIONS = 256


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        hours = self.settings.get("open_hours", [7, 19])
        self.open_start, self.open_end = int(hours[0]), int(hours[1])
        self.window = max(1.0, float(self.settings.get("window_seconds", 20)))
        self.escort_distance = float(self.settings.get("escort_distance", 0.25))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"), (GRANTED,))
        self._active = None
        self._previous = {}

    def _outside_open_hours(self, ts, ctx):
        hour = site_time(ts, ctx).tm_hour
        if self.open_start > self.open_end:
            return self.open_end <= hour < self.open_start
        return not self.open_start <= hour < self.open_end

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("door_line")
        if not line or len(line) != 2:
            return

        for seconds, _kind, event in self._feed.poll(ctx, ts, self.window):
            if not self._outside_open_hours(seconds, ctx):
                continue
            self._active = {
                "record": describe(event, include_actor=self.include_actor),
                "started": seconds,
                "frames": 0,
                "max_people": 0,
                "inbound": 0,
                "outbound": 0,
                "vehicle_frames": 0,
                "closest_pair": None,
            }
            self._previous.clear()
        if self._active is None:
            return

        self._observe(frame, line)
        if ts - self._active["started"] >= self.window:
            state, self._active = self._active, None
            self._previous.clear()
            self._emit(camera, frame, ctx, state)

    def _observe(self, frame, line):
        state = self._active
        state["frames"] += 1
        centroids = []
        vehicles = 0
        for (cls, cx, cy, *_rest, track_id) in boxes_of(frame, conf=self.conf):
            if cls in VEHICLES:
                vehicles += 1
                continue
            if cls != 0:
                continue
            centroids.append((cx, cy))
            if track_id is None:
                continue
            previous = self._previous.get(track_id)
            self._previous[track_id] = (cx, cy)
            if previous is None:
                continue
            direction = crossed_line(previous, (cx, cy), line)
            if direction > 0:
                state["inbound"] += 1
            elif direction < 0:
                state["outbound"] += 1
        while len(self._previous) > MAX_TRACKED_POSITIONS:
            self._previous.pop(next(iter(self._previous)))
        if vehicles:
            state["vehicle_frames"] += 1
        state["max_people"] = max(state["max_people"], len(centroids))
        closest = self._closest_pair(centroids)
        if closest is not None:
            current = state["closest_pair"]
            state["closest_pair"] = closest if current is None else min(current, closest)

    @staticmethod
    def _closest_pair(centroids):
        if len(centroids) < 2:
            return None
        best = None
        for index, (ax, ay) in enumerate(centroids):
            for bx, by in centroids[index + 1:]:
                distance = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
                best = distance if best is None else min(best, distance)
        return best

    def _emit(self, camera, frame, ctx, state):
        record = state["record"]
        door = record["door_name"] or record["door_id"] or "the configured door"
        closest = state["closest_pair"]
        proximity = "no second person observed" if closest is None else f"nearest second person at {closest:.2f}"
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Credential grant outside configured open hours",
            detail=(
                f"Access granted at {door} outside the configured open hours. {camera['name']} observed up to "
                f"{state['max_people']} person(s), {state['inbound']} inbound and {state['outbound']} outbound "
                f"doorway crossing(s), a vehicle on {state['vehicle_frames']} of {state['frames']} analyzed "
                f"frame(s), and {proximity}."
            ),
            frame=frame,
            meta={
                **record,
                "max_people": state["max_people"],
                "inbound_crossings": state["inbound"],
                "outbound_crossings": state["outbound"],
                "vehicle_frames": state["vehicle_frames"],
                "frames_analyzed": state["frames"],
                "closest_person_distance": None if closest is None else round(closest, 3),
                "close_second_person": closest is not None and closest <= self.escort_distance,
                "window_seconds": self.window,
            },
        )
