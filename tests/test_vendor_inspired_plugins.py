from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace.contract import MarketplaceFunction, validate_manifest


PLUGIN_MODULES = [
    "hardhat_visibility_review",
    "high_visibility_vest_review",
    "smoke_flame_visual_review",
    "plate_watchlist_review",
    "vehicle_attribute_log",
    "parking_violation_dwell",
    "stopped_vehicle_lane",
    "traffic_queue_spillback",
    "unusual_dwell_baseline",
    "queue_abandonment_review",
    "pedestrian_vehicle_conflict",
    "forklift_pedestrian_proximity",
    "perimeter_climb_review",
    "vehicle_wrong_way",
    "occupancy_flow_anomaly",
    "floor_water_change_review",
    "unusual_motion_baseline",
    "object_removal_review",
    "assembly_stage_order_review",
    "shipping_label_presence_review",
]
PLUGIN_IDS = {name.replace("_", "-") for name in PLUGIN_MODULES}
FULL_ZONE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


class _Alerts:
    def __init__(self):
        self.events = []

    def fire(self, **event):
        self.events.append(event)
        return True


def _context():
    return SimpleNamespace(site="Test Site", alerts=_Alerts())


def _camera(**zones):
    return {"id": "cam-1", "name": "Camera 1", "zones": zones}


def _module(name: str):
    return importlib.import_module(f"marketplace.functions.{name}")


class VendorInspiredInventoryTests(unittest.TestCase):
    def test_exactly_20_unique_plugins_have_valid_executable_contracts(self):
        self.assertEqual(len(PLUGIN_MODULES), 20)
        self.assertEqual(len(PLUGIN_IDS), 20)
        observed = set()
        for module_name in PLUGIN_MODULES:
            module = _module(module_name)
            observed.add(module.MANIFEST["id"])
            self.assertEqual(validate_manifest(module.MANIFEST), [], module_name)
            self.assertTrue(issubclass(module.Function, MarketplaceFunction), module_name)
            self.assertIsNot(module.Function.process, MarketplaceFunction.process, module_name)
        self.assertEqual(observed, PLUGIN_IDS)

    def test_core_detector_adapters_rewrite_events_to_plugin_ids(self):
        for module_name in (
            "hardhat_visibility_review",
            "high_visibility_vest_review",
            "smoke_flame_visual_review",
            "pedestrian_vehicle_conflict",
        ):
            module = _module(module_name)
            function = module.Function({})

            class _Detector:
                def process(self, camera, frame, ts, ctx):
                    ctx.alerts.fire(
                        site=ctx.site,
                        camera=camera,
                        detector="core-detector-id",
                        title="review",
                        detail="review",
                        frame=frame,
                        meta={"source": "core"},
                    )

            function._detector = _Detector()
            ctx = _context()
            function.process(_camera(), object(), 1.0, ctx)
            self.assertEqual(ctx.alerts.events[0]["detector"], module.MANIFEST["id"])

    def test_ppe_adapters_request_only_their_named_item(self):
        hardhat = _module("hardhat_visibility_review").Function({})
        vest = _module("high_visibility_vest_review").Function({})
        self.assertEqual(hardhat._detector.required, {"hardhat"})
        self.assertEqual(vest._detector.required, {"hi-vis"})


class VendorInspiredBehaviorTests(unittest.TestCase):
    def test_plate_watchlist_matches_normalized_candidate_and_redacts_plate(self):
        function = _module("plate_watchlist_review").Function(
            {"watchlist": ["ABC-123"], "min_confidence": 0.8}
        )
        ctx = _context()
        function.process_candidates(
            _camera(), object(), 1.0, ctx,
            [{"text": "abc 123", "confidence": 0.91}, {"text": "ZZZ999", "confidence": 0.99}],
        )
        self.assertEqual(len(ctx.alerts.events), 1)
        event = ctx.alerts.events[0]
        self.assertNotIn("ABC123", str(event))
        self.assertRegex(event["meta"]["plate_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(event["meta"]["plate_suffix"], "123")

    def test_vehicle_attribute_log_deduplicates_model_candidates(self):
        function = _module("vehicle_attribute_log").Function({"cooldown_seconds": 60})
        ctx = _context()
        observation = {"track_id": 7, "label": "red-suv", "confidence": 0.88}
        function.process_observations(_camera(), object(), 10.0, ctx, [observation])
        function.process_observations(_camera(), object(), 20.0, ctx, [observation])
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["classification"], "red-suv")

    def test_parking_violation_requires_sustained_vehicle_dwell(self):
        function = _module("parking_violation_dwell").Function({"hold_seconds": 5})
        ctx = _context()
        detection = {"track_id": 1, "class_id": 2, "cx": 0.5, "cy": 0.5}
        function.process_observations(_camera(), object(), 0.0, ctx, [detection], FULL_ZONE)
        function.process_observations(_camera(), object(), 5.0, ctx, [detection], FULL_ZONE)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertGreaterEqual(ctx.alerts.events[0]["meta"]["dwell_seconds"], 5)

    def test_stopped_vehicle_requires_low_motion_for_hold_period(self):
        function = _module("stopped_vehicle_lane").Function(
            {"hold_seconds": 5, "movement_threshold": 0.02}
        )
        ctx = _context()
        function.process_positions(_camera(), object(), 0.0, ctx, {9: (0.5, 0.5)})
        function.process_positions(_camera(), object(), 5.0, ctx, {9: (0.505, 0.5)})
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["vehicle_track"], 9)

    def test_traffic_spillback_requires_sustained_count(self):
        function = _module("traffic_queue_spillback").Function(
            {"vehicle_threshold": 3, "hold_seconds": 5}
        )
        ctx = _context()
        function.process_count(_camera(), object(), 0.0, ctx, 3)
        function.process_count(_camera(), object(), 5.0, ctx, 4)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["vehicle_count"], 4)

    def test_unusual_dwell_uses_completed_local_baseline(self):
        function = _module("unusual_dwell_baseline").Function(
            {"min_samples": 5, "minimum_seconds": 10, "anomaly_factor": 2}
        )
        ctx = _context()
        for value in (10, 11, 12, 10, 11):
            function.record_completed_dwell("cam-1", value)
        function.process_current_dwell(_camera(), object(), 100.0, ctx, 4, 30.0)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["track"], 4)
        self.assertEqual(ctx.alerts.events[0]["meta"]["baseline_samples"], 5)

    def test_queue_abandonment_requires_queue_dwell_without_service_entry(self):
        function = _module("queue_abandonment_review").Function(
            {"minimum_wait_seconds": 5, "missing_grace_seconds": 1}
        )
        ctx = _context()
        function.process_tracks(
            _camera(), object(), 0.0, ctx, {3: (0.2, 0.2)}, FULL_ZONE, []
        )
        function.process_tracks(
            _camera(), object(), 5.0, ctx, {3: (0.2, 0.2)}, FULL_ZONE, []
        )
        function.process_tracks(_camera(), object(), 7.0, ctx, {}, FULL_ZONE, [])
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["track"], 3)

    def test_forklift_proximity_associates_person_and_forklift(self):
        function = _module("forklift_pedestrian_proximity").Function(
            {"distance_ratio": 0.2}
        )
        ctx = _context()
        observations = [
            {"track_id": 1, "label": "person", "cx": 0.5, "cy": 0.5},
            {"track_id": 2, "label": "forklift", "cx": 0.6, "cy": 0.5},
        ]
        function.process_detections(_camera(), object(), 1.0, ctx, observations)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["forklift_track"], 2)

    def test_perimeter_climb_requires_sustained_pose_signal(self):
        function = _module("perimeter_climb_review").Function({"hold_seconds": 2})
        ctx = _context()
        signal = [{"track_id": 8, "near_boundary": True, "climb_pose": True}]
        function.process_signals(_camera(), object(), 0.0, ctx, signal)
        function.process_signals(_camera(), object(), 2.0, ctx, signal)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["track"], 8)

    def test_vehicle_wrong_way_uses_directional_crossing(self):
        function = _module("vehicle_wrong_way").Function({"allowed_direction": 1})
        ctx = _context()
        line = [(0.0, 0.5), (1.0, 0.5)]
        function.process_tracks(_camera(), object(), 0.0, ctx, {5: (0.5, 0.6)}, line)
        function.process_tracks(_camera(), object(), 1.0, ctx, {5: (0.5, 0.4)}, line)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["vehicle_track"], 5)

    def test_occupancy_flow_anomaly_uses_prior_window_only(self):
        function = _module("occupancy_flow_anomaly").Function(
            {"min_samples": 5, "anomaly_factor": 2}
        )
        ctx = _context()
        for ts, count in enumerate((10, 11, 10, 9, 10)):
            function.process_count(_camera(), object(), float(ts), ctx, count)
        function.process_count(_camera(), object(), 10.0, ctx, 25)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["current_count"], 25)
        self.assertEqual(ctx.alerts.events[0]["meta"]["baseline_samples"], 5)

    def test_floor_water_change_requires_sustained_metric_change(self):
        function = _module("floor_water_change_review").Function(
            {"min_samples": 3, "change_threshold": 0.2, "hold_seconds": 2}
        )
        ctx = _context()
        for ts, value in enumerate((0.05, 0.06, 0.05)):
            function.process_metric(_camera(), object(), float(ts), ctx, value)
        function.process_metric(_camera(), object(), 10.0, ctx, 0.4)
        function.process_metric(_camera(), object(), 12.0, ctx, 0.42)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertIn("appearance", ctx.alerts.events[0]["title"].lower())

    def test_unusual_motion_uses_learned_metric_baseline(self):
        function = _module("unusual_motion_baseline").Function(
            {"min_samples": 3, "anomaly_factor": 3, "hold_seconds": 1}
        )
        ctx = _context()
        for ts, value in enumerate((0.01, 0.02, 0.01)):
            function.process_metric(_camera(), object(), float(ts), ctx, value)
        function.process_metric(_camera(), object(), 10.0, ctx, 0.2)
        function.process_metric(_camera(), object(), 11.0, ctx, 0.2)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["baseline_samples"], 3)

    def test_object_removal_requires_established_presence_then_absence(self):
        function = _module("object_removal_review").Function(
            {"baseline_samples": 3, "hold_seconds": 2, "minimum_present": 1}
        )
        ctx = _context()
        for ts in (0.0, 1.0, 2.0):
            function.process_count(_camera(), object(), ts, ctx, 2)
        function.process_count(_camera(), object(), 10.0, ctx, 0)
        function.process_count(_camera(), object(), 12.0, ctx, 0)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["current_count"], 0)

    def test_assembly_stage_flags_out_of_order_observation(self):
        function = _module("assembly_stage_order_review").Function(
            {"expected_sequence": ["pick", "fasten", "inspect"]}
        )
        ctx = _context()
        function.process_stage(_camera(), object(), 1.0, ctx, "pick")
        function.process_stage(_camera(), object(), 2.0, ctx, "inspect")
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["expected_stage"], "fasten")
        self.assertEqual(ctx.alerts.events[0]["meta"]["observed_stage"], "inspect")

    def test_shipping_label_requires_label_center_inside_package(self):
        function = _module("shipping_label_presence_review").Function({"hold_seconds": 2})
        ctx = _context()
        packages = [
            {"track_id": 12, "x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.6}
        ]
        labels = [{"cx": 0.9, "cy": 0.9}]
        function.process_observations(_camera(), object(), 0.0, ctx, packages, labels)
        function.process_observations(_camera(), object(), 2.0, ctx, packages, labels)
        self.assertEqual(len(ctx.alerts.events), 1)
        self.assertEqual(ctx.alerts.events[0]["meta"]["package_track"], 12)


if __name__ == "__main__":
    unittest.main()
