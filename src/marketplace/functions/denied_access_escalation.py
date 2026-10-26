"""Groups repeated denied-credential events at one door into one review.

A single denied credential is routine. This module counts denials at the
configured door inside a rolling window and, once the configured threshold is
reached, emits one record carrying the observed person count and the longest
approach-zone dwell so the denial log becomes actionable instead of noisy.
"""
from marketplace.access import DENIED, AccessEventFeed, describe
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "denied-access-escalation",
    "name": "Denied-Access Escalation",
    "tagline": "Groups repeated denied-credential events at one door inside a rolling window and reports the observed person count and longest approach dwell once the threshold is reached.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose denied credentials are grouped.",
        "approach_zone": "Polygon for the approach area that person count and dwell are measured in; unset uses the whole frame.",
        "window_seconds": "Rolling window in which denials are grouped together (default 300).",
        "min_denials": "Denials required inside the window before a record is emitted (default 3).",
        "cooldown_seconds": "Minimum seconds between emitted records for the same door (default 600).",
        "person_confidence": "Person-detection confidence used for the observed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("window_seconds", 300)))
        self.min_denials = max(2, int(self.settings.get("min_denials", 3)))
        self.cooldown = max(0.0, float(self.settings.get("cooldown_seconds", 600)))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"), (DENIED,))
        self._zone_tracker = ZoneTracker()
        self._denials = []
        self._max_people = 0
        self._longest_dwell = 0.0
        self._last_emitted = None

    def _reset(self):
        self._denials = []
        self._max_people = 0
        self._longest_dwell = 0.0

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("approach_zone")
        for seconds, _kind, event in self._feed.poll(ctx, ts, self.window):
            self._denials.append((seconds, describe(event, include_actor=self.include_actor)))
        self._denials = [item for item in self._denials if ts - item[0] <= self.window]
        if not self._denials:
            self._reset()
            return

        people = 0
        for (_cls, cx, cy, *_rest, track_id) in boxes_of(frame, classes=[0], conf=self.conf):
            if zone and not in_zone(cx, cy, zone):
                continue
            people += 1
            _entered, dwell, _state = self._zone_tracker.update(track_id, True, ts)
            self._longest_dwell = max(self._longest_dwell, dwell)
        self._max_people = max(self._max_people, people)

        if len(self._denials) < self.min_denials:
            return
        if self._last_emitted is not None and ts - self._last_emitted < self.cooldown:
            return

        record = self._denials[-1][1]
        span = self._denials[-1][0] - self._denials[0][0]
        methods = sorted({item[1]["method"] for item in self._denials})
        door = record["door_name"] or record["door_id"] or "the configured door"
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Repeated denied credentials at one door",
            detail=(
                f"{len(self._denials)} denied credential event(s) at {door} within {span:.0f}s. "
                f"{camera['name']} observed up to {self._max_people} person(s) in the approach area with the "
                f"longest dwell at {self._longest_dwell:.0f}s. Credential method(s): {', '.join(methods)}."
            ),
            frame=frame,
            meta={
                **record,
                "denials": len(self._denials),
                "span_seconds": round(span, 1),
                "max_people": self._max_people,
                "longest_dwell_seconds": round(self._longest_dwell, 1),
                "methods": methods,
                "window_seconds": self.window,
            },
        )
        self._last_emitted = ts
        self._reset()
