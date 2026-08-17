"""Compares credentialed door passages with observed directional crossings.

Access counts how many credentials were accepted at the door across the site
day. The camera counts how many people crossed the configured line in each
direction. At the summary hour the two totals are reported side by side so a
discrepancy is visible; neither total is treated as ground truth.
"""
from marketplace.access import GRANTED, AccessEventFeed
from marketplace.contract import (
    MarketplaceFunction,
    boxes_of,
    crossed_line,
    site_time,
)

MANIFEST = {
    "id": "occupancy-reconciliation",
    "name": "Occupancy Reconciliation",
    "tagline": "Reports the site-day difference between credentialed door passages counted by Access and directional person crossings counted on the configured line.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose credential grants are counted.",
        "count_line": "Two-point line across the doorway that person crossings are counted against.",
        "summary_hour": "Site-local hour at which the daily reconciliation is emitted (default 23).",
        "min_difference": "Smallest absolute difference between the two totals that is reported (default 2).",
        "person_confidence": "Person-detection confidence used for crossing counts (default 0.45).",
    },
}

POLL_WINDOW_SECONDS = 60.0
MAX_TRACKED_POSITIONS = 256


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.summary_hour = int(self.settings.get("summary_hour", 23))
        self.min_difference = max(1, int(self.settings.get("min_difference", 2)))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self._feed = AccessEventFeed(self.settings.get("door_id"), (GRANTED,))
        self._previous = {}
        self._day = None
        self._reported_day = None
        self._credentials = 0
        self._inbound = 0
        self._outbound = 0

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("count_line")
        if not line or len(line) != 2:
            return

        local = site_time(ts, ctx)
        day = f"{local.tm_year:04d}-{local.tm_mon:02d}-{local.tm_mday:02d}"
        if self._day != day:
            self._day = day
            self._credentials = 0
            self._inbound = 0
            self._outbound = 0
            self._previous.clear()

        self._credentials += len(self._feed.poll(ctx, ts, POLL_WINDOW_SECONDS))

        for (_cls, cx, cy, *_rest, track_id) in boxes_of(frame, classes=[0], conf=self.conf):
            if track_id is None:
                continue
            previous = self._previous.get(track_id)
            self._previous[track_id] = (cx, cy)
            if previous is None:
                continue
            direction = crossed_line(previous, (cx, cy), line)
            if direction > 0:
                self._inbound += 1
            elif direction < 0:
                self._outbound += 1
        while len(self._previous) > MAX_TRACKED_POSITIONS:
            self._previous.pop(next(iter(self._previous)))

        if local.tm_hour != self.summary_hour or self._reported_day == day:
            return
        self._reported_day = day
        crossings = self._inbound + self._outbound
        difference = crossings - self._credentials
        if abs(difference) < self.min_difference:
            return
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Access and camera passage counts differ",
            detail=(
                f"{self._credentials} credentialed passage(s) counted by Access against {crossings} observed "
                f"crossing(s) on {camera['name']} ({self._inbound} inbound, {self._outbound} outbound) for {day}; "
                f"difference {difference:+d}."
            ),
            frame=None,
            meta={
                "day": day,
                "credentialed_passages": self._credentials,
                "observed_crossings": crossings,
                "inbound_crossings": self._inbound,
                "outbound_crossings": self._outbound,
                "difference": difference,
            },
        )
