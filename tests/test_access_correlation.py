"""Contract tests for the Access ↔ Protect cross-system marketplace modules."""

from __future__ import annotations

import calendar
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.modules.setdefault("cv2", types.ModuleType("cv2"))

from marketplace import access
from marketplace.functions import (
    access_evidence_package,
    access_incident_index,
    after_hours_entry_verification,
    denied_access_escalation,
    door_alarm_verification,
    door_operation_verification,
    occupancy_reconciliation,
    tailgating_correlation,
    verified_door_timeline,
    visitor_entry_review,
)
from unifi_access import AccessPoller

NOW = 1_800_000_000.0

CROSS_SYSTEM_MODULES = (
    verified_door_timeline,
    tailgating_correlation,
    door_alarm_verification,
    denied_access_escalation,
    access_incident_index,
    access_evidence_package,
    after_hours_entry_verification,
    occupancy_reconciliation,
    visitor_entry_review,
    door_operation_verification,
)


class _Alerts:
    def __init__(self, result=True):
        self.events = []
        self.result = result

    def fire(self, **event):
        self.events.append(event)
        return self.result

    def stats(self):
        return {}


def context(events=(), *, alerts=None, timezone="America/Chicago"):
    return SimpleNamespace(
        site="Test Site",
        timezone=timezone,
        alerts=alerts if alerts is not None else _Alerts(),
        access_events=list(events),
    )


def door_event(kind_fields, *, seconds=NOW, door="door-main", identifier="event-1"):
    event = {"id": identifier, "ts": int(seconds * 1000), "door_id": door, "door_name": "Main Entry"}
    event.update(kind_fields)
    return event


def person(track_id, cx, cy):
    """One boxes_of tuple: (cls, cx, cy, x1, y1, x2, y2, track_id)."""
    return (0, cx, cy, cx - 0.05, cy - 0.1, cx + 0.05, cy + 0.1, track_id)


class AccessVocabularyTests(unittest.TestCase):
    def test_classify_reads_type_result_and_the_canonical_grant_flag(self):
        cases = {
            access.FORCED_OPEN: {"type": "dps_door_forced_open"},
            access.HELD_OPEN: {"type": "door_held_open_too_long"},
            access.DOORBELL: {"type": "access_doorbell_ring"},
            access.UNLOCK_COMMAND: {"type": "remote_unlock"},
            access.DENIED: {"type": "access_denied"},
            access.GRANTED: {"type": "access_granted"},
            access.DOOR_CLOSED: {"type": "door_relock"},
        }
        for expected, fields in cases.items():
            self.assertEqual(access.classify(door_event(fields)), expected, fields)

        self.assertEqual(access.classify({"type": "unknown", "result": "BLOCKED"}), access.DENIED)
        self.assertEqual(access.classify({"type": "unknown", "result": "ACCESS_GRANTED"}), access.GRANTED)
        self.assertEqual(access.classify(None), access.OTHER)

    def test_canonical_grant_flag_overrides_permissive_token_matching(self):
        # A firmware string containing "open" must not be promoted to a grant
        # when the Access poller explicitly said it was not a credential grant.
        event = {"type": "door_position_opened", "credential_granted": False}
        self.assertEqual(access.classify(event), access.OTHER)
        self.assertEqual(access.classify({"type": "vendor_specific", "credential_granted": True}), access.GRANTED)

    def test_poller_normalization_feeds_the_shared_vocabulary(self):
        hit = {
            "_id": "evt-9",
            "event_time": int(NOW * 1000),
            "door": {"id": "door-main", "name": "Main Entry"},
            "event_type": "access.door.unlock",
            "result": "ACCESS_GRANTED",
            "authentication": {"credential_provider": "NFC"},
            "actor": {"id": "user-3", "name": "Operator"},
        }
        event = AccessPoller._normalize(hit)
        self.assertEqual(event["id"], "evt-9")
        self.assertEqual(event["door_id"], "door-main")
        self.assertEqual(access.event_seconds(event), NOW)
        self.assertEqual(access.method_of(event), "nfc")
        self.assertEqual(access.actor_of(event), "Operator")
        self.assertEqual(access.event_id(event), "evt-9")

    def test_event_seconds_accepts_millisecond_and_second_timestamps(self):
        self.assertEqual(access.event_seconds({"ts": int(NOW * 1000)}), NOW)
        self.assertEqual(access.event_seconds({"ts": NOW}), NOW)
        self.assertEqual(access.event_seconds({"ts": 0}), 0.0)
        self.assertEqual(access.event_seconds({"ts": "not-a-time"}), 0.0)

    def test_describe_keeps_the_actor_name_opt_in(self):
        event = door_event({"type": "access_granted", "user": "Operator"})
        self.assertNotIn("actor", access.describe(event))
        self.assertEqual(access.describe(event, include_actor=True)["actor"], "Operator")

    def test_feed_deduplicates_filters_by_door_kind_and_window(self):
        feed = access.AccessEventFeed("door-main", (access.GRANTED,))
        events = [
            door_event({"type": "access_granted"}, identifier="a"),
            door_event({"type": "access_granted"}, identifier="b", door="door-other"),
            door_event({"type": "access_denied"}, identifier="c"),
            door_event({"type": "access_granted"}, identifier="d", seconds=NOW - 500),
        ]
        ctx = context(events)
        first = feed.poll(ctx, NOW, 60)
        self.assertEqual([item[2]["id"] for item in first], ["a"])
        self.assertEqual(feed.poll(ctx, NOW, 60), [])

    def test_feed_without_a_door_id_accepts_every_door(self):
        feed = access.AccessEventFeed()
        events = [
            door_event({"type": "access_granted"}, identifier="a", door="door-a"),
            door_event({"type": "access_denied"}, identifier="b", door="door-b"),
        ]
        self.assertEqual(len(feed.poll(context(events), NOW, 60)), 2)

    def test_feed_seen_table_stays_bounded(self):
        feed = access.AccessEventFeed(max_seen=16)
        events = [door_event({"type": "access_granted"}, identifier=f"e{index}") for index in range(200)]
        feed.poll(context(events), NOW, 60)
        self.assertLessEqual(len(feed._seen), 16)

    def test_safe_component_neutralizes_path_traversal_identifiers(self):
        component = access.safe_component("../../etc/passwd")
        self.assertNotIn("/", component)
        self.assertNotIn("..", component.split("-")[0])
        self.assertNotEqual(component, access.safe_component("../../etc/passwdx"))


class LocalRecordStoreTests(unittest.TestCase):
    def test_data_directory_stays_inside_vision_data(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            self.assertTrue(access.data_directory("access-index").is_relative_to(Path(temporary).resolve()))
            with self.assertRaises(ValueError):
                access.data_directory("../escape")

    def test_append_record_trims_to_the_newest_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index in range(10):
                access.append_record(directory, "index.jsonl", {"n": index}, max_records=4)
            records = access.read_records(directory, "index.jsonl")
            self.assertEqual([record["n"] for record in records], [6, 7, 8, 9])

    def test_read_records_skips_unparsable_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "index.jsonl").write_text('{"n":1}\nnot json\n\n{"n":2}\n', encoding="utf-8")
            self.assertEqual([record["n"] for record in access.read_records(directory, "index.jsonl")], [1, 2])
            self.assertEqual(access.read_records(directory, "missing.jsonl"), [])

    def test_prune_files_bounds_by_count_and_age(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index in range(5):
                path = directory / f"package-{index}.json"
                path.write_text("{}", encoding="utf-8")
                os.utime(path, (100 + index, 100 + index))
            access.prune_files(directory, "*.json", max_files=2, retention_days=0, now=1_000)
            self.assertEqual(len(list(directory.glob("*.json"))), 2)


class VerifiedDoorTimelineTests(unittest.TestCase):
    def test_one_record_is_emitted_after_the_review_window_closes(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_denied"})], alerts=alerts)
        function = verified_door_timeline.Function({"door_id": "door-main", "review_seconds": 5})
        camera = {"id": "cam", "name": "Entry", "zones": {"door_zone": [[0, 0], [1, 0], [1, 1], [0, 1]]}}
        with patch.object(
            verified_door_timeline, "boxes_of",
            side_effect=[[person(1, 0.4, 0.5)], [person(1, 0.4, 0.5), person(2, 0.6, 0.5)]],
        ), patch.object(verified_door_timeline, "in_zone", return_value=True):
            function.process(camera, object(), NOW, ctx)
            self.assertEqual(alerts.events, [])
            function.process(camera, object(), NOW + 6, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["kind"], access.DENIED)
        self.assertEqual(meta["people_at_event"], 1)
        self.assertEqual(meta["max_people"], 2)
        self.assertEqual(meta["access_event_id"], "event-1")

    def test_configured_event_kinds_exclude_other_door_events(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_granted"})], alerts=alerts)
        function = verified_door_timeline.Function(
            {"door_id": "door-main", "review_seconds": 1, "event_kinds": ["denied"]}
        )
        camera = {"id": "cam", "name": "Entry"}
        with patch.object(verified_door_timeline, "boxes_of", return_value=[]):
            function.process(camera, object(), NOW, ctx)
            function.process(camera, object(), NOW + 2, ctx)
        self.assertEqual(alerts.events, [])

    def test_no_inference_runs_while_no_door_event_is_open(self):
        ctx = context()
        function = verified_door_timeline.Function({"door_id": "door-main"})
        with patch.object(verified_door_timeline, "boxes_of") as boxes:
            function.process({"id": "cam", "name": "Entry"}, object(), NOW, ctx)
        boxes.assert_not_called()


class TailgatingCorrelationTests(unittest.TestCase):
    CAMERA = {"id": "cam", "name": "Entry", "zones": {"door_line": [[0, 0.5], [1, 0.5]]}}

    def _run(self, function, ctx, frames):
        with patch.object(tailgating_correlation, "boxes_of", side_effect=frames):
            for index in range(len(frames)):
                function.process(self.CAMERA, object(), NOW + index, ctx)

    def test_crossings_beyond_the_grant_allowance_are_flagged(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_granted"})], alerts=alerts)
        function = tailgating_correlation.Function({"door_id": "door-main", "window_seconds": 30})
        self._run(function, ctx, [
            [person(1, 0.4, 0.3), person(2, 0.6, 0.3)],
            [person(1, 0.4, 0.7), person(2, 0.6, 0.7)],
        ])
        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual((meta["crossings"], meta["grants"], meta["allowance"]), (2, 1, 1))

    def test_crossings_within_the_allowance_stay_quiet(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_granted"})], alerts=alerts)
        function = tailgating_correlation.Function({"door_id": "door-main", "window_seconds": 30})
        self._run(function, ctx, [[person(1, 0.4, 0.3)], [person(1, 0.4, 0.7)]])
        self.assertEqual(alerts.events, [])

    def test_crossings_without_a_credential_grant_are_not_counted(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_denied"})], alerts=alerts)
        function = tailgating_correlation.Function({"door_id": "door-main", "window_seconds": 30})
        with patch.object(tailgating_correlation, "boxes_of") as boxes:
            function.process(self.CAMERA, object(), NOW, ctx)
            function.process(self.CAMERA, object(), NOW + 1, ctx)
        boxes.assert_not_called()
        self.assertEqual(alerts.events, [])

    def test_only_the_configured_inbound_direction_counts(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_granted"})], alerts=alerts)
        function = tailgating_correlation.Function(
            {"door_id": "door-main", "window_seconds": 30, "inbound": "backward"}
        )
        self._run(function, ctx, [
            [person(1, 0.4, 0.3), person(2, 0.6, 0.3)],
            [person(1, 0.4, 0.7), person(2, 0.6, 0.7)],
        ])
        self.assertEqual(alerts.events, [])


class DoorAlarmVerificationTests(unittest.TestCase):
    def test_forced_open_alarm_summarizes_observed_context(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "dps_door_forced_open"})], alerts=alerts)
        function = door_alarm_verification.Function({"door_id": "door-main", "observe_seconds": 2})
        camera = {"id": "cam", "name": "Side Door", "zones": {"door_zone": [[0, 0], [1, 0], [1, 1], [0, 1]]}}
        frames = [
            [person(1, 0.5, 0.5), (7, 0.2, 0.2, 0.1, 0.1, 0.3, 0.3, 9)],
            [person(1, 0.5, 0.5), (39, 0.8, 0.8, 0.7, 0.7, 0.9, 0.9, 11)],
            [person(1, 0.5, 0.5)],
        ]
        with patch.object(door_alarm_verification, "boxes_of", side_effect=frames), patch.object(
            door_alarm_verification, "in_zone", return_value=True
        ):
            function.process(camera, object(), NOW, ctx)
            function.process(camera, object(), NOW + 1, ctx)
            self.assertEqual(alerts.events, [])
            function.process(camera, object(), NOW + 2, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["kind"], access.FORCED_OPEN)
        self.assertEqual(meta["max_people"], 1)
        self.assertEqual(meta["max_vehicles"], 1)
        self.assertEqual(meta["max_objects"], 1)
        self.assertGreaterEqual(meta["longest_dwell_seconds"], 2)

    def test_a_credential_grant_does_not_open_an_alarm_window(self):
        ctx = context([door_event({"type": "access_granted"})])
        function = door_alarm_verification.Function({"door_id": "door-main"})
        with patch.object(door_alarm_verification, "boxes_of") as boxes:
            function.process({"id": "cam", "name": "Side Door"}, object(), NOW, ctx)
        boxes.assert_not_called()
        self.assertEqual(ctx.alerts.events, [])


class DeniedAccessEscalationTests(unittest.TestCase):
    CAMERA = {"id": "cam", "name": "East Entrance", "zones": {"approach_zone": [[0, 0], [1, 0], [1, 1], [0, 1]]}}

    def _denials(self, count):
        return [
            door_event({"type": "access_denied", "credential_type": "NFC"},
                       seconds=NOW - count + index, identifier=f"deny-{index}")
            for index in range(count)
        ]

    def test_threshold_is_required_before_a_record_is_emitted(self):
        alerts = _Alerts()
        ctx = context(self._denials(2), alerts=alerts)
        function = denied_access_escalation.Function({"door_id": "door-main", "min_denials": 3})
        with patch.object(denied_access_escalation, "boxes_of", return_value=[person(1, 0.5, 0.5)]), patch.object(
            denied_access_escalation, "in_zone", return_value=True
        ):
            function.process(self.CAMERA, object(), NOW, ctx)
        self.assertEqual(alerts.events, [])

    def test_grouped_denials_report_person_count_dwell_and_methods(self):
        alerts = _Alerts()
        ctx = context(self._denials(3), alerts=alerts)
        function = denied_access_escalation.Function({"door_id": "door-main", "min_denials": 3})
        with patch.object(
            denied_access_escalation, "boxes_of",
            side_effect=[[person(1, 0.5, 0.5)], [person(1, 0.5, 0.5), person(2, 0.6, 0.5)]],
        ), patch.object(denied_access_escalation, "in_zone", return_value=True):
            function.process(self.CAMERA, object(), NOW, ctx)
            function.process(self.CAMERA, object(), NOW + 2, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["denials"], 3)
        self.assertEqual(meta["max_people"], 1)
        self.assertEqual(meta["methods"], ["nfc"])

    def test_cooldown_suppresses_a_second_record_for_the_same_door(self):
        alerts = _Alerts()
        events = self._denials(3)
        ctx = context(events, alerts=alerts)
        function = denied_access_escalation.Function(
            {"door_id": "door-main", "min_denials": 3, "cooldown_seconds": 600}
        )
        with patch.object(denied_access_escalation, "boxes_of", return_value=[person(1, 0.5, 0.5)]), patch.object(
            denied_access_escalation, "in_zone", return_value=True
        ):
            function.process(self.CAMERA, object(), NOW, ctx)
            ctx.access_events.extend(
                door_event({"type": "access_denied"}, seconds=NOW + index, identifier=f"late-{index}")
                for index in range(3)
            )
            function.process(self.CAMERA, object(), NOW + 5, ctx)
        self.assertEqual(len(alerts.events), 1)


class AccessIncidentIndexTests(unittest.TestCase):
    def test_records_are_written_and_searchable_by_door_kind_and_people(self):
        alerts = _Alerts()
        events = [
            door_event({"type": "access_denied", "credential_type": "keypad"}, identifier="deny-east"),
            door_event({"type": "access_granted"}, identifier="grant-east"),
        ]
        ctx = context(events, alerts=alerts)
        function = access_incident_index.Function({"door_id": "door-main", "sample_seconds": 2})
        camera = {"id": "cam", "name": "East Entrance"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            with patch.object(
                access_incident_index, "boxes_of",
                return_value=[person(1, 0.4, 0.5), person(2, 0.6, 0.5)],
            ):
                function.process(camera, object(), NOW, ctx)
                function.process(camera, object(), NOW + 3, ctx)

            everything = access_incident_index.search_records()
            self.assertEqual(len(everything), 2)
            denied = access_incident_index.search_records(kinds=["denied"], min_people=2)
            self.assertEqual([record["access_event_id"] for record in denied], ["deny-east"])
            self.assertEqual(denied[0]["method"], "pin")
            self.assertEqual(denied[0]["camera_name"], "East Entrance")
            self.assertEqual(access_incident_index.search_records(min_people=3), [])
            self.assertEqual(access_incident_index.search_records(door="door-other"), [])
            self.assertEqual(len(access_incident_index.search_records(query="east entrance")), 2)

    def test_index_file_is_bounded_by_max_records(self):
        alerts = _Alerts()
        events = [
            door_event({"type": "access_granted"}, seconds=NOW + index, identifier=f"grant-{index}")
            for index in range(5)
        ]
        ctx = context(events, alerts=alerts)
        function = access_incident_index.Function(
            {"door_id": "door-main", "sample_seconds": 1, "max_records": 2}
        )
        camera = {"id": "cam", "name": "Entry"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            with patch.object(access_incident_index, "boxes_of", return_value=[]):
                function.process(camera, object(), NOW + 4, ctx)
                function.process(camera, object(), NOW + 10, ctx)
            self.assertEqual(len(access_incident_index.search_records()), 2)


class AccessEvidencePackageTests(unittest.TestCase):
    def test_package_holds_event_metadata_observations_and_review_history(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_denied"}, identifier="evt/../escape")], alerts=alerts)
        function = access_evidence_package.Function(
            {"door_id": "door-main", "sample_seconds": 2, "retention_days": 0}
        )
        camera = {"id": "cam", "name": "Entry"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            with patch.object(access_evidence_package, "boxes_of", return_value=[person(1, 0.5, 0.5)]):
                function.process(camera, object(), NOW, ctx)
                function.process(camera, object(), NOW + 3, ctx)

            packages = access_evidence_package.list_packages()
            self.assertEqual(len(packages), 1)
            package = packages[0]
            self.assertEqual(package["access_event"]["access_event_id"], "evt/../escape")
            self.assertEqual(package["access_event"]["kind"], access.DENIED)
            self.assertEqual(package["observations"]["max_people"], 1)
            self.assertTrue(package["alert"]["delivered"])
            self.assertEqual(package["review"], [])

            updated = access_evidence_package.record_review(
                "evt/../escape", reviewer="Operator", decision="cleared", note="scheduled delivery", at=NOW
            )
            self.assertEqual(len(updated["review"]), 1)
            self.assertEqual(updated["review"][0]["decision"], "cleared")

            stored = json.loads(access_evidence_package.package_path("evt/../escape").read_text(encoding="utf-8"))
            self.assertEqual(len(stored["review"]), 1)
            self.assertEqual(
                access_evidence_package.package_path("evt/../escape").parent,
                access.data_directory(access_evidence_package.PACKAGE_DIRECTORY),
            )

    def test_package_store_is_bounded_by_max_packages(self):
        alerts = _Alerts()
        events = [
            door_event({"type": "access_denied"}, seconds=NOW + index, identifier=f"evt-{index}")
            for index in range(4)
        ]
        ctx = context(events, alerts=alerts)
        function = access_evidence_package.Function(
            {"door_id": "door-main", "sample_seconds": 1, "max_packages": 2, "retention_days": 0}
        )
        camera = {"id": "cam", "name": "Entry"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            with patch.object(access_evidence_package, "boxes_of", return_value=[]):
                function.process(camera, object(), NOW + 3, ctx)
                function.process(camera, object(), NOW + 9, ctx)
            self.assertEqual(len(access_evidence_package.list_packages()), 2)

    def test_snapshot_is_not_requested_under_skeleton_privacy_mode(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_denied"})], alerts=alerts)
        function = access_evidence_package.Function(
            {"door_id": "door-main", "sample_seconds": 1, "retention_days": 0}
        )
        camera = {"id": "cam", "name": "Entry", "privacy_mode": "skeleton"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            with patch.object(access_evidence_package, "boxes_of", return_value=[]):
                function.process(camera, object(), NOW, ctx)
                function.process(camera, object(), NOW + 2, ctx)
            self.assertFalse(access_evidence_package.list_packages()[0]["alert"]["snapshot_requested"])


class AfterHoursEntryVerificationTests(unittest.TestCase):
    CAMERA = {"id": "cam", "name": "Rear Door", "zones": {"door_line": [[0, 0.5], [1, 0.5]]}}
    NIGHT = calendar.timegm((2026, 8, 15, 6, 0, 0, 0, 0, 0))    # 01:00 CDT
    MIDDAY = calendar.timegm((2026, 8, 15, 17, 0, 0, 0, 0, 0))  # 12:00 CDT

    def test_grant_inside_open_hours_opens_no_window(self):
        ctx = context([door_event({"type": "access_granted"}, seconds=self.MIDDAY)])
        function = after_hours_entry_verification.Function({"door_id": "door-main", "open_hours": [7, 19]})
        with patch.object(after_hours_entry_verification, "boxes_of") as boxes:
            function.process(self.CAMERA, object(), self.MIDDAY, ctx)
        boxes.assert_not_called()
        self.assertEqual(ctx.alerts.events, [])

    def test_grant_outside_open_hours_reports_direction_vehicle_and_proximity(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_granted"}, seconds=self.NIGHT)], alerts=alerts)
        function = after_hours_entry_verification.Function(
            {"door_id": "door-main", "open_hours": [7, 19], "window_seconds": 4, "escort_distance": 0.3}
        )
        frames = [
            [person(1, 0.40, 0.30), person(2, 0.50, 0.30), (7, 0.9, 0.9, 0.8, 0.8, 1.0, 1.0, 5)],
            [person(1, 0.40, 0.70), person(2, 0.50, 0.70)],
        ]
        with patch.object(after_hours_entry_verification, "boxes_of", side_effect=frames):
            function.process(self.CAMERA, object(), self.NIGHT, ctx)
            self.assertEqual(alerts.events, [])
            function.process(self.CAMERA, object(), self.NIGHT + 5, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["max_people"], 2)
        self.assertEqual(meta["inbound_crossings"], 2)
        self.assertEqual(meta["outbound_crossings"], 0)
        self.assertEqual(meta["vehicle_frames"], 1)
        self.assertTrue(meta["close_second_person"])
        self.assertAlmostEqual(meta["closest_person_distance"], 0.1, places=3)

    def test_overnight_open_hours_wrap_across_midnight(self):
        function = after_hours_entry_verification.Function({"open_hours": [20, 6]})
        ctx = context()
        self.assertFalse(function._outside_open_hours(self.NIGHT, ctx))
        self.assertTrue(function._outside_open_hours(self.MIDDAY, ctx))


class OccupancyReconciliationTests(unittest.TestCase):
    CAMERA = {"id": "cam", "name": "Lobby", "zones": {"count_line": [[0, 0.5], [1, 0.5]]}}
    EVENING = calendar.timegm((2026, 8, 16, 4, 0, 0, 0, 0, 0))  # 23:00 CDT

    def test_difference_at_the_summary_hour_is_reported_once(self):
        alerts = _Alerts()
        start = self.EVENING - 3600
        ctx = context(
            [door_event({"type": "access_granted"}, seconds=start, identifier="grant-1")],
            alerts=alerts,
        )
        function = occupancy_reconciliation.Function({"door_id": "door-main", "summary_hour": 23})
        frames = [
            [person(1, 0.3, 0.3), person(2, 0.6, 0.3), person(3, 0.8, 0.3)],
            [person(1, 0.3, 0.7), person(2, 0.6, 0.7), person(3, 0.8, 0.7)],
            [],
        ]
        with patch.object(occupancy_reconciliation, "boxes_of", side_effect=frames):
            function.process(self.CAMERA, object(), start, ctx)
            function.process(self.CAMERA, object(), start + 1, ctx)
            function.process(self.CAMERA, object(), self.EVENING, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["credentialed_passages"], 1)
        self.assertEqual(meta["observed_crossings"], 3)
        self.assertEqual(meta["difference"], 2)

    def test_matching_totals_stay_quiet(self):
        alerts = _Alerts()
        start = self.EVENING - 3600
        ctx = context(
            [door_event({"type": "access_granted"}, seconds=start, identifier="grant-1")],
            alerts=alerts,
        )
        function = occupancy_reconciliation.Function({"door_id": "door-main", "summary_hour": 23})
        with patch.object(
            occupancy_reconciliation, "boxes_of",
            side_effect=[[person(1, 0.3, 0.3)], [person(1, 0.3, 0.7)], []],
        ):
            function.process(self.CAMERA, object(), start, ctx)
            function.process(self.CAMERA, object(), start + 1, ctx)
            function.process(self.CAMERA, object(), self.EVENING, ctx)
        self.assertEqual(alerts.events, [])


class VisitorEntryReviewTests(unittest.TestCase):
    def test_doorbell_event_reports_people_items_and_vehicles_without_unlocking(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "access_doorbell_ring"})], alerts=alerts)
        function = visitor_entry_review.Function({"door_id": "door-main", "review_seconds": 3})
        camera = {"id": "cam", "name": "Front Door"}
        frames = [
            [person(1, 0.5, 0.5), (24, 0.4, 0.6, 0.3, 0.5, 0.5, 0.7, 4)],
            [person(1, 0.5, 0.5), (7, 0.9, 0.5, 0.8, 0.4, 1.0, 0.6, 6)],
        ]
        with patch.object(visitor_entry_review, "boxes_of", side_effect=frames):
            function.process(camera, object(), NOW, ctx)
            function.process(camera, object(), NOW + 4, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["max_people"], 1)
        self.assertEqual(meta["max_carried_items"], 1)
        self.assertEqual(meta["max_vehicles"], 1)
        self.assertFalse(meta["auto_unlock"])

    def test_module_never_calls_an_unlock_path(self):
        source = (SRC / "marketplace" / "functions" / "visitor_entry_review.py").read_text(encoding="utf-8")
        self.assertNotIn("unlock(", source)


class DoorOperationVerificationTests(unittest.TestCase):
    CAMERA = {
        "id": "cam",
        "name": "Dock Door",
        "zones": {"door_line": [[0, 0.5], [1, 0.5]], "door_zone": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]},
    }

    def test_unlock_command_reports_crossing_and_zone_change(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "remote_unlock"})], alerts=alerts)
        function = door_operation_verification.Function({"door_id": "door-main", "verify_seconds": 4})
        frames = [[person(1, 0.5, 0.3)], [person(1, 0.5, 0.7)]]
        with patch.object(door_operation_verification, "boxes_of", side_effect=frames), patch.object(
            door_operation_verification.Function, "_zone_crop", return_value=object()
        ), patch.object(door_operation_verification.Function, "_difference", side_effect=[0.42]):
            function.process(self.CAMERA, object(), NOW, ctx)
            self.assertEqual(alerts.events, [])
            function.process(self.CAMERA, object(), NOW + 5, ctx)

        self.assertEqual(len(alerts.events), 1)
        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["crossings"], 1)
        self.assertEqual(meta["peak_zone_change"], 0.42)
        self.assertTrue(meta["zone_changed_at_close"])

    def test_zone_returning_to_its_reference_is_reported_as_unchanged(self):
        alerts = _Alerts()
        ctx = context([door_event({"type": "remote_unlock"})], alerts=alerts)
        function = door_operation_verification.Function({"door_id": "door-main", "verify_seconds": 4})
        with patch.object(door_operation_verification, "boxes_of", return_value=[]), patch.object(
            door_operation_verification.Function, "_zone_crop", return_value=object()
        ), patch.object(door_operation_verification.Function, "_difference", side_effect=[0.01]):
            function.process(self.CAMERA, object(), NOW, ctx)
            function.process(self.CAMERA, object(), NOW + 5, ctx)

        meta = alerts.events[0]["meta"]
        self.assertEqual(meta["crossings"], 0)
        self.assertFalse(meta["zone_changed_at_close"])

    def test_a_credential_grant_does_not_open_a_verification_window(self):
        ctx = context([door_event({"type": "access_granted"})])
        function = door_operation_verification.Function({"door_id": "door-main"})
        with patch.object(door_operation_verification, "boxes_of") as boxes:
            function.process(self.CAMERA, object(), NOW, ctx)
        boxes.assert_not_called()


class CrossSystemContractTests(unittest.TestCase):
    def test_every_module_declares_a_door_id_and_a_security_manifest(self):
        for module in CROSS_SYSTEM_MODULES:
            manifest = module.MANIFEST
            self.assertEqual(manifest["category"], "Security & Access", manifest["id"])
            self.assertIn("door_id", manifest["config_schema"], manifest["id"])
            self.assertTrue(manifest["requires_gpu"], manifest["id"])

    def test_modules_degrade_quietly_without_access_credentials(self):
        """No Access host means an empty event buffer: no alerts, no inference."""
        empty = SimpleNamespace(site="Test Site", timezone="America/Chicago", alerts=_Alerts())
        cameras = {
            "zones": {
                "door_line": [[0, 0.5], [1, 0.5]],
                "count_line": [[0, 0.5], [1, 0.5]],
                "door_zone": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "approach_zone": [[0, 0], [1, 0], [1, 1], [0, 1]],
            }
        }
        camera = {"id": "cam", "name": "Entry", **cameras}
        for module in CROSS_SYSTEM_MODULES:
            function = module.Function({"door_id": "door-main"})
            with patch.object(module, "boxes_of", return_value=[]):
                function.process(camera, object(), NOW, empty)
        self.assertEqual(empty.alerts.events, [])

    def test_modules_ignore_malformed_access_events(self):
        camera = {
            "id": "cam",
            "name": "Entry",
            "zones": {
                "door_line": [[0, 0.5], [1, 0.5]],
                "count_line": [[0, 0.5], [1, 0.5]],
                "door_zone": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "approach_zone": [[0, 0], [1, 0], [1, 1], [0, 1]],
            },
        }
        malformed = [None, "not-an-event", {}, {"ts": "bad"}, {"door_id": "door-main"}]
        for module in CROSS_SYSTEM_MODULES:
            alerts = _Alerts()
            ctx = context(malformed, alerts=alerts)
            function = module.Function({"door_id": "door-main"})
            with patch.object(module, "boxes_of", return_value=[]):
                function.process(camera, object(), NOW, ctx)
            self.assertEqual(alerts.events, [], module.MANIFEST["id"])


class PipelineIntegrationTests(unittest.TestCase):
    """The buffer the AccessPoller feeds is the buffer the modules read."""

    def test_access_event_reaches_a_marketplace_module_through_the_pipeline(self):
        from marketplace.loader import load_all
        from main import Pipeline

        registry, errors = load_all()
        self.assertEqual(errors, {})
        classes = {function_id: entry["cls"] for function_id, entry in registry.items()}
        detector_id = "verified-door-timeline"
        config = {
            "site": {"name": "Test Site", "timezone": "America/Chicago"},
            "alerts": {"dedup_seconds": 0},
            "cameras": [{
                "id": "cam-east",
                "name": "East Entrance",
                "detectors": [detector_id],
                detector_id: {"door_id": "door-east", "review_seconds": 2},
            }],
        }
        hit = {
            "_id": "evt-pipeline",
            "event_time": int(NOW * 1000),
            "door": {"id": "door-east", "name": "East Entrance"},
            "event_type": "access.door.denied",
            "result": "DENIED",
        }

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"VISION_DATA": temporary, "BASE44_ALERT_URL": "", "EXTRA_WEBHOOK_URL": ""},
            clear=False,
        ):
            pipeline = Pipeline(config, classes)
            pipeline.on_access_event(AccessPoller._normalize(hit))
            configured = pipeline.camera_detectors["cam-east"][0]
            # The loader execs each module outside sys.modules, so patch the
            # globals of the class the runtime actually instantiated.
            with patch.dict(
                type(configured).process.__globals__,
                {"boxes_of": lambda *_args, **_kwargs: [person(1, 0.5, 0.5)]},
            ):
                pipeline.on_frame(config["cameras"][0], None, NOW)
                pipeline.on_frame(config["cameras"][0], None, NOW + 3)

            self.assertEqual(pipeline.detector_failures, {})
            self.assertEqual(pipeline.alerts.sent, 1)


if __name__ == "__main__":
    unittest.main()
