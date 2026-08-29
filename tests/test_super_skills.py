from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace.contract import MarketplaceFunction, validate_manifest

AUDIT_PATH = ROOT / "docs" / "super-skill-portfolio.json"


class SuperSkillInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        cls.specs = cls.audit["super_skills"]

    def test_audit_has_exact_portfolio_arithmetic(self):
        retired = [row["id"] for row in self.audit["retired"]]
        added = [row["id"] for row in self.specs]
        self.assertEqual(len(retired), 25)
        self.assertEqual(len(set(retired)), 25)
        self.assertEqual(len(added), 30)
        self.assertEqual(len(set(added)), 30)
        self.assertTrue(set(retired).isdisjoint(added))
        self.assertEqual(self.audit["outcome"]["retained_functions"], 75)
        self.assertEqual(self.audit["outcome"]["active_functions"], 105)
        self.assertEqual(self.audit["outcome"]["source_archive_contracts"], 301)

    def test_exactly_30_super_skills_have_executable_contracts(self):
        from marketplace.super_skills import SuperSkillFunction, WORKFLOWS

        seen = set()
        for spec in self.specs:
            module_name = spec["id"].replace("-", "_")
            with self.subTest(module=module_name):
                module = importlib.import_module(f"marketplace.functions.{module_name}")
                self.assertEqual(module.MANIFEST["id"], spec["id"])
                self.assertEqual(module.MANIFEST["name"], spec["name"])
                self.assertEqual(module.MANIFEST["category"], spec["category"])
                self.assertEqual(module.MANIFEST["tier"], spec["tier"])
                self.assertEqual(validate_manifest(module.MANIFEST), [])
                self.assertTrue(issubclass(module.Function, MarketplaceFunction))
                self.assertTrue(issubclass(module.Function, SuperSkillFunction))
                self.assertEqual(module.Function.function_id, spec["id"])
                self.assertEqual(module.Function.workflow, spec["workflow"])
                self.assertIn(module.Function.workflow, WORKFLOWS)
                self.assertIs(module.Function.process, SuperSkillFunction.process)
                instance = module.Function({})
                self.assertEqual(instance.name, spec["id"])
                seen.add(module.MANIFEST["id"])
        self.assertEqual(seen, {row["id"] for row in self.specs})

    def test_super_skill_workflows_are_all_represented(self):
        from marketplace.super_skills import WORKFLOWS

        workflows = {row["workflow"] for row in self.specs}
        self.assertEqual(workflows, set(WORKFLOWS))


FULL = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
A = [(0.0, 0.0), (0.3, 0.0), (0.3, 1.0), (0.0, 1.0)]
B = [(0.34, 0.0), (0.56, 0.0), (0.56, 1.0), (0.34, 1.0)]
C = [(0.60, 0.0), (0.79, 0.0), (0.79, 1.0), (0.60, 1.0)]
D = [(0.82, 0.0), (1.0, 0.0), (1.0, 1.0), (0.82, 1.0)]
VERTICAL = [(0.5, 0.0), (0.5, 1.0)]
FRAME = np.full((40, 40, 3), 100, dtype=np.uint8)


def box(track_id, x, y=0.5, class_id=0):
    return {
        "class_id": class_id,
        "cx": x,
        "cy": y,
        "x1": max(0.0, x - 0.05),
        "y1": max(0.0, y - 0.05),
        "x2": min(1.0, x + 0.05),
        "y2": min(1.0, y + 0.05),
        "track_id": track_id,
    }


def domain(track_id, label, x=0.5, y=0.5):
    value = box(track_id, x, y, -1)
    value["label"] = label
    return value


class AlertSink:
    def __init__(self):
        self.events = []

    def fire(self, **event):
        self.events.append(event)
        return event


class SuperSkillBehaviorTests(unittest.TestCase):
    def setUp(self):
        from marketplace import super_skills

        with super_skills._SHARED_LOCK:
            super_skills._SHARED_STATE.clear()
        self.alerts = AlertSink()
        self.ctx = SimpleNamespace(
            site="test-site",
            timezone=ZoneInfo("UTC"),
            alerts=self.alerts,
            access_events=[],
            protect_events=[],
            cameras=[],
            detector_failures={},
        )

    def function(self, function_id, settings=None):
        module = importlib.import_module(
            f"marketplace.functions.{function_id.replace('-', '_')}"
        )
        return module.Function(settings or {})

    def camera(self, zones=None, camera_id="cam-1", **extra):
        value = {
            "id": camera_id,
            "name": f"Camera {camera_id}",
            "rtsp": "rtsp://example.invalid/live",
            "zones": zones or {},
        }
        value.update(extra)
        return value

    def boxes(self, function, batches):
        pending = iter(batches)
        function._box_items = lambda camera, frame, classes=None: next(pending, [])

    def domains(self, function, batches):
        pending = iter(batches)
        function._domain_items = lambda frame, ts: next(pending, [])

    def assert_fired(self, function_id):
        self.assertTrue(self.alerts.events, function_id)
        self.assertEqual(self.alerts.events[-1]["detector"], function_id)

    def test_all_30_super_skills_execute_positive_behavior_paths(self):
        exercises = [
            self.exercise_secured_exit,
            self.exercise_room_exit,
            self.exercise_mobility_obstruction,
            self.exercise_controlled_room_count,
            self.exercise_occupancy_imbalance,
            self.exercise_waiting_flow,
            self.exercise_estate_health,
            self.exercise_perimeter_verify,
            self.exercise_intrusion_progression,
            self.exercise_package_chain,
            self.exercise_multi_camera_corroboration,
            self.exercise_door_response,
            self.exercise_zone_funnel,
            self.exercise_queue_service,
            self.exercise_curbside_handoff,
            self.exercise_lane_balance,
            self.exercise_table_reset,
            self.exercise_traffic_trigger,
            self.exercise_dock_turnaround,
            self.exercise_trajectory_conflict,
            self.exercise_domain_route,
            self.exercise_persistent_obstruction,
            self.exercise_domain_sequence,
            self.exercise_yard_queue,
            self.exercise_multi_class_flow,
            self.exercise_space_utilization,
            self.exercise_route_completion,
            self.exercise_schedule_baseline,
            self.exercise_shift_flow,
            self.exercise_evidence_casebook,
        ]
        expected = {
            row["id"]
            for row in json.loads(AUDIT_PATH.read_text(encoding="utf-8"))["super_skills"]
        }
        observed = set()
        for exercise in exercises:
            self.alerts.events.clear()
            with self.subTest(exercise=exercise.__name__):
                function_id = exercise()
                self.assert_fired(function_id)
                observed.add(function_id)
        self.assertEqual(observed, expected)

    def test_camera_skeleton_privacy_cannot_be_overridden_by_function(self):
        function_id = "secured-exit-approach-review"
        function = self.function(
            function_id,
            {"approach_seconds": 0, "privacy_mode": "full"},
        )
        self.boxes(function, [[box(1, 0.2)]])

        function.process(
            self.camera(
                {"secured_exit_approach": FULL},
                privacy_mode="skeleton",
            ),
            FRAME,
            100,
            self.ctx,
        )

        self.assert_fired(function_id)
        self.assertIsNone(self.alerts.events[-1]["frame"])

    def test_domain_workflows_fail_closed_without_customer_weights(self):
        cases = [
            (
                "mobility-aid-egress-obstruction",
                {"hold_seconds": 0},
                {"mobility_egress": FULL},
            ),
            (
                "forklift-route-deviation-review",
                {"off_route_seconds": 0},
                {"forklift_allowed_corridor": A},
            ),
            (
                "cycle-step-timer",
                {},
                {"cycle_workcell": FULL},
            ),
        ]
        for function_id, settings, zones in cases:
            with self.subTest(function_id=function_id):
                self.alerts.events.clear()
                function = self.function(function_id, settings)
                function.process(self.camera(zones), FRAME, 100, self.ctx)
                self.assertEqual(self.alerts.events, [])

    def test_domain_workflows_fail_closed_with_unreadable_customer_weights(self):
        cases = [
            (
                "mobility-aid-egress-obstruction",
                {"hold_seconds": 0},
                {"mobility_egress": FULL},
            ),
            (
                "package-room-chain-review",
                {},
                {"package_room": FULL},
            ),
            (
                "forklift-route-deviation-review",
                {"off_route_seconds": 0},
                {"forklift_allowed_corridor": A},
            ),
            (
                "cycle-step-timer",
                {},
                {"cycle_workcell": FULL},
            ),
            (
                "aisle-blockage-duration-review",
                {"hold_seconds": 1},
                {"aisle_blockage_area": FULL},
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            weights = Path(temporary) / "unreadable.pt"
            weights.write_bytes(b"not a model")
            with patch(
                "marketplace.vendor_patterns.detector_base.get_model",
                side_effect=TypeError("unreadable weights"),
            ) as get_model:
                for function_id, settings, zones in cases:
                    with self.subTest(function_id=function_id):
                        self.alerts.events.clear()
                        function = self.function(
                            function_id,
                            {**settings, "weights": str(weights)},
                        )
                        if function_id == "aisle-blockage-duration-review":
                            self.boxes(
                                function,
                                [
                                    [box(1, 0.5, class_id=1)],
                                    [box(1, 0.5, class_id=1)],
                                ],
                            )
                        function.process(self.camera(zones), FRAME, 100, self.ctx)
                        function.process(self.camera(zones), FRAME, 102, self.ctx)
                        self.assertEqual(self.alerts.events, [])
                self.assertEqual(get_model.call_count, len(cases))

    def test_last_zone_only_does_not_complete_ordered_sequence(self):
        function_id = "room-exit-sequence-review"
        function = self.function(function_id)
        self.boxes(function, [[box(1, 0.7)]])

        function.process(
            self.camera(
                {
                    "room_bed_area": A,
                    "room_transition": B,
                    "room_doorway": C,
                }
            ),
            FRAME,
            100,
            self.ctx,
        )

        self.assertEqual(self.alerts.events, [])
        self.assertEqual(function._tracks["0:1"]["stage"], 0)
        self.assertTrue(function._tracks["0:1"]["skipped"])

    def test_sequence_timeout_resets_all_per_cycle_latches(self):
        function_id = "room-exit-sequence-review"
        function = self.function(function_id, {"sequence_window_seconds": 2})
        self.boxes(
            function,
            [
                [box(1, 0.2)],
                [box(1, 0.45)],
                [box(1, 0.7)],
                [box(1, 0.2)],
                [box(1, 0.45)],
                [box(1, 0.7)],
            ],
        )
        camera = self.camera(
            {
                "room_bed_area": A,
                "room_transition": B,
                "room_doorway": C,
            }
        )

        for ts in (100, 101, 102, 105, 106, 107):
            function.process(camera, FRAME, ts, self.ctx)

        self.assertEqual(len(self.alerts.events), 2)

    def test_trajectory_conflict_pair_state_is_hard_bounded_and_cleaned(self):
        from marketplace import super_skills

        function = self.function(
            "dock-apron-conflict-review",
            {"hold_seconds": 0, "conflict_distance_ratio": 1},
        )
        first = [
            *[box(index, 0.2, class_id=0) for index in range(100)],
            *[box(index, 0.8, class_id=2) for index in range(100)],
        ]
        second = [
            *[box(index, 0.49, class_id=0) for index in range(100)],
            *[box(index, 0.51, class_id=2) for index in range(100)],
        ]
        self.boxes(function, [first, second, []])
        camera = self.camera({"dock_apron_conflict": FULL})

        function.process(camera, FRAME, 100, self.ctx)
        function.process(camera, FRAME, 101, self.ctx)

        self.assertLessEqual(
            len(function._state["conflicts"]),
            super_skills._CONFLICT_PAIR_LIMIT,
        )
        self.assertLessEqual(
            len(function._state["reported_pairs"]),
            super_skills._CONFLICT_PAIR_LIMIT,
        )
        self.assertLessEqual(
            len(function._tracks),
            super_skills._CONFLICT_TRACKS_PER_CLASS * 2,
        )

        function.process(camera, FRAME, 102, self.ctx)
        self.assertEqual(function._state["conflicts"], {})
        self.assertEqual(function._state["reported_pairs"], {})

    def test_empty_customer_stage_sequence_fails_closed(self):
        function = self.function(
            "cycle-step-timer",
            {"expected_sequence": []},
        )
        self.domains(function, [[domain(1, "stage-a")]])

        result = function.process(
            self.camera({"cycle_workcell": FULL}),
            FRAME,
            100,
            self.ctx,
        )

        self.assertIsNone(result)
        self.assertEqual(self.alerts.events, [])

    def test_cross_camera_shared_state_is_bounded(self):
        from marketplace import super_skills

        function = self.function("after-hours-multi-camera-corroboration")
        for index in range(super_skills._SHARED_LIMIT + 50):
            self.ctx.site = f"site-{index}"
            function._shared(self.ctx, float(index))

        with super_skills._SHARED_LOCK:
            self.assertLessEqual(
                len(super_skills._SHARED_STATE),
                super_skills._SHARED_LIMIT,
            )

    def test_cross_camera_observation_window_has_a_hard_cap(self):
        function = self.function(
            "after-hours-multi-camera-corroboration",
            {"closed_hours": [0, 0]},
        )
        self.boxes(
            function,
            [[box(index, 0.5) for index in range(5000)]],
        )
        function.process(
            self.camera({"after_hours_corroboration": FULL}),
            FRAME,
            100,
            self.ctx,
        )

        state = function._shared(self.ctx, 100)
        self.assertEqual(len(state["observations"]), 4096)

    def exercise_secured_exit(self):
        function_id = "secured-exit-approach-review"
        fn = self.function(function_id, {"approach_seconds": 0})
        self.boxes(fn, [[box(1, 0.2)]])
        camera = self.camera({"secured_exit_approach": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        return function_id

    def exercise_room_exit(self):
        function_id = "room-exit-sequence-review"
        fn = self.function(function_id)
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.45)], [box(1, 0.7)]])
        camera = self.camera(
            {"room_bed_area": A, "room_transition": B, "room_doorway": C}
        )
        for ts in (100, 101, 102):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_mobility_obstruction(self):
        function_id = "mobility-aid-egress-obstruction"
        fn = self.function(function_id, {"hold_seconds": 1})
        self.domains(fn, [[domain(1, "wheelchair")], [domain(1, "wheelchair")]])
        camera = self.camera({"mobility_egress": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_controlled_room_count(self):
        function_id = "controlled-room-two-person-review"
        fn = self.function(function_id, {"observe_seconds": 1, "door_id": "door-1"})
        self.ctx.access_events = [
            {
                "id": "grant-1",
                "ts": 100,
                "type": "credential_granted",
                "credential_granted": True,
                "door_id": "door-1",
            }
        ]
        self.boxes(fn, [[box(1, 0.5), box(2, 0.6)], []])
        camera = self.camera({"controlled_room_door": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_occupancy_imbalance(self):
        function_id = "care-area-occupancy-imbalance"
        fn = self.function(
            function_id, {"imbalance_threshold": 2, "hold_seconds": 1}
        )
        batch = [box(1, 0.1), box(2, 0.15), box(3, 0.2)]
        self.boxes(fn, [batch, batch])
        camera = self.camera({"care_zone_a": A, "care_zone_b": D})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_waiting_flow(self):
        function_id = "waiting-room-flow-ledger"
        fn = self.function(function_id, {"digest_seconds": 100})
        self.boxes(
            fn,
            [
                [box(1, 0.1)],
                [box(1, 0.4)],
                [box(1, 0.65)],
                [box(1, 0.9)],
                [],
            ],
        )
        camera = self.camera(
            {
                "waiting_arrival": A,
                "waiting_area": B,
                "waiting_service": C,
                "waiting_exit": D,
            }
        )
        for ts in (100, 101, 102, 103, 201):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_estate_health(self):
        function_id = "vision-estate-health"
        fn = self.function(
            function_id,
            {"digest_seconds": 10, "startup_grace_seconds": 0, "offline_seconds": 5},
        )
        camera = self.camera({}, camera_id="health", name="", rtsp="")
        self.ctx.cameras = [camera]
        dark = np.zeros_like(FRAME)
        fn.process(camera, dark, 100, self.ctx)
        fn.process(camera, dark, 111, self.ctx)
        return function_id

    def exercise_perimeter_verify(self):
        function_id = "perimeter-event-verifier"
        fn = self.function(function_id, {"hold_seconds": 0})
        self.boxes(fn, [[box(1, 0.5)]])
        camera = self.camera({"perimeter_verify_zone": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        return function_id

    def exercise_intrusion_progression(self):
        function_id = "multi-zone-intrusion-progression"
        fn = self.function(function_id)
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.45)], [box(1, 0.7)]])
        camera = self.camera(
            {"intrusion_perimeter": A, "intrusion_yard": B, "intrusion_doorway": C}
        )
        for ts in (100, 101, 102):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_package_chain(self):
        function_id = "package-room-chain-review"
        fn = self.function(function_id, {"require_access_event": False})
        self.domains(fn, [[], [domain(1, "package")]])
        camera = self.camera({"package_room_zone": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 101, self.ctx)
        return function_id

    def exercise_multi_camera_corroboration(self):
        function_id = "after-hours-multi-camera-corroboration"
        settings = {"closed_hours": [0, 0], "corroboration_seconds": 10}
        first = self.function(function_id, settings)
        second = self.function(function_id, settings)
        self.boxes(first, [[box(1, 0.5)]])
        self.boxes(second, [[box(2, 0.5)]])
        first.process(
            self.camera({"after_hours_corroboration": FULL}, "cam-a"),
            FRAME,
            100,
            self.ctx,
        )
        second.process(
            self.camera({"after_hours_corroboration": FULL}, "cam-b"),
            FRAME,
            101,
            self.ctx,
        )
        return function_id

    def exercise_door_response(self):
        function_id = "door-alarm-observed-response-timer"
        fn = self.function(function_id, {"door_id": "door-1", "response_timeout_seconds": 20})
        camera = self.camera({"door_response_zone": FULL})
        self.ctx.access_events = [
            {"id": "forced", "ts": 100, "type": "forced_open", "door_id": "door-1"}
        ]
        self.boxes(fn, [[box(1, 0.5)], [box(1, 0.5)]])
        fn.process(camera, FRAME, 100, self.ctx)
        self.ctx.access_events.append(
            {"id": "closed", "ts": 102, "type": "door_closed", "door_id": "door-1"}
        )
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_zone_funnel(self):
        function_id = "anonymous-zone-funnel"
        fn = self.function(function_id, {"digest_seconds": 100})
        self.boxes(
            fn,
            [[box(1, 0.2)], [box(1, 0.45)], [box(1, 0.7)], [box(1, 0.9)], []],
        )
        camera = self.camera(
            {
                "funnel_entrance": A,
                "funnel_display": B,
                "funnel_product": C,
                "funnel_checkout": D,
            }
        )
        for ts in (100, 101, 102, 103, 201):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_queue_service(self):
        function_id = "queue-service-rate-digest"
        fn = self.function(function_id, {"digest_seconds": 100})
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.7)], []])
        camera = self.camera(
            {"queue_service_area": A, "queue_service_point": C}
        )
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 101, self.ctx)
        fn.process(camera, FRAME, 201, self.ctx)
        return function_id

    def exercise_curbside_handoff(self):
        function_id = "curbside-handoff-timer"
        fn = self.function(function_id)
        self.boxes(
            fn,
            [
                [box(10, 0.2, class_id=2)],
                [box(10, 0.2, class_id=2), box(1, 0.45)],
                [box(10, 0.8, class_id=2)],
            ],
        )
        camera = self.camera(
            {
                "curbside_arrival": A,
                "curbside_handoff": B,
                "curbside_departure_line": VERTICAL,
            }
        )
        for ts in (100, 101, 102):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_lane_balance(self):
        function_id = "drive-thru-lane-balance"
        fn = self.function(
            function_id, {"imbalance_count": 2, "imbalance_seconds": 1}
        )
        batch = [box(1, 0.1, class_id=2), box(2, 0.15, class_id=2), box(3, 0.2, class_id=2)]
        self.boxes(fn, [batch, batch])
        camera = self.camera({"drive_thru_lane_a": A, "drive_thru_lane_b": D})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_table_reset(self):
        function_id = "table-reset-delay-review"
        fn = self.function(function_id, {"reset_seconds": 5})
        self.boxes(fn, [[box(1, 0.2)], [], []])
        camera = self.camera(
            {"table_reset_area": A, "table_service_approach": D}
        )
        for ts in (100, 101, 107):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_traffic_trigger(self):
        function_id = "high-traffic-service-trigger"
        fn = self.function(function_id, {"event_threshold": 1, "window_seconds": 5})
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.8)]])
        camera = self.camera(
            {"high_traffic_service": FULL, "high_traffic_line": VERTICAL}
        )
        fn.process(camera, FRAME, 10, self.ctx)
        fn.process(camera, FRAME, 20, self.ctx)
        return function_id

    def exercise_dock_turnaround(self):
        function_id = "dock-stage-turnaround"
        fn = self.function(function_id)
        self.boxes(
            fn,
            [
                [box(1, 0.2, class_id=2)],
                [box(1, 0.45, class_id=2)],
                [box(1, 0.7, class_id=2)],
                [box(1, 0.9, class_id=2)],
            ],
        )
        camera = self.camera(
            {"dock_arrival": A, "dock_staging": B, "dock_bay": C, "dock_departure": D}
        )
        for ts in (100, 101, 102, 103):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_trajectory_conflict(self):
        function_id = "dock-apron-conflict-review"
        fn = self.function(function_id, {"hold_seconds": 0, "conflict_distance_ratio": 0.2})
        self.boxes(
            fn,
            [
                [box(1, 0.3), box(2, 0.7, class_id=2)],
                [box(1, 0.45), box(2, 0.55, class_id=2)],
            ],
        )
        camera = self.camera({"dock_apron": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 101, self.ctx)
        return function_id

    def exercise_domain_route(self):
        function_id = "forklift-route-deviation-review"
        fn = self.function(function_id, {"off_route_seconds": 0})
        self.domains(fn, [[domain(1, "forklift", 0.8)]])
        camera = self.camera({"forklift_allowed_corridor": A})
        fn.process(camera, FRAME, 100, self.ctx)
        return function_id

    def exercise_persistent_obstruction(self):
        function_id = "aisle-blockage-duration-review"
        fn = self.function(function_id, {"hold_seconds": 1})
        self.boxes(fn, [[box(1, 0.2, class_id=56)], [box(1, 0.2, class_id=56)]])
        camera = self.camera({"aisle_blockage_area": A, "emergency_access_area": D})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_domain_sequence(self):
        function_id = "cycle-step-timer"
        fn = self.function(function_id)
        self.domains(
            fn,
            [
                [domain(1, "stage-a")],
                [domain(1, "stage-b")],
                [domain(1, "stage-c")],
            ],
        )
        camera = self.camera({"cycle_workcell": FULL})
        for ts in (100, 101, 102):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_yard_queue(self):
        function_id = "yard-queue-bottleneck-digest"
        fn = self.function(function_id, {"digest_seconds": 1})
        batch = [box(index, 0.2, class_id=2) for index in range(1, 7)]
        self.boxes(fn, [batch, batch])
        camera = self.camera({"yard_queue": A, "yard_staging": B, "yard_dock": C})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_multi_class_flow(self):
        function_id = "multi-class-flow-ledger"
        fn = self.function(function_id, {"digest_seconds": 1})
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.8)]])
        camera = self.camera({"multi_class_flow_line": VERTICAL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_space_utilization(self):
        function_id = "anonymous-space-utilization-percentiles"
        fn = self.function(function_id, {"sample_seconds": 1, "digest_seconds": 1})
        self.boxes(fn, [[box(1, 0.5)], [box(1, 0.5), box(2, 0.6)]])
        camera = self.camera({"space_utilization": FULL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_route_completion(self):
        function_id = "route-completion-ledger"
        fn = self.function(function_id, {"digest_seconds": 100})
        self.boxes(
            fn,
            [[box(1, 0.2)], [box(1, 0.45)], [box(1, 0.7)], [box(1, 0.9)], []],
        )
        camera = self.camera(
            {
                "route_checkpoint_a": A,
                "route_checkpoint_b": B,
                "route_checkpoint_c": C,
                "route_checkpoint_d": D,
            }
        )
        for ts in (100, 101, 102, 103, 201):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_schedule_baseline(self):
        function_id = "zone-activity-schedule-baseline"
        fn = self.function(
            function_id, {"min_samples": 2, "change_threshold": 1, "hold_seconds": 0}
        )
        self.boxes(fn, [[], [], [box(1, 0.5), box(2, 0.6), box(3, 0.7)]])
        camera = self.camera({"schedule_activity": FULL})
        for ts in (100, 101, 102):
            fn.process(camera, FRAME, ts, self.ctx)
        return function_id

    def exercise_shift_flow(self):
        function_id = "shift-change-flow-review"
        fn = self.function(
            function_id,
            {"shift_windows": ["00:00-23:59"], "digest_seconds": 1},
        )
        self.boxes(fn, [[box(1, 0.2)], [box(1, 0.8)]])
        camera = self.camera({"shift_change_area": FULL, "shift_ingress_line": VERTICAL})
        fn.process(camera, FRAME, 100, self.ctx)
        fn.process(camera, FRAME, 102, self.ctx)
        return function_id

    def exercise_evidence_casebook(self):
        function_id = "exception-evidence-casebook"
        fn = self.function(function_id, {"collect_seconds": 1})
        self.ctx.access_events = [
            {"id": "denied", "ts": 100, "type": "denied", "door_id": "door-1"}
        ]
        self.boxes(fn, [[box(1, 0.5)], []])
        camera = self.camera()
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("VISION_DATA")
            os.environ["VISION_DATA"] = directory
            try:
                fn.process(camera, FRAME, 100, self.ctx)
                fn.process(camera, FRAME, 102, self.ctx)
                self.assertEqual(len(list(Path(directory).rglob("*.json"))), 1)
            finally:
                if previous is None:
                    os.environ.pop("VISION_DATA", None)
                else:
                    os.environ["VISION_DATA"] = previous
        return function_id


if __name__ == "__main__":
    unittest.main()
