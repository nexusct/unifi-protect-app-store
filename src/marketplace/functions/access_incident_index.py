"""Local searchable index joining Access door events with observed analytics.

Every correlated door event is written to a bounded JSON-lines file with the
door, result kind, credential method, timestamp, and the counts the camera
observed. `search_records` answers structured questions over that file, such
as denied entry attempts at one entrance with two people observed.
"""
from marketplace.access import (
    AccessEventFeed,
    append_record,
    data_directory,
    describe,
    read_records,
)
from marketplace.contract import MarketplaceFunction, boxes_of

MANIFEST = {
    "id": "access-incident-index",
    "name": "Access Incident Search Index",
    "tagline": "Writes one bounded local index record per Access door event joining door, result kind, credential method, and timestamp with the counts observed on the correlated camera.",
    "category": "Security & Access",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name to index; unset indexes every door in the event buffer.",
        "sample_seconds": "Seconds of observation collected after each event before its record is written (default 10).",
        "max_records": "Newest index records kept in the local file (default 2000).",
        "summary_seconds": "Seconds between emitted index summaries (default 3600).",
        "person_confidence": "Person-detection confidence used for the indexed counts (default 0.45).",
        "include_actor": "Include the Access actor name in the index record (default false).",
    },
}

INDEX_DIRECTORY = "access-index"
INDEX_FILE = "incidents.jsonl"
PERSON = 0
VEHICLES = (2, 3, 5, 7)
MAX_OPEN_RECORDS = 64


def search_records(*, door=None, kinds=None, methods=None, min_people=None,
                   since=None, until=None, query=None, limit=50):
    """Filter the local index; returns the newest matching records first."""
    records = read_records(data_directory(INDEX_DIRECTORY), INDEX_FILE)
    wanted_kinds = {str(kind).casefold() for kind in kinds} if kinds else None
    wanted_methods = {str(method).casefold() for method in methods} if methods else None
    needle = str(query).casefold() if query else None
    matched = []
    for record in records:
        if door and str(door) not in (record.get("door_id"), record.get("door_name")):
            continue
        if wanted_kinds is not None and str(record.get("kind", "")).casefold() not in wanted_kinds:
            continue
        if wanted_methods is not None and str(record.get("method", "")).casefold() not in wanted_methods:
            continue
        if min_people is not None and int(record.get("max_people", 0)) < int(min_people):
            continue
        seconds = float(record.get("event_seconds") or 0)
        if since is not None and seconds < float(since):
            continue
        if until is not None and seconds > float(until):
            continue
        if needle is not None and needle not in " ".join(
            str(record.get(key, "")) for key in ("door_name", "door_id", "kind", "method", "camera_name")
        ).casefold():
            continue
        matched.append(record)
    matched.sort(key=lambda record: float(record.get("event_seconds") or 0), reverse=True)
    return matched[: max(1, int(limit))]


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("sample_seconds", 10)))
        self.max_records = max(1, int(self.settings.get("max_records", 2000)))
        self.summary_seconds = max(60.0, float(self.settings.get("summary_seconds", 3600)))
        self.conf = float(self.settings.get("person_confidence", 0.45))
        self.include_actor = bool(self.settings.get("include_actor", False))
        self._feed = AccessEventFeed(self.settings.get("door_id"))
        self._open = {}
        self._indexed_kinds = {}
        self._last_summary = None

    def _observe(self, frame):
        people = vehicles = 0
        for (cls, *_rest) in boxes_of(frame, conf=self.conf):
            if cls == PERSON:
                people += 1
            elif cls in VEHICLES:
                vehicles += 1
        return people, vehicles

    def process(self, camera, frame, ts, ctx):
        for seconds, kind, event in self._feed.poll(ctx, ts, self.window):
            record = describe(event, include_actor=self.include_actor)
            self._open[record["access_event_id"]] = {
                "record": record,
                "kind": kind,
                "started": seconds,
                "frames": 0,
                "max_people": 0,
                "max_vehicles": 0,
            }
        while len(self._open) > MAX_OPEN_RECORDS:
            self._open.pop(next(iter(self._open)))

        if self._open:
            people, vehicles = self._observe(frame)
            for state in self._open.values():
                state["frames"] += 1
                state["max_people"] = max(state["max_people"], people)
                state["max_vehicles"] = max(state["max_vehicles"], vehicles)

            for identifier, state in list(self._open.items()):
                if ts - state["started"] < self.window:
                    continue
                del self._open[identifier]
                self._write(camera, state)

        if self._last_summary is None:
            self._last_summary = ts
        elif ts - self._last_summary >= self.summary_seconds and self._indexed_kinds:
            self._emit_summary(camera, ctx)
            self._last_summary = ts

    def _write(self, camera, state):
        record = {
            **state["record"],
            "camera_id": camera["id"],
            "camera_name": camera["name"],
            "max_people": state["max_people"],
            "max_vehicles": state["max_vehicles"],
            "frames_analyzed": state["frames"],
        }
        append_record(
            data_directory(INDEX_DIRECTORY),
            INDEX_FILE,
            record,
            max_records=self.max_records,
        )
        self._indexed_kinds[state["kind"]] = self._indexed_kinds.get(state["kind"], 0) + 1

    def _emit_summary(self, camera, ctx):
        breakdown = dict(sorted(self._indexed_kinds.items()))
        total = sum(breakdown.values())
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title="Access index summary",
            detail=(
                f"{total} Access door event(s) indexed for {camera['name']}: "
                + ", ".join(f"{kind.replace('_', ' ')}: {count}" for kind, count in breakdown.items())
                + "."
            ),
            frame=None,
            meta={"indexed": total, "by_kind": breakdown, "max_records": self.max_records},
        )
        self._indexed_kinds = {}
