"""Assembles one local export package per correlated Access door event.

Each package holds the original Access event id and metadata, the camera and
alert that carried the snapshot request, the analytics counts observed during
the sample window, and a review history that operators append to. Packages
are bounded by count and age so the local store stays predictable.
"""
import json

from marketplace.access import (
    KINDS,
    AccessEventFeed,
    data_directory,
    describe,
    prune_files,
    safe_component,
    write_package,
)
from marketplace.contract import MarketplaceFunction, boxes_of

MANIFEST = {
    "id": "access-evidence-package",
    "name": "Access Event Evidence Package",
    "tagline": "Builds one bounded local JSON package per Access door event holding the original event id and metadata, observed analytics counts, and an operator review history.",
    "category": "Security & Access",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "door_id": "Access door id or door name to package; unset packages every door in the event buffer.",
        "event_kinds": "Access kinds to package from granted, denied, forced_open, held_open, doorbell, unlock_command, door_closed (default all).",
        "sample_seconds": "Seconds of observation collected after each event before the package is written (default 12).",
        "max_packages": "Newest packages kept in the local package store (default 500).",
        "retention_days": "Days a package is kept before it is pruned (default 30).",
        "person_confidence": "Detection confidence used for the packaged counts (default 0.45).",
        "include_actor": "Include the Access actor name in the package (default false).",
    },
}

PACKAGE_DIRECTORY = "access-packages"
PERSON = 0
VEHICLES = (2, 3, 5, 7)
MAX_OPEN_RECORDS = 64


def package_path(package_id: str):
    """Return the local path a package id resolves to."""
    return data_directory(PACKAGE_DIRECTORY) / f"{safe_component(package_id)}.json"


def list_packages(limit: int = 50) -> list[dict]:
    """Return the newest stored packages first."""
    directory = data_directory(PACKAGE_DIRECTORY)
    paths = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    packages = []
    for path in paths[: max(1, int(limit))]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            packages.append(value)
    return packages


def record_review(package_id: str, *, reviewer: str, decision: str, note: str = "", at=None) -> dict:
    """Append one review entry to a stored package and return the package."""
    path = package_path(package_id)
    package = json.loads(path.read_text(encoding="utf-8"))
    history = package.setdefault("review", [])
    history.append({
        "reviewer": str(reviewer)[:120],
        "decision": str(decision)[:80],
        "note": str(note)[:500],
        "at": at,
    })
    write_package(path.parent, path.stem, package)
    return package


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = max(1.0, float(self.settings.get("sample_seconds", 12)))
        self.max_packages = max(1, int(self.settings.get("max_packages", 500)))
        self.retention_days = max(0.0, float(self.settings.get("retention_days", 30)))
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
        if not self._open:
            return

        people, vehicles = self._observe(frame)
        for state in self._open.values():
            state["frames"] += 1
            state["max_people"] = max(state["max_people"], people)
            state["max_vehicles"] = max(state["max_vehicles"], vehicles)

        for identifier, state in list(self._open.items()):
            if ts - state["started"] < self.window:
                continue
            del self._open[identifier]
            self._write(camera, frame, ts, ctx, state)

    def _write(self, camera, frame, ts, ctx, state):
        record = state["record"]
        label = state["kind"].replace("_", " ")
        door = record["door_name"] or record["door_id"] or "the configured door"
        snapshot_requested = frame is not None and camera.get("privacy_mode") != "skeleton"
        delivered = ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=MANIFEST["id"],
            title=f"Evidence package written: {label}",
            detail=(
                f"Packaged the Access {label} record at {door} with up to {state['max_people']} person(s) and "
                f"{state['max_vehicles']} vehicle(s) observed on {camera['name']} across "
                f"{state['frames']} analyzed frame(s)."
            ),
            frame=frame,
            meta={
                **record,
                "max_people": state["max_people"],
                "max_vehicles": state["max_vehicles"],
                "frames_analyzed": state["frames"],
            },
        )
        package = {
            "access_event": record,
            "camera": {"id": camera["id"], "name": camera["name"]},
            "observations": {
                "max_people": state["max_people"],
                "max_vehicles": state["max_vehicles"],
                "frames_analyzed": state["frames"],
                "sample_seconds": self.window,
            },
            "alert": {
                "detector": MANIFEST["id"],
                "delivered": bool(delivered),
                "snapshot_requested": snapshot_requested,
            },
            "review": [],
            "created_at": ts,
        }
        directory = data_directory(PACKAGE_DIRECTORY)
        write_package(directory, safe_component(record["access_event_id"]), package)
        prune_files(
            directory,
            "*.json",
            max_files=self.max_packages,
            retention_days=self.retention_days,
            now=ts,
        )
