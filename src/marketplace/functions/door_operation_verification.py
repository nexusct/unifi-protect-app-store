"""Observed outcome of the doorway after a remote unlock command.

Access records that the unlock command was issued. This module reports what
the camera observed in the verification window: whether a person crossed the
doorway line, how far the door zone drifted from its pre-command reference,
and whether it was still different from that reference when the window closed.
"""
import numpy as np

from marketplace.access import UNLOCK_COMMAND, AccessEventFeed, describe
from marketplace.contract import (
    MarketplaceFunction,
    boxes_of,
    crossed_line,
    pixel_box,
)

MANIFEST = {
    "id": "door-operation-verification",
    "name": "Door Operation Verification",
    "tagline": "After a remote unlock command, reports whether a person crossed the doorway line and how far the door zone drifted from its pre-command reference during the verification window.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose unlock commands open the verification window.",
        "door_line": "Two-point line across the doorway that person crossings are counted against.",
        "door_zone": "Polygon for the door leaf area compared against its pre-command reference.",
        "verify_seconds": "Seconds of observation collected after the unlock command before the record is emitted (default 20).",
        "change_threshold": "Normalized frame-difference above which the door zone is reported as changed (default 0.06).",
        "person_confidence": "Person-detection confidence used for crossing counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

MAX_TRACKED_POSITIONS = 256


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("verify_seconds", 20)))
        self.threshold = float(self.settings.get("change_threshold", 0.06))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"), (UNLOCK_COMMAND,))
        self._active = None
        self._previous = {}

    @staticmethod
    def _zone_crop(frame, zone):
        import cv2

        xs = [point[0] for point in zone]
        ys = [point[1] for point in zone]
        left, top, right, bottom = pixel_box(frame, min(xs), min(ys), max(xs), max(ys))
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return None
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _difference(reference, crop):
        import cv2

        if reference is None or crop is None or reference.shape != crop.shape:
            return None
        return float(np.mean(cv2.absdiff(crop, reference))) / 255.0

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("door_line")
        zone = (camera.get("zones") or {}).get("door_zone")
        if not line or len(line) != 2:
            return

        for seconds, _kind, event in self._feed.poll(ctx, ts, self.window):
            self._active = {
                "record": describe(event, include_actor=self.include_actor),
                "started": seconds,
                "frames": 0,
                "crossings": 0,
                "reference": None,
                "peak_change": 0.0,
                "final_change": None,
            }
            self._previous.clear()
        if self._active is None:
            return

        state = self._active
        state["frames"] += 1
        for (_cls, cx, cy, *_rest, track_id) in boxes_of(frame, classes=[0], conf=self.conf):
            if track_id is None:
                continue
            previous = self._previous.get(track_id)
            self._previous[track_id] = (cx, cy)
            if previous is not None and crossed_line(previous, (cx, cy), line) != 0:
                state["crossings"] += 1
        while len(self._previous) > MAX_TRACKED_POSITIONS:
            self._previous.pop(next(iter(self._previous)))

        if zone:
            crop = self._zone_crop(frame, zone)
            if state["reference"] is None:
                state["reference"] = crop
            else:
                change = self._difference(state["reference"], crop)
                if change is not None:
                    state["peak_change"] = max(state["peak_change"], change)
                    state["final_change"] = change

        if ts - state["started"] < self.window:
            return
        self._active = None
        self._previous.clear()
        self._emit(camera, frame, ctx, state)

    def _emit(self, camera, frame, ctx, state):
        record = state["record"]
        door = record["door_name"] or record["door_id"] or "the configured door"
        final = state["final_change"]
        still_changed = final is not None and final > self.threshold
        if state["final_change"] is None:
            zone_summary = "no door-zone reference was configured"
        elif still_changed:
            zone_summary = f"the door zone still differs from its reference at {final:.3f}"
        else:
            zone_summary = f"the door zone returned to its reference at {final:.3f}"
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Unlock command outcome observed",
            detail=(
                f"Access issued an unlock command at {door}. Over {self.window:.0f}s on {camera['name']} the camera "
                f"counted {state['crossings']} doorway crossing(s) across {state['frames']} analyzed frame(s), "
                f"peak door-zone change {state['peak_change']:.3f}, and {zone_summary}."
            ),
            frame=frame,
            meta={
                **record,
                "crossings": state["crossings"],
                "frames_analyzed": state["frames"],
                "peak_zone_change": round(state["peak_change"], 4),
                "final_zone_change": None if final is None else round(final, 4),
                "zone_changed_at_close": still_changed,
                "change_threshold": self.threshold,
                "verify_seconds": self.window,
            },
        )
