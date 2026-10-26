from __future__ import annotations

import calendar
import os
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.modules.setdefault("cv2", types.ModuleType("cv2"))

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pydantic.networks as pydantic_networks


def _test_validate_email(value, **_kwargs):
    text = str(value)
    return SimpleNamespace(normalized=text, local_part=text.partition("@")[0])


setattr(pydantic_networks, "email_validator", SimpleNamespace(validate_email=_test_validate_email))
setattr(pydantic_networks, "import_email_validator", lambda: None)

import api
from alerts import AlertEngine
from detectors import bed_exit, fall, ppe, tailgating, video_search
from main import Pipeline
from marketplace import contract
from marketplace.functions import aggression_posture, dock_slip_occupancy, dock_utilization, route_verification
from streams import StreamManager
from subscriptions import app as subscription_app
from subscriptions import store
import unifi_access


class _Alerts:
    def __init__(self, result=True):
        self.events = []
        self.result = result

    def fire(self, **event):
        self.events.append(event)
        return self.result

    def stats(self):
        return {}


class _Result:
    names = {}
    boxes = []


class RuntimeBlockerTests(unittest.TestCase):
    def test_marketplace_inference_uses_configured_cpu_device(self):
        frame = SimpleNamespace(shape=(16, 16, 3))
        model = Mock()
        model.predict.return_value = [_Result()]
        with patch.dict(os.environ, {"VISION_DEVICE": "cpu"}, clear=False), patch.object(
            contract, "model", return_value=model
        ) as load_model:
            contract.boxes_of(frame)
        load_model.assert_called_once_with("yolov8n.pt", "cpu")
        model.predict.assert_called_once()
        model.track.assert_not_called()

    def test_boxes_of_returns_numeric_classes_and_normalized_geometry(self):
        frame = SimpleNamespace(shape=(100, 200, 3))
        box = SimpleNamespace(
            cls=np.array([5]),
            xyxy=np.array([[20.0, 10.0, 100.0, 90.0]]),
        )
        result = SimpleNamespace(boxes=[box])
        fake_model = Mock()
        fake_model.predict.return_value = [result]
        if hasattr(contract, "_tracker_cache"):
            contract._tracker_cache.clear()
        with patch.object(contract, "model", return_value=fake_model):
            detection = contract.boxes_of(frame, classes=[5])[0]
        cls, cx, cy, x1, y1, x2, y2, track_id = detection
        self.assertEqual(cls, 5)
        self.assertEqual((cx, cy), (0.3, 0.5))
        self.assertEqual((x1, y1, x2, y2), (0.1, 0.1, 0.5, 0.9))
        self.assertIsInstance(track_id, int)

    def test_zone_tracker_resets_dwell_after_unobserved_gap(self):
        tracker = contract.ZoneTracker(max_gap_seconds=5)
        entered, dwell, _ = tracker.update("track", True, 0)
        self.assertTrue(entered)
        self.assertEqual(dwell, 0)
        entered, dwell, _ = tracker.update("track", True, 2)
        self.assertFalse(entered)
        self.assertEqual(dwell, 2)
        entered, dwell, state = tracker.update("track", True, 10)
        self.assertTrue(entered)
        self.assertEqual(dwell, 0)
        self.assertEqual(state["visits"], [10])

    def test_normalized_corner_consumers_convert_only_at_pixel_crops(self):
        normalized_height_files = (
            "child_safety_zone.py",
            "daycare_ratio.py",
            "playground_alone.py",
        )
        for filename in normalized_height_files:
            source = (SRC / "marketplace" / "functions" / filename).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"\(y2\s*-\s*y1\)\s*/\s*h|\(b\[5\]\s*-\s*b\[3\]\)\s*/\s*h")
        for filename in (
            "detail_qc_walk.py",
            "lab_coat_zone.py",
            "repeat_visitor.py",
            "uniform_check.py",
            "visitor_badge_check.py",
        ):
            source = (SRC / "marketplace" / "functions" / filename).read_text(encoding="utf-8")
            self.assertIn("pixel_box", source, filename)

    def test_fall_state_is_per_person_and_checks_all_poses(self):
        detector = fall.FallDetector({"floor_angle_seconds": 2})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", alerts=alerts)
        camera = {"id": "cam", "name": "Camera"}
        angles = [(1, 5.0), (2, 80.0)]
        detector._process_angles(camera, object(), 10.0, context, angles)
        detector._process_angles(camera, object(), 12.0, context, angles)
        self.assertEqual(len(alerts.events), 1)
        self.assertEqual(alerts.events[0]["meta"]["track"], 2)

    def test_bed_exit_sequence_cannot_stitch_different_people(self):
        detector = bed_exit.BedExitDetector({"window_seconds": 20})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", alerts=alerts)
        camera = {"id": "cam", "name": "Camera"}
        detector._advance(camera, 1, "lying", 1.0, context)
        detector._advance(camera, 2, "sitting", 2.0, context)
        detector._advance(camera, 2, "edge", 3.0, context)
        self.assertEqual(alerts.events, [])
        detector._advance(camera, 2, "lying", 4.0, context)
        detector._advance(camera, 2, "sitting", 5.0, context)
        detector._advance(camera, 2, "edge", 6.0, context)
        self.assertEqual(len(alerts.events), 1)

    def test_ppe_items_are_associated_per_person(self):
        people = [
            (1, (0.0, 0.0, 0.4, 1.0)),
            (2, (0.6, 0.0, 1.0, 1.0)),
        ]
        items = [
            ("hardhat", (0.2, 0.1)),
            ("hi-vis", (0.2, 0.5)),
        ]
        missing = ppe.PPEDetector._missing_by_person(people, items, {"hardhat", "hi-vis"})
        self.assertEqual(missing, {2: {"hardhat", "hi-vis"}})

    def test_all_inference_uses_shared_serialized_predict_path(self):
        offenders = []
        for path in (SRC / "detectors").glob("*.py"):
            if path.name == "base.py":
                continue
            source = path.read_text(encoding="utf-8")
            if ".track(" in source or re.search(r"(?:self\._model|\bmodel\([^\n]+\))\(frame", source):
                offenders.append(path.name)
        for path in (SRC / "marketplace" / "functions").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            if ".track(" in source or re.search(r"(?:self\._model|\bmodel\([^\n]+\))\(frame", source):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_aggression_motion_state_uses_track_identity_not_pose_order(self):
        function = aggression_posture.Function({"sustain_seconds": 1})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", alerts=alerts)
        camera = {"id": "cam", "name": "Camera"}
        function._process_signals(camera, object(), 1.0, context, [(11, True), (22, False)])
        function._process_signals(camera, object(), 2.0, context, [(22, False), (11, True)])
        self.assertEqual(len(alerts.events), 1)
        self.assertEqual(alerts.events[0]["meta"]["track"], 11)

    def test_model_cache_is_scoped_by_weights_and_device(self):
        contract._model_cache.clear()
        created = []

        class FakeModel:
            def __init__(self, weights):
                self.weights = weights
                self.device = None
                created.append(self)

            def to(self, device):
                self.device = device

        fake_ultralytics = types.ModuleType("ultralytics")
        fake_ultralytics.YOLO = FakeModel
        with patch.dict(sys.modules, {"ultralytics": fake_ultralytics}):
            cpu = contract.model("model.pt", "cpu")
            cuda = contract.model("model.pt", "cuda")
        self.assertIsNot(cpu, cuda)
        self.assertEqual([item.device for item in created], ["cpu", "cuda"])

    def test_stream_manager_keeps_unresolved_cameras_not_ready(self):
        manager = StreamManager(
            [{"id": "one", "name": "One", "rtsp": "file.mp4"}, {"id": "two", "name": "Two"}],
            1.0,
            lambda *_: None,
        )
        self.assertEqual(len(manager.workers), 2)
        self.assertFalse(manager.workers[1].connected)

    def test_readiness_requires_all_configured_cameras_and_recent_frames(self):
        now = 1_800_000_000.0
        pipeline = SimpleNamespace(
            site="Test Site",
            cameras=[{"id": "one"}, {"id": "two"}],
            alerts=_Alerts(),
            camera_detectors={},
            detector_failures={},
        )
        worker = SimpleNamespace(connected=True, last_frame_at=now)
        streams = SimpleNamespace(workers=[worker], status=lambda: [])
        with patch.object(store, "init_db", return_value=None), patch("api.time.time", return_value=now), patch.dict(
            os.environ, {"VISION_READY_MAX_FRAME_AGE_SECONDS": "30"}, clear=False
        ):
            client = TestClient(api.create_app(pipeline, streams))
            self.assertEqual(client.get("/ready").status_code, 503)
            pipeline.cameras = [{"id": "one"}]
            worker.last_frame_at = None
            self.assertEqual(client.get("/ready").status_code, 503)
            worker.last_frame_at = now - 31
            self.assertEqual(client.get("/ready").status_code, 503)
            worker.last_frame_at = now - 1
            self.assertEqual(client.get("/ready").status_code, 200)

    def test_readiness_rejects_current_license_when_requested_mapping_is_denied(self):
        now = 1_800_000_000.0
        license_service = Mock()
        license_service.status.return_value = {
            "state": "current",
            "reason": "authorized",
            "paid_runtime_authorized": True,
        }
        pipeline = SimpleNamespace(
            site="Test Site",
            cameras=[{"id": "one"}],
            alerts=_Alerts(),
            camera_detectors={},
            detector_failures={},
            license_service=license_service,
            licensing_enforced=True,
            requested_detector_count=1,
            license_authorization=SimpleNamespace(
                authorized=False,
                state="current",
                reason="function_not_granted",
            ),
        )
        worker = SimpleNamespace(connected=True, last_frame_at=now)
        streams = SimpleNamespace(workers=[worker], status=lambda: [])
        with patch.object(store, "init_db", return_value=None), patch(
            "api.time.time", return_value=now
        ):
            response = TestClient(api.create_app(pipeline, streams)).get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])

    def test_detector_exception_does_not_skip_later_detector_and_degrades_readiness(self):
        calls = []

        class Broken:
            name = "broken"

            def process(self, *_args):
                raise RuntimeError("boom")

        class Good:
            name = "good"

            def process(self, *_args):
                calls.append("good")

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._detector_lock = threading.RLock()
        pipeline.camera_detectors = {"cam": [Broken(), Good()]}
        pipeline.detector_failures = {}
        pipeline.api_runtime = None
        pipeline.on_frame({"id": "cam", "name": "Camera"}, object(), 123.0)
        self.assertEqual(calls, ["good"])
        self.assertIn("cam:broken", pipeline.detector_failures)

    def test_pipeline_sets_camera_detector_tracking_scope(self):
        observed = []

        class Probe:
            name = "probe"

            def __init__(self, _settings):
                pass

            def process(self, _camera, _frame, _ts, _ctx):
                observed.append(contract.current_tracking_scope())

        config = {
            "site": {"name": "Site", "timezone": "UTC"},
            "cameras": [{"id": "cam", "name": "Camera", "detectors": ["probe"]}],
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            pipeline = Pipeline(config, {"probe": Probe})
            pipeline.on_frame(config["cameras"][0], object(), 1.0)
        self.assertEqual(observed, [("cam", "probe")])

    def test_license_refresh_error_disables_active_paid_runtime(self):
        class Probe:
            name = "probe"

            def __init__(self, _settings):
                pass

            def process(self, *_args):
                pass

        class LicenseServiceProbe:
            def __init__(self):
                self.calls = 0

            def authorize_configuration(self, config):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("entitlement refresh unavailable")
                return SimpleNamespace(
                    authorized=True,
                    state="current",
                    reason="ok",
                    effective_config=config,
                    stream_count=1,
                    distinct_function_count=1,
                    granted_function_ids=frozenset({"probe"}),
                )

        config = {
            "site": {"name": "Site", "timezone": "UTC"},
            "cameras": [{"id": "cam", "name": "Camera", "detectors": ["probe"]}],
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"VISION_DATA": temporary}, clear=False
        ):
            pipeline = Pipeline(config, {"probe": Probe}, license_service=LicenseServiceProbe())
            self.assertEqual(len(pipeline.camera_detectors["cam"]), 1)
            changed = pipeline.refresh_license()

        self.assertTrue(changed)
        self.assertFalse(pipeline.license_authorization.authorized)
        self.assertEqual(pipeline.license_authorization.state, "invalid")
        self.assertEqual(pipeline.license_authorization.reason, "license_refresh_error")
        self.assertEqual(pipeline.camera_detectors["cam"], [])
        self.assertEqual(pipeline.entitled_detector_ids, set())

    def test_tailgating_counts_newest_first_and_equal_timestamp_badges(self):
        now = 1_800_000_000.0
        detector = tailgating.TailgatingDetector(
            {"door_id": "door-main", "window_seconds": 6, "max_persons_per_badge": 1}
        )
        alerts = _Alerts()
        context = SimpleNamespace(
            site="Test Site",
            alerts=alerts,
            access_events=[
                {"id": "newer", "door_id": "door-main", "ts": int((now - 1) * 1000), "credential_granted": True},
                {"id": "older", "door_id": "door-main", "ts": int((now - 2) * 1000), "credential_granted": True},
                {"id": "same-a", "door_id": "door-main", "ts": int((now - 3) * 1000), "credential_granted": True},
                {"id": "same-b", "door_id": "door-main", "ts": int((now - 3) * 1000), "credential_granted": True},
            ],
        )
        with patch.object(tailgating, "boxes_of", return_value=[object()] * 4, create=True):
            detector.process({"id": "cam", "name": "Entry"}, object(), now, context)
        self.assertEqual(alerts.events, [])
        self.assertEqual(len(detector._badges), 4)

    def test_tailgating_ignores_access_events_without_explicit_credential_grant(self):
        now = 1_800_000_000.0
        detector = tailgating.TailgatingDetector(
            {"door_id": "door-main", "window_seconds": 6, "max_persons_per_badge": 1}
        )
        alerts = _Alerts()
        context = SimpleNamespace(
            site="Test Site",
            alerts=alerts,
            access_events=[
                {"id": "denied", "door_id": "door-main", "ts": int((now - 1) * 1000), "credential_granted": False},
                {"id": "forced", "door_id": "door-main", "ts": int((now - 2) * 1000), "credential_granted": False},
                {"id": "remote", "door_id": "door-main", "ts": int((now - 3) * 1000), "credential_granted": False},
            ],
        )
        with patch.object(tailgating, "boxes_of", return_value=[object()] * 3, create=True):
            detector.process({"id": "cam", "name": "Entry"}, object(), now, context)
        self.assertEqual(detector._badges, [])
        self.assertEqual(alerts.events, [])

    def test_access_poller_marks_only_explicit_credential_grants(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "hits": [
                    {"id": "grant", "event_time": 1000, "event_type": "credential_granted", "door_id": "door-main"},
                    {"id": "denied", "event_time": 2000, "event_type": "access_denied", "door_id": "door-main"},
                    {"id": "remote", "event_time": 3000, "event_type": "access.door.unlock", "door_id": "door-main"},
                ]
            },
        )
        with patch.dict(
            os.environ,
            {"UNIFI_ACCESS_HOST": "access.invalid", "UNIFI_ACCESS_TOKEN": "unit-test-token"},
            clear=False,
        ), patch("unifi_access.requests.get", return_value=response):
            poller = unifi_access.AccessPoller(lambda _event: None)
            poller._last_seen = 0
            events = poller._poll_once()
        self.assertEqual([event["id"] for event in events], ["grant", "denied", "remote"])
        self.assertEqual([event["credential_granted"] for event in events], [True, False, False])

    def test_failed_alert_is_persisted_and_retryable_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "BASE44_ALERT_URL": "https://alerts.invalid/ingest",
                "BASE44_INTERNAL_TOKEN": "unit-test-destination-token",
                "EXTRA_WEBHOOK_URL": "",
            },
            clear=False,
        ):
            config = {"alerts": {"dedup_seconds": 120, "retry_interval_seconds": 0}}
            failed = SimpleNamespace(status_code=500)
            with patch("alerts.requests.post", return_value=failed):
                first = AlertEngine(config, temporary)
                delivered = first.fire(
                    site="Site",
                    camera={"id": "cam", "name": "Camera"},
                    detector="tailgating",
                    title="Possible tailgating",
                    detail="review",
                )
            self.assertFalse(delivered)
            self.assertEqual(first.pending_count(), 1)
            self.assertTrue((Path(temporary) / "alert-outbox.json").exists())
            first_metrics = first.destination_stats()["base44"]
            self.assertEqual(first_metrics["failed"], 1)
            self.assertEqual(first_metrics["pending"], 1)

            succeeded = SimpleNamespace(status_code=200)
            with patch("alerts.requests.post", return_value=succeeded):
                restarted = AlertEngine(config, temporary)
                self.assertEqual(restarted.pending_count(), 1)
                self.assertEqual(restarted.retry_pending(), 1)
                self.assertEqual(restarted.pending_count(), 0)
                restarted_metrics = restarted.destination_stats()["base44"]
                self.assertEqual(restarted_metrics["retried"], 1)
                self.assertEqual(restarted_metrics["pending"], 0)

    def test_snapshot_and_embedding_retention_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots = root / "snapshots"
            snapshots.mkdir()
            for index in range(4):
                path = snapshots / f"snapshot-{index}.jpg"
                path.write_bytes(b"x")
                os.utime(path, (100 + index, 100 + index))
            engine = AlertEngine(
                {"alerts": {"retry_interval_seconds": 0, "snapshot_max_files": 2, "snapshot_retention_days": 0}},
                temporary,
            )
            engine.prune_storage(now=1_000)
            self.assertLessEqual(len(list(snapshots.glob("*.jpg"))), 2)

            embeddings = root / "embeddings"
            embeddings.mkdir()
            for index in range(4):
                path = embeddings / f"embedding-{index}.npy"
                path.write_bytes(b"x")
                os.utime(path, (100 + index, 100 + index))
            video_search.prune_embeddings(embeddings, max_files=2, retention_days=0, now=1_000)
            self.assertLessEqual(len(list(embeddings.glob("*.npy"))), 2)

    def test_route_summary_emits_once_per_day(self):
        function = route_verification.Function({"window": [2, 7]})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", timezone="America/Chicago", alerts=alerts)
        camera = {
            "id": "cam",
            "name": "Route Camera",
            "zones": {"route_zones": {"north": [[0, 0], [1, 0], [1, 1], [0, 1]]}},
        }
        timestamp = calendar.timegm((2026, 8, 15, 11, 0, 0, 0, 0, 0))
        with patch.object(route_verification, "boxes_of", return_value=[(2, 0.5, 0.5)]), patch.object(
            route_verification, "in_zone", return_value=True
        ):
            function.process(camera, object(), timestamp, context)
            function.process(camera, object(), timestamp + 1, context)
            self.assertEqual(alerts.events, [])
            function.process(camera, object(), timestamp + 3600, context)
            function.process(camera, object(), timestamp + 3601, context)
        self.assertEqual(len(alerts.events), 1)

    def test_dock_utilization_emits_daily_summary_once(self):
        function = dock_utilization.Function({"summary_hour": 23})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", timezone="America/Chicago", alerts=alerts)
        camera = {
            "id": "cam",
            "name": "Dock Camera",
            "zones": {"docks": {"dock-1": [[0, 0], [1, 0], [1, 1], [0, 1]]}},
        }
        start = calendar.timegm((2026, 8, 16, 3, 0, 0, 0, 0, 0))  # 22:00 CDT
        with patch.object(dock_utilization, "boxes_of", side_effect=[[('truck', 0.5, 0.5)], [], []]), patch.object(
            dock_utilization, "in_zone", return_value=True
        ):
            function.process(camera, object(), start, context)
            function.process(camera, object(), start + 3600, context)
            function.process(camera, object(), start + 3601, context)
        self.assertEqual(len(alerts.events), 1)
        self.assertIn("utilization", alerts.events[0]["title"].lower())

    def test_marketplace_boxes_use_numeric_class_ids_and_normalized_area(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SRC / "marketplace" / "functions").glob("*.py")
        )
        self.assertNotRegex(source, r"\bcls\s*(?:==|!=)\s*[\"']person[\"']")
        self.assertNotRegex(source, r"\bcls\s+(?:in|not in)\s*\([^)]*[\"']person[\"']")
        self.assertNotRegex(source, r"\(x2\s*-\s*x1\).*\(y2\s*-\s*y1\).*frame\.shape")

        alerts = _Alerts()
        context = SimpleNamespace(site="Site", timezone="America/Chicago", alerts=alerts)
        camera = {
            "id": "dock",
            "name": "Dock",
            "zones": {"slips": {"A": [[0, 0], [1, 0], [1, 1], [0, 1]]}},
        }
        function = dock_slip_occupancy.Function({"check_hour": 6, "min_object_ratio": 0.02})
        timestamp = calendar.timegm((2026, 8, 15, 11, 0, 0, 0, 0, 0))
        frame = SimpleNamespace(shape=(100, 100, 3))
        normalized_vehicle = (2, 0.5, 0.5, 0.2, 0.2, 0.5, 0.5, 1)
        with patch.object(dock_slip_occupancy, "boxes_of", return_value=[normalized_vehicle]):
            function.process(camera, frame, timestamp, context)
        self.assertEqual(len(alerts.events), 1)
        self.assertIn("A: occupied", alerts.events[0]["detail"])


class PublicApiBlockerTests(unittest.TestCase):
    @staticmethod
    def _pipeline():
        return SimpleNamespace(
            site="Test Site",
            cameras=[],
            alerts=_Alerts(),
            camera_detectors={"cam": []},
            detector_failures={},
        )

    def test_signup_schema_bounds_functions_and_free_text(self):
        payload = {
            "company": "Nexus",
            "contactName": "Operator",
            "email": "operator@example.com",
            "tier": "starter",
            "functions": [f"module-{index}" for index in range(131)],
        }
        with self.assertRaises(ValidationError):
            subscription_app.SignupRequest.model_validate(payload)
        payload["functions"] = ["x" * 81]
        with self.assertRaises(ValidationError):
            subscription_app.SignupRequest.model_validate(payload)
        payload["functions"] = []
        payload["notes"] = "x" * 2001
        with self.assertRaises(ValidationError):
            subscription_app.SignupRequest.model_validate(payload)

    def test_signup_rate_limit_blocks_repeated_source(self):
        row = {
            "id": "SUB-test",
            "company": "Nexus",
            "contact_name": "Operator",
            "email": "operator@example.com",
            "phone": "",
            "industry": "",
            "tier": "starter",
            "sites": 1,
            "cameras": None,
            "functions": "[]",
        }
        streams = SimpleNamespace(workers=[], status=lambda: [])
        payload = {
            "company": "Nexus",
            "contactName": "Operator",
            "email": "operator@example.com",
            "tier": "starter",
            "functions": [],
        }
        with patch.object(store, "init_db", return_value=None), patch.object(
            store, "create_sub", return_value=row
        ), patch.object(store, "forward_to_base44", return_value=False), patch.dict(
            os.environ, {"VISION_SIGNUP_RATE_LIMIT_PER_MINUTE": "2"}, clear=False
        ):
            client = TestClient(api.create_app(self._pipeline(), streams))
            self.assertEqual(client.post("/api/subscriptions", json=payload).status_code, 200)
            self.assertEqual(client.post("/api/subscriptions", json=payload).status_code, 200)
            self.assertEqual(client.post("/api/subscriptions", json=payload).status_code, 429)

    def test_subscription_store_has_a_hard_record_cap(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            store, "DB_PATH", Path(temporary) / "subscriptions.db"
        ), patch.dict(os.environ, {"VISION_SUBSCRIPTION_MAX_RECORDS": "1"}, clear=False):
            store.init_db()
            payload = {
                "company": "Nexus",
                "contactName": "Operator",
                "email": "operator@example.com",
                "tier": "starter",
                "functions": [],
            }
            store.create_sub(payload)
            with self.assertRaises(store.SubscriptionCapacityError):
                store.create_sub(payload)

    def test_operational_routes_require_admin_token(self):
        now = time.time()
        worker = SimpleNamespace(connected=True, last_frame_at=now, status=lambda: {})
        streams = SimpleNamespace(workers=[worker], status=lambda: [{"camera": "Camera"}])
        pipeline = self._pipeline()
        pipeline.cameras = [{"id": "cam"}]
        with patch.object(store, "init_db", return_value=None), patch.dict(
            os.environ, {"VISION_ADMIN_TOKEN": "unit-test-admin-token"}, clear=False
        ), patch("detectors.video_search.search", return_value=[]):
            client = TestClient(api.create_app(pipeline, streams))
            for path in ("/streams", "/detectors", "/search?q=truck"):
                self.assertEqual(client.get(path).status_code, 401)
                self.assertEqual(client.get(path, headers={"x-admin-token": "wrong"}).status_code, 401)
                self.assertEqual(
                    client.get(path, headers={"x-admin-token": "unit-test-admin-token"}).status_code,
                    200,
                )


class ReleaseContractTests(unittest.TestCase):
    def test_env_example_has_unique_keys(self):
        keys = []
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                keys.append(stripped.split("=", 1)[0])
        self.assertEqual(len(keys), len(set(keys)), "duplicate keys in .env.example")

    def test_lead_form_exposes_common_input_purposes(self):
        source = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
        for field_id, token in (
            ("company", "organization"),
            ("contact-name", "name"),
            ("work-email", "email"),
            ("phone", "tel"),
        ):
            element = re.search(rf'<input[^>]*id="{field_id}"[^>]*>', source)
            if element is None:
                self.fail(f"missing input {field_id}")
            self.assertIn(f'autocomplete="{token}"', element.group(0))

    def test_social_preview_images_are_absolute_https_urls(self):
        values = []
        for relative in ("landing/index.html", "storefront/index.html", "guide/index.html"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            values.extend(
                re.findall(
                    r'<meta (?:property|name)="(?:og:image|twitter:image)" content="([^"]+)"',
                    source,
                )
            )
        self.assertEqual(len(values), 6)
        self.assertTrue(all(value.startswith("https://") for value in values), values)

    def test_cuda_121_torch_pairing_is_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        public_hardware_copy = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8").casefold()
            for relative in ("README.md", "landing/index.html", "guide/index.html")
        )
        self.assertIn("torch==2.5.1", requirements)
        self.assertIn("torchvision==0.20.1", requirements)
        self.assertIn("--index-url https://download.pytorch.org/whl/cu121", dockerfile)
        self.assertNotIn("--extra-index-url https://download.pytorch.org/whl/cu121", dockerfile)
        self.assertEqual(compose.count("platform: linux/amd64"), 2)
        self.assertIsNone(re.search(r"\b(?:jetson|orin)\b", public_hardware_copy))

    def test_runtime_claims_are_observable_signals_only(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py")).casefold()
        landing = (ROOT / "landing" / "index.html").read_text(encoding="utf-8").casefold()
        storefront = (ROOT / "storefront" / "index.html").read_text(encoding="utf-8").casefold()
        guide = (ROOT / "guide" / "index.html").read_text(encoding="utf-8").casefold()
        all_text = "\n".join((text, landing, storefront, guide))
        for phrase in (
            "specimen drop confirmed",
            "unscheduled vendor arrival",
            "hygiene gap",
            "without a sink visit",
            "person under crane load path",
            "snow/ice accumulation",
            "lone child outside recess window",
            "children /",
            "unbadged person",
            "pre-assault posture",
            "seconds of notice before an incident",
            "trigger building lockdown",
            "lockdown trigger",
            "any protect camera",
            "expected-vendor lists",
            "occupancy proof matters",
            "child left behind",
            "unauthorized liveaboard",
            "compliance alert",
            "auction compliance photos",
            "break-in attempts",
            "separately configured clip exports",
            "child-height and adult-height figures",
            "over posted limit",
            "before the temp sensors move",
            "kill people",
            "crane zone shows activity",
            "tenant quietly living",
            "settle with the camera log",
            "before customers walk out",
            "premise-safety trigger",
            "evidence preservation",
        ):
            self.assertNotIn(phrase, all_text)
        self.assertNotIn("access-event correlation (tailgating, vendor windows)", landing)

        guide = (ROOT / "guide" / "index.html").read_text(encoding="utf-8")
        self.assertIn("X-Admin-Token: $VISION_ADMIN_TOKEN", guide)
        self.assertIn("connected: true", guide)
        self.assertNotIn("up: true", guide)

    def test_mobile_dialog_uses_a_dedicated_labeled_table_scroller(self):
        source = (ROOT / "storefront" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="config-table-scroll"', source)
        self.assertIn('role="region"', source)
        self.assertIn('tabindex="0"', source)
        self.assertIn(".config-table-scroll", source)


if __name__ == "__main__":
    unittest.main()
