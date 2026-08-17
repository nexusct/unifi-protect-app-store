"""Credential grants versus directional person crossings at one doorway.

Counts how many people the camera observed crossing the configured doorway
line in the window after each explicit credential-grant event. It compares
counts only; it does not identify anyone and does not use face recognition.
"""
from marketplace.access import GRANTED, AccessEventFeed, describe
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "tailgating-correlation",
    "name": "Credential-to-Crossing Correlation",
    "tagline": "Counts directional person crossings of a configured doorway line in the window after each credential grant and flags windows with more crossings than the configured allowance.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name whose credential grants open the correlation window.",
        "door_line": "Two-point line across the doorway that person crossings are counted against.",
        "window_seconds": "Seconds after a credential grant during which crossings are attributed to it (default 12).",
        "inbound": "Crossing direction counted as an entry: forward or backward (default forward).",
        "crossings_per_grant": "Inbound crossings allowed per credential grant before review (default 1).",
        "person_confidence": "Person-detection confidence used for crossing counts (default 0.45).",
        "include_actor": "Include the Access actor name in the emitted record (default false).",
    },
}

BACKWARD = ("backward", "reverse", "-1", "out", "exit")
MAX_TRACKED_POSITIONS = 256


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("window_seconds", 12)))
        self.per_grant = max(1, int(self.settings.get("crossings_per_grant", 1)))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        direction = str(self.settings.get("inbound", "forward")).strip().casefold()
        self.direction = -1 if direction in BACKWARD else 1
        self._feed = AccessEventFeed(self.settings.get("door_id"), (GRANTED,))
        self._grants = []
        self._crossings = []
        self._previous = {}

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("door_line")
        if not line or len(line) != 2:
            return

        for seconds, _kind, event in self._feed.poll(ctx, ts, self.window):
            self._grants.append((seconds, describe(event, include_actor=self.include_actor)))
        self._grants = [item for item in self._grants if ts - item[0] <= self.window]
        self._crossings = [stamp for stamp in self._crossings if ts - stamp <= self.window]
        if not self._grants:
            # Positions go stale between windows; a reopened window counts
            # crossings from its own first analyzed frame.
            self._previous.clear()
            return

        for (_cls, cx, cy, *_rest, track_id) in boxes_of(frame, classes=[0], conf=self.conf):
            if track_id is None:
                continue
            previous = self._previous.get(track_id)
            self._previous[track_id] = (cx, cy)
            if previous is not None and crossed_line(previous, (cx, cy), line) == self.direction:
                self._crossings.append(ts)
        while len(self._previous) > MAX_TRACKED_POSITIONS:
            self._previous.pop(next(iter(self._previous)))

        allowance = self.per_grant * len(self._grants)
        if len(self._crossings) <= allowance:
            return
        record = self._grants[-1][1]
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="More doorway crossings than credential grants",
            detail=(
                f"{len(self._crossings)} inbound crossing(s) counted on {camera['name']} against an allowance of "
                f"{allowance} across {len(self._grants)} credential grant(s) within {self.window:.0f}s."
            ),
            frame=frame,
            meta={
                **record,
                "crossings": len(self._crossings),
                "grants": len(self._grants),
                "allowance": allowance,
                "window_seconds": self.window,
            },
        )
        self._grants = []
        self._crossings = []
