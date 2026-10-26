from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace import loader
from marketplace.api_runtime import APIFunctionRuntime, APIRuntimeError
from marketplace.runtime import build_camera_detectors


class AlertSink:
    def __init__(self):
        self.calls = []

    def fire(self, **kwargs):
        self.calls.append(kwargs)


class APIFunctionRuntimeTests(unittest.TestCase):
    def test_function_routes_are_strict_admin_protected_and_dual_authorized(self):
        sys.modules.setdefault("cv2", types.ModuleType("cv2"))
        from fastapi import APIRouter
        from fastapi.testclient import TestClient
        import api
        import subscriptions

        runtime = Mock()
        runtime.export_clip.return_value = {
            "path": "clips/example.mp4",
            "bytes": 10,
            "sha256": "a" * 64,
        }
        runtime.request_snapshot.return_value = {
            "status": "stored",
            "suppressed": False,
            "snapshot_path": "snapshots/example.jpg",
            "snapshot_bytes": 10,
            "snapshot_sha256": "b" * 64,
        }
        runtime.request_unlock.return_value = {
            "request_id": "request-one",
            "door_id": "door-one",
            "accepted": True,
        }
        licensing = Mock()
        licensing.allows_function.return_value = True
        licensing.allows_capability.return_value = True
        pipeline = types.SimpleNamespace(
            site="Test Site",
            cameras=[],
            alerts=types.SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            api_runtime=runtime,
            license_service=licensing,
            licensing_enforced=True,
            requested_detector_count=2,
        )
        streams = types.SimpleNamespace(workers=[], status=lambda: [])
        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        fake_store = types.ModuleType("subscriptions.store")
        fake_store.init_db = lambda: None
        fake_app = types.ModuleType("subscriptions.app")
        fake_app.router = APIRouter()
        with patch.dict(
            os.environ,
            {
                "VISION_ADMIN_TOKEN": "unit-test-admin-token",
                "VISION_CONTROL_TOKEN": "unit-test-control-token",
            },
            clear=False,
        ), patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules,
            {"subscriptions.store": fake_store, "subscriptions.app": fake_app},
        ):
            client = TestClient(api.create_app(pipeline, streams, setup_service=setup))
            clip_payload = {
                "function_id": "manual-bounded-clip-export",
                "camera_id": "camera-one",
                "start_ms": 1_800_000_000_000,
                "end_ms": 1_800_000_010_000,
            }
            self.assertEqual(
                client.post("/api/functions/protect/clip-export", json=clip_payload).status_code,
                401,
            )
            exported = client.post(
                "/api/functions/protect/clip-export",
                json=clip_payload,
                headers={"x-admin-token": "unit-test-admin-token"},
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            snapshot_payload = {
                "function_id": "manual-review-snapshot",
                "camera_id": "camera-one",
                "request_id": "snapshot-request-one",
            }
            self.assertEqual(
                client.post("/api/functions/protect/snapshot", json=snapshot_payload).status_code,
                401,
            )
            snapshot = client.post(
                "/api/functions/protect/snapshot",
                json=snapshot_payload,
                headers={"x-admin-token": "unit-test-admin-token"},
            )
            self.assertEqual(snapshot.status_code, 200, snapshot.text)
            self.assertNotIn("image", snapshot.json())
            self.assertEqual(
                client.post(
                    "/api/functions/protect/snapshot",
                    json=dict(snapshot_payload, unexpected="rejected"),
                    headers={"x-admin-token": "unit-test-admin-token"},
                ).status_code,
                422,
            )
            unlock_payload = {
                "function_id": "access-audited-unlock-request",
                "door_id": "door-one",
                "reason": "Approved vendor arrival",
                "request_id": "request-one",
            }
            self.assertEqual(
                client.post(
                    "/api/functions/access/unlock",
                    json=unlock_payload,
                    headers={"x-admin-token": "unit-test-admin-token"},
                ).status_code,
                401,
            )
            allowed = client.post(
                "/api/functions/access/unlock",
                json=unlock_payload,
                headers={
                    "x-admin-token": "unit-test-admin-token",
                    "Authorization": "Bearer unit-test-control-token",
                },
            )
            self.assertEqual(allowed.status_code, 200, allowed.text)
            invalid = dict(unlock_payload, unexpected="must be rejected")
            rejected = client.post(
                "/api/functions/access/unlock",
                json=invalid,
                headers={
                    "x-admin-token": "unit-test-admin-token",
                    "Authorization": "Bearer unit-test-control-token",
                },
            )
            self.assertEqual(rejected.status_code, 422)
            self.assertNotIn("must be rejected", rejected.text)
        runtime.export_clip.assert_called_once()
        runtime.request_unlock.assert_called_once()

    def test_pipeline_compiles_and_routes_api_functions_separately(self):
        cv2_stub = types.ModuleType("cv2")
        setattr(cv2_stub, "CAP_FFMPEG", 0)
        sys.modules.setdefault("cv2", cv2_stub)
        from main import Pipeline

        registry, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        classes = {
            function_id: entry["cls"]
            for function_id, entry in registry.items()
            if function_id in {
                "protect-camera-api-latency",
                "protect-event-poll-health",
                "protect-event-type-inventory",
                "rtsp-reconnect-rate",
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            previous_data = os.environ.get("VISION_DATA")
            previous_evidence = os.environ.get("VISION_EVIDENCE_DIR")
            os.environ["VISION_DATA"] = temporary
            os.environ["VISION_EVIDENCE_DIR"] = str(Path(temporary) / "evidence")
            try:
                pipeline = Pipeline(
                    {
                        "site": {"name": "Test Site", "timezone": "UTC"},
                        "cameras": [
                            {
                                "id": "camera-one",
                                "name": "Camera One",
                                "detectors": [
                                    "protect-camera-api-latency",
                                    "protect-event-poll-health",
                                    "protect-event-type-inventory",
                                    "rtsp-reconnect-rate",
                                ],
                            }
                        ],
                        "detector_settings": {},
                        "alerts": {},
                    },
                    classes,
                )
            finally:
                if previous_data is None:
                    os.environ.pop("VISION_DATA", None)
                else:
                    os.environ["VISION_DATA"] = previous_data
                if previous_evidence is None:
                    os.environ.pop("VISION_EVIDENCE_DIR", None)
                else:
                    os.environ["VISION_EVIDENCE_DIR"] = previous_evidence
        self.assertEqual(pipeline.camera_detectors, {"camera-one": []})
        self.assertEqual(pipeline.api_runtime.status()["binding_count"], 4)
        alerts = AlertSink()
        pipeline.api_runtime.alerts = alerts
        pipeline.on_protect_event(
            {
                "id": "event-one",
                "ts": int(time.time() * 1000),
                "camera_id": "camera-one",
                "type": "motion",
                "smart_types": [],
                "score": 0,
            }
        )
        self.assertEqual([call["detector"] for call in alerts.calls], ["protect-event-type-inventory"])
        pipeline.on_protect_poll(
            {
                "ok": False,
                "poll_latency_ms": 15000,
                "raw_event_count": 0,
                "emitted_event_count": 0,
                "duplicate_event_count": 0,
                "page_saturated": False,
            }
        )
        pipeline.on_protect_inventory(
            [
                {
                    "id": "camera-one",
                    "name": "Camera One",
                    "model": "G5 Bullet",
                    "state": "CONNECTED",
                    "rtsp_enabled": True,
                    "stream": {"width": 1920, "height": 1080, "fps": 30},
                }
            ],
            api_latency_ms=42.5,
        )
        routed = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertFalse(routed["protect-event-poll-health"]["poll_ok"])
        self.assertEqual(routed["protect-camera-api-latency"]["api_latency_ms"], 42.5)
        pipeline.on_stream_status(
            {"id": "camera-one", "name": "Camera One"},
            {"event": "reconnecting"},
            1_800_000_001.0,
        )
        self.assertEqual(alerts.calls[-1]["detector"], "rtsp-reconnect-rate")
        self.assertEqual(alerts.calls[-1]["meta"]["reconnect_count"], 1)
        protect_client = Mock()
        access_control = Mock()
        pipeline.attach_api_adapters(protect_client=protect_client, access_control=access_control)
        self.assertIs(pipeline.api_runtime.protect_client, protect_client)
        self.assertIs(pipeline.api_runtime.access_control, access_control)

    def test_pipeline_uses_canonical_evidence_volume(self):
        cv2_stub = types.ModuleType("cv2")
        setattr(cv2_stub, "CAP_FFMPEG", 0)
        sys.modules.setdefault("cv2", cv2_stub)
        from main import Pipeline

        registry, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        classes = {
            "manual-review-snapshot": registry["manual-review-snapshot"]["cls"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "application-data"
            evidence_root = root / "separate-evidence-volume"
            with patch.dict(
                os.environ,
                {
                    "VISION_DATA": str(data_root),
                    "VISION_EVIDENCE": str(evidence_root),
                    "VISION_EVIDENCE_DIR": "",
                },
                clear=False,
            ):
                pipeline = Pipeline(
                    {
                        "site": {"name": "Test Site", "timezone": "UTC"},
                        "cameras": [
                            {
                                "id": "camera-one",
                                "name": "Camera One",
                                "detectors": ["manual-review-snapshot"],
                            }
                        ],
                        "detector_settings": {},
                        "alerts": {},
                    },
                    classes,
                )

            api_runtime = pipeline.api_runtime
            assert api_runtime is not None
            self.assertEqual(api_runtime.evidence_root, evidence_root.resolve())
            self.assertNotEqual(api_runtime.evidence_root, (data_root / "evidence").resolve())

    def test_frame_runtime_validates_but_does_not_instantiate_api_bindings(self):
        registry, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        api_class = registry["protect-event-type-inventory"]["cls"]
        self.assertTrue(api_class.api_function)
        configured = build_camera_detectors(
            [
                {
                    "id": "camera-one",
                    "name": "Camera One",
                    "detectors": ["protect-event-type-inventory"],
                }
            ],
            {},
            {"protect-event-type-inventory": api_class},
        )
        self.assertEqual(configured, {"camera-one": []})

    def _runtime(
        self,
        configured_ids,
        *,
        protect_client=None,
        access_control=None,
        camera_settings=None,
        clock=None,
    ):
        registry, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        camera = {
            "id": "camera-one",
            "name": "Camera One",
            "detectors": configured_ids,
        }
        camera.update(camera_settings or {})
        config = {
            "site": {"name": "Test Site", "timezone": "UTC"},
            "cameras": [camera],
            "detector_settings": {},
        }
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        alerts = AlertSink()
        runtime = APIFunctionRuntime(
            config,
            registry,
            alerts=alerts,
            site="Test Site",
            evidence_root=Path(temporary.name),
            protect_client=protect_client,
            access_control=access_control,
            clock=clock or (lambda: 1_800_000_001.0),
        )
        return runtime, alerts

    def test_events_are_dispatched_without_rtsp_frame_arrival(self):
        runtime, alerts = self._runtime(
            ["protect-event-type-inventory", "access-unclassified-event-review"]
        )
        self.assertEqual(runtime.status()["binding_count"], 2)
        runtime.on_protect_event(
            {
                "id": "motion-one",
                "ts": 1_800_000_000_000,
                "camera_id": "camera-one",
                "type": "motion",
                "smart_types": [],
                "score": 0,
            }
        )
        runtime.on_access_event(
            {
                "id": "access-one",
                "ts": 1_800_000_000_000,
                "door_id": "door-one",
                "door_name": "Front Door",
                "type": "firmware_new_event",
                "result": "",
                "credential_granted": False,
            }
        )
        self.assertEqual(
            {call["detector"] for call in alerts.calls},
            {"protect-event-type-inventory", "access-unclassified-event-review"},
        )

    def test_protect_event_profiles_compute_real_bounded_semantics_and_persist_safe_records(self):
        function_ids = [
            "protect-event-camera-reference-audit",
            "protect-event-duplicate-id-audit",
            "protect-event-duration-outlier",
            "protect-event-end-field-audit",
            "protect-event-ingest-lag",
            "protect-event-jsonl-archive",
            "protect-event-order-anomaly",
            "protect-event-schema-drift",
            "protect-event-score-distribution",
            "protect-event-start-field-audit",
            "protect-event-type-inventory",
            "protect-event-watermark-checkpoint",
        ]
        runtime, alerts = self._runtime(
            function_ids,
            camera_settings={
                "protect-event-duration-outlier": {"alert_threshold": 60},
                "protect-event-ingest-lag": {"alert_threshold": 0.5},
                "protect-event-schema-drift": {"event_threshold": 2},
            },
        )
        normal = {
            "id": "event-one",
            "ts": 1_800_000_000_000,
            "camera_id": "camera-one",
            "type": "motion",
            "smart_types": ["person"],
            "score": 80.0,
            "duration_seconds": 120.0,
            "start_present": True,
            "end_present": True,
            "camera_reference_present": True,
            "source_fields": ["camera", "end", "id", "score", "start", "type"],
        }
        runtime.on_protect_event(normal)
        first = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertNotIn("protect-event-duplicate-id-audit", first)
        self.assertNotIn("protect-event-order-anomaly", first)
        self.assertNotIn("protect-event-start-field-audit", first)
        self.assertNotIn("protect-event-end-field-audit", first)
        self.assertNotIn("protect-event-camera-reference-audit", first)
        self.assertEqual(first["protect-event-duration-outlier"]["duration_seconds"], 120.0)
        self.assertEqual(first["protect-event-ingest-lag"]["ingest_lag_seconds"], 1.0)
        self.assertEqual(first["protect-event-type-inventory"]["event_type_counts"], {"motion": 1})
        self.assertEqual(first["protect-event-score-distribution"]["score_mean"], 80.0)

        alerts.calls.clear()
        runtime.on_protect_event(normal)
        self.assertEqual(
            [call["detector"] for call in alerts.calls if call["detector"] == "protect-event-duplicate-id-audit"],
            ["protect-event-duplicate-id-audit"],
        )

        alerts.calls.clear()
        malformed = dict(
            normal,
            id="event-two",
            ts=1_799_999_999_000,
            duration_seconds=0.0,
            start_present=False,
            end_present=False,
            camera_reference_present=False,
            source_fields=["id", "timestamp", "type"],
        )
        runtime.on_protect_event(malformed)
        malformed_two = dict(malformed, id="event-three", ts=1_799_999_999_500)
        runtime.on_protect_event(malformed_two)
        changed = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertTrue(changed["protect-event-order-anomaly"]["out_of_order"])
        self.assertFalse(changed["protect-event-start-field-audit"]["start_present"])
        self.assertFalse(changed["protect-event-end-field-audit"]["end_present"])
        self.assertFalse(changed["protect-event-camera-reference-audit"]["camera_reference_present"])
        self.assertTrue(changed["protect-event-schema-drift"]["schema_drift"])

        archive = runtime.evidence_root / "protect-events.jsonl"
        checkpoint = runtime.evidence_root / "protect-event-watermark.json"
        self.assertTrue(archive.is_file())
        self.assertTrue(checkpoint.is_file())
        archive_text = archive.read_text(encoding="utf-8")
        self.assertNotIn("password", archive_text.casefold())
        self.assertLessEqual(len(archive_text.splitlines()), 4096)
        watermark = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(watermark["watermark_ms"], 1_800_000_000_000)

    def test_protect_poll_health_page_saturation_and_silence_use_lifecycle_ticks(self):
        runtime, alerts = self._runtime(
            [
                "protect-event-page-saturation",
                "protect-event-poll-health",
                "protect-event-silence-watch",
            ],
            camera_settings={
                "protect-event-silence-watch": {"threshold_window_seconds": 300},
            },
        )
        runtime.on_protect_poll(
            {
                "ok": False,
                "poll_latency_ms": 15000.0,
                "raw_event_count": 0,
                "emitted_event_count": 0,
                "duplicate_event_count": 0,
                "page_saturated": False,
            }
        )
        runtime.on_protect_poll(
            {
                "ok": True,
                "poll_latency_ms": 25.0,
                "raw_event_count": 100,
                "emitted_event_count": 100,
                "duplicate_event_count": 0,
                "page_saturated": True,
            }
        )
        runtime.tick(1_800_000_001.0)
        runtime.tick(1_800_000_302.0)
        by_detector = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertFalse(by_detector["protect-event-poll-health"]["poll_ok"])
        self.assertEqual(by_detector["protect-event-poll-health"]["poll_latency_ms"], 15000.0)
        self.assertTrue(by_detector["protect-event-page-saturation"]["page_saturated"])
        self.assertEqual(by_detector["protect-event-page-saturation"]["raw_event_count"], 100)
        self.assertGreaterEqual(by_detector["protect-event-silence-watch"]["silence_seconds"], 300.0)

    def test_access_profiles_compute_aggregates_quality_inventory_and_sequence_without_control(self):
        now = [1_800_000_001.0]
        function_ids = [
            "access-close-confirmation-gap",
            "access-credential-method-mix",
            "access-door-activity-heatmap",
            "access-door-alarm-duration-ledger",
            "access-door-name-drift",
            "access-doorbell-next-event-timing",
            "access-event-type-census",
            "access-first-last-door-event",
            "access-grant-denial-ratio",
            "access-log-delivery-lag",
            "access-observed-door-roster",
            "access-out-of-order-event-review",
            "access-unclassified-event-review",
            "access-unreported-method-review",
        ]
        control = Mock()
        runtime, alerts = self._runtime(
            function_ids,
            access_control=control,
            clock=lambda: now[0],
            camera_settings={
                function_id: {"digest_seconds": 60, "event_threshold": 2}
                for function_id in function_ids
            },
        )

        def send(identifier, event_type, *, result="", method="", door_name="Front Door", offset=1):
            event = {
                "id": identifier,
                "ts": int((now[0] - offset) * 1000),
                "door_id": "door-one",
                "door_name": door_name,
                "type": event_type,
                "result": result,
                "method": method,
                "credential_granted": event_type == "access_granted",
            }
            runtime.on_access_event(event)
            now[0] += 61

        send("grant", "access_granted", result="granted", method="card")
        send("denied", "access_denied", result="denied", method="pin")
        send("doorbell", "doorbell", method="unknown")
        send("forced", "forced_open", method="unknown")
        send("closed", "door_closed", method="unknown", offset=6)
        send("rename", "access_denied", result="denied", method="pin", door_name="Main Door")
        send("unknown", "firmware_new_event", method="unknown", door_name="Main Door", offset=10)
        # Arrival order is older than the immediately preceding normalized event.
        send("older", "access_denied", result="denied", method="pin", door_name="Main Door", offset=120)

        by_detector = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(by_detector["access-event-type-census"]["event_kind_counts"]["denied"], 3)
        self.assertEqual(by_detector["access-grant-denial-ratio"]["grant_count"], 1)
        self.assertEqual(by_detector["access-grant-denial-ratio"]["denied_count"], 3)
        self.assertEqual(by_detector["access-credential-method-mix"]["method_counts"]["nfc"], 1)
        self.assertEqual(by_detector["access-credential-method-mix"]["method_counts"]["pin"], 3)
        self.assertLess(
            by_detector["access-first-last-door-event"]["first_event_seconds"],
            by_detector["access-first-last-door-event"]["last_event_seconds"],
        )
        self.assertIn("door-one", by_detector["access-observed-door-roster"]["observed_doors"])
        self.assertEqual(by_detector["access-door-name-drift"]["previous_door_name"], "Front Door")
        self.assertEqual(by_detector["access-door-name-drift"]["door_name"], "Main Door")
        self.assertGreater(by_detector["access-log-delivery-lag"]["delivery_lag_seconds"], 5.0)
        self.assertTrue(by_detector["access-out-of-order-event-review"]["out_of_order"])
        self.assertEqual(by_detector["access-unclassified-event-review"]["kind"], "other")
        self.assertEqual(by_detector["access-unreported-method-review"]["method"], "unknown")
        self.assertGreater(by_detector["access-door-alarm-duration-ledger"]["alarm_duration_seconds"], 0)
        self.assertGreater(by_detector["access-close-confirmation-gap"]["close_confirmation_gap_seconds"], 0)
        self.assertGreater(by_detector["access-doorbell-next-event-timing"]["doorbell_next_event_seconds"], 0)
        self.assertTrue(by_detector["access-door-activity-heatmap"]["door_hour_counts"])
        control.unlock.assert_not_called()

    def test_inventory_and_stream_profiles_use_their_declared_sources(self):
        runtime, alerts = self._runtime(
            ["protect-camera-offline-watch", "rtsp-black-frame-rate"]
        )
        runtime.on_inventory(
            [
                {
                    "id": "camera-one",
                    "name": "Camera One",
                    "model": "Camera",
                    "state": "DISCONNECTED",
                    "rtsp_enabled": True,
                    "stream": {"width": 1920, "height": 1080, "fps": 30},
                }
            ],
            1_800_000_001.0,
        )
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")
        black = np.zeros((120, 160, 3), dtype=np.uint8)
        runtime.on_frame({"id": "camera-one", "name": "Camera One"}, black, 1_800_000_001.0)
        self.assertEqual(
            {call["detector"] for call in alerts.calls},
            {"protect-camera-offline-watch", "rtsp-black-frame-rate"},
        )

    def test_stream_profiles_use_temporal_metrics_for_freeze_gap_and_drift(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")
        function_ids = [
            "rtsp-aspect-ratio-drift",
            "rtsp-black-frame-rate",
            "rtsp-effective-fps",
            "rtsp-frame-gap-watch",
            "rtsp-frame-hash-duplication",
            "rtsp-frame-size-consistency",
            "rtsp-freeze-watch",
            "rtsp-low-contrast-watch",
            "rtsp-luminance-flicker",
            "rtsp-resolution-drift",
            "rtsp-rolling-quality-digest",
            "rtsp-startup-latency",
        ]
        runtime, alerts = self._runtime(
            function_ids,
            camera_settings={
                function_id: {
                    "sample_interval_seconds": 1,
                    "event_threshold": 2,
                    "alert_threshold": 2,
                }
                for function_id in function_ids
            },
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        gradient = np.tile(np.arange(160, dtype=np.uint8), (120, 1))
        color = np.stack([gradient, gradient, gradient], axis=2)
        runtime.on_frame(camera, color, 1_800_000_001.0)
        first_detectors = {call["detector"] for call in alerts.calls}
        self.assertNotIn("rtsp-freeze-watch", first_detectors)
        self.assertIn("rtsp-startup-latency", first_detectors)

        alerts.calls.clear()
        runtime.on_frame(camera, color.copy(), 1_800_000_002.0)
        second = {call["detector"]: call["meta"]["metrics"] for call in alerts.calls}
        self.assertEqual(second["rtsp-frame-hash-duplication"]["duplicate_frame"], 1.0)
        self.assertAlmostEqual(second["rtsp-effective-fps"]["effective_fps"], 1.0)
        self.assertNotIn("rtsp-freeze-watch", second)

        alerts.calls.clear()
        runtime.on_frame(camera, color.copy(), 1_800_000_003.0)
        third = {call["detector"]: call["meta"]["metrics"] for call in alerts.calls}
        self.assertGreaterEqual(third["rtsp-freeze-watch"]["duplicate_streak"], 2.0)

        alerts.calls.clear()
        black = np.zeros((90, 160, 3), dtype=np.uint8)
        runtime.on_frame(camera, black, 1_800_000_007.0)
        changed = {call["detector"]: call["meta"]["metrics"] for call in alerts.calls}
        self.assertGreaterEqual(changed["rtsp-frame-gap-watch"]["frame_gap_seconds"], 4.0)
        self.assertEqual(changed["rtsp-resolution-drift"]["resolution_changed"], 1.0)
        self.assertEqual(changed["rtsp-frame-size-consistency"]["frame_size_changed"], 1.0)
        self.assertEqual(changed["rtsp-aspect-ratio-drift"]["aspect_ratio_changed"], 1.0)
        self.assertGreaterEqual(changed["rtsp-black-frame-rate"]["black_ratio"], 0.95)
        self.assertGreater(changed["rtsp-luminance-flicker"]["luminance_delta"], 2.0)
        self.assertIn("quality_score", changed["rtsp-rolling-quality-digest"])

    def test_stream_lifecycle_profiles_use_sanitized_worker_status(self):
        function_ids = [
            "rtsp-connectivity-probe",
            "rtsp-decode-error-rate",
            "rtsp-reconnect-rate",
            "rtsp-startup-latency",
        ]
        runtime, alerts = self._runtime(function_ids)
        camera = {"id": "camera-one", "name": "Camera One"}
        runtime.on_stream_status(
            camera,
            {"event": "connect_failed", "attempt": 1, "backoff_seconds": 1, "url": "rtsps://secret"},
            1_800_000_001.0,
        )
        runtime.on_stream_status(
            camera,
            {"event": "connected", "attempt": 2, "latency_seconds": 1.25, "password": "secret"},
            1_800_000_002.0,
        )
        runtime.on_stream_status(camera, {"event": "decode_error"}, 1_800_000_003.0)
        runtime.on_stream_status(camera, {"event": "reconnecting"}, 1_800_000_004.0)

        by_detector = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(by_detector["rtsp-startup-latency"]["latency_seconds"], 1.25)
        self.assertEqual(by_detector["rtsp-decode-error-rate"]["decode_error_count"], 1)
        self.assertGreater(by_detector["rtsp-decode-error-rate"]["decode_error_rate"], 0)
        self.assertEqual(by_detector["rtsp-reconnect-rate"]["reconnect_count"], 1)
        self.assertEqual(by_detector["rtsp-connectivity-probe"]["event"], "connected")
        serialized = json.dumps(alerts.calls, sort_keys=True)
        self.assertNotIn("rtsps://", serialized)
        self.assertNotIn("password", serialized)

    def test_inventory_profiles_publish_specific_bounded_fleet_and_change_metrics(self):
        function_ids = [
            "protect-camera-api-latency",
            "protect-camera-count-trend",
            "protect-camera-discovery-delta",
            "protect-camera-fleet-inventory",
            "protect-camera-model-mix",
            "protect-camera-state-flap-log",
            "protect-rtsp-availability-delta",
            "protect-stream-fps-register",
            "protect-stream-profile-drift",
            "protect-stream-resolution-register",
        ]
        runtime, alerts = self._runtime(function_ids)
        first = [
            {
                "id": "camera-one",
                "name": "Camera One",
                "model": "G5 Bullet",
                "state": "CONNECTED",
                "rtsp_enabled": True,
                "stream": {"width": 1920, "height": 1080, "fps": 30},
            },
            {
                "id": "camera-two",
                "name": "Camera Two",
                "model": "G5 Dome",
                "state": "DISCONNECTED",
                "rtsp_enabled": False,
                "stream": {"width": 0, "height": 0, "fps": 0},
            },
        ]
        runtime.on_inventory(first, 1_800_000_001.0, api_latency_ms=125.25)
        first_meta = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(first_meta["protect-camera-fleet-inventory"]["camera_count"], 2)
        self.assertEqual(first_meta["protect-camera-fleet-inventory"]["offline_count"], 1)
        self.assertEqual(
            first_meta["protect-camera-model-mix"]["model_counts"],
            {"G5 Bullet": 1, "G5 Dome": 1},
        )
        self.assertEqual(first_meta["protect-camera-api-latency"]["api_latency_ms"], 125.25)

        alerts.calls.clear()
        second = [
            {
                "id": "camera-one",
                "name": "Camera One",
                "model": "G5 Bullet",
                "state": "DISCONNECTED",
                "rtsp_enabled": False,
                "stream": {"width": 1280, "height": 720, "fps": 15},
            },
            {
                "id": "camera-three",
                "name": "Camera Three",
                "model": "AI Pro",
                "state": "CONNECTED",
                "rtsp_enabled": True,
                "stream": {"width": 3840, "height": 2160, "fps": 30},
            },
        ]
        runtime.on_inventory(second, 1_800_000_061.0, api_latency_ms=80.5)
        changed = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(changed["protect-camera-count-trend"]["camera_count_delta"], 0)
        self.assertEqual(
            changed["protect-camera-discovery-delta"]["added_camera_ids"],
            ["camera-three"],
        )
        self.assertEqual(
            changed["protect-camera-discovery-delta"]["removed_camera_ids"],
            ["camera-two"],
        )
        self.assertEqual(changed["protect-camera-state-flap-log"]["previous_state"], "CONNECTED")
        self.assertEqual(changed["protect-camera-state-flap-log"]["state"], "DISCONNECTED")
        self.assertEqual(changed["protect-rtsp-availability-delta"]["previous_rtsp_enabled"], True)
        self.assertEqual(changed["protect-stream-profile-drift"]["previous_stream"]["fps"], 30)
        self.assertEqual(changed["protect-stream-profile-drift"]["stream"]["fps"], 15)
        self.assertNotIn("rtsps://", json.dumps(changed).casefold())

    def test_clip_export_is_bounded_confined_and_requires_configured_function(self):
        client = Mock()

        def download(camera_id, start_ms, end_ms, destination, **_kwargs):
            self.assertEqual(camera_id, "camera-one")
            Path(destination).write_bytes(b"clip-bytes")
            return destination

        client.download_clip.side_effect = download
        runtime, _alerts = self._runtime(["manual-bounded-clip-export"], protect_client=client)
        result = runtime.export_clip(
            "manual-bounded-clip-export",
            "camera-one",
            1_800_000_000_000,
            1_800_000_010_000,
        )
        self.assertEqual(result["bytes"], 10)
        self.assertEqual(len(result["sha256"]), 64)
        self.assertFalse(Path(result["path"]).is_absolute())
        with self.assertRaises(APIRuntimeError) as unconfigured:
            runtime.export_clip(
                "smart-event-clip-export",
                "camera-one",
                1_800_000_000_000,
                1_800_000_010_000,
            )
        self.assertEqual(unconfigured.exception.code, "function_not_configured")
        with self.assertRaises(APIRuntimeError) as duration:
            runtime.export_clip(
                "manual-bounded-clip-export",
                "camera-one",
                1_800_000_000_000,
                1_800_000_700_000,
            )
        self.assertEqual(duration.exception.code, "clip_window_invalid")

    def test_requested_api_function_selects_the_matching_camera_binding(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")

        registry, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        function_ids = [
            "manual-review-snapshot",
            "manual-bounded-clip-export",
            "access-audited-unlock-request",
        ]
        cameras = []
        for suffix in ("one", "two"):
            cameras.append(
                {
                    "id": f"camera-{suffix}",
                    "name": f"Camera {suffix.title()}",
                    "detectors": list(function_ids),
                    "manual-review-snapshot": {"sample_interval_seconds": 1},
                    "access-audited-unlock-request": {
                        "door_allowlist": [f"door-{suffix}"],
                        "reason_required": True,
                    },
                }
            )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        protect_client = Mock()

        def download(camera_id, _start_ms, _end_ms, destination, **_kwargs):
            self.assertEqual(camera_id, "camera-two")
            Path(destination).write_bytes(b"second-camera-clip")
            return destination

        protect_client.download_clip.side_effect = download
        access_control = Mock()
        access_control.unlock.return_value = True
        runtime = APIFunctionRuntime(
            {
                "site": {"name": "Test Site", "timezone": "UTC"},
                "cameras": cameras,
                "detector_settings": {},
            },
            registry,
            alerts=AlertSink(),
            site="Test Site",
            evidence_root=temporary.name,
            protect_client=protect_client,
            access_control=access_control,
            clock=lambda: 1_800_000_001.0,
        )

        runtime.on_frame(
            cameras[1],
            np.full((48, 64, 3), 100, dtype=np.uint8),
            1_800_000_001.0,
        )
        snapshot = runtime.request_snapshot(
            "manual-review-snapshot",
            "camera-two",
            request_id="snapshot-camera-two",
        )
        self.assertIn("camera-two", snapshot["snapshot_path"])
        clip = runtime.export_clip(
            "manual-bounded-clip-export",
            "camera-two",
            1_800_000_000_000,
            1_800_000_010_000,
        )
        self.assertEqual(clip["bytes"], len(b"second-camera-clip"))
        unlock = runtime.request_unlock(
            "access-audited-unlock-request",
            "door-two",
            reason="Approved second-camera door",
            request_id="unlock-camera-two",
        )
        self.assertTrue(unlock["accepted"])
        access_control.unlock.assert_called_once_with("door-two")

    def test_clip_export_prunes_reuses_tracks_quota_and_emits_governance(self):
        client = Mock()

        def download(_camera_id, _start_ms, _end_ms, destination, **kwargs):
            self.assertEqual(kwargs["max_bytes"], 700)
            self.assertEqual(kwargs["timeout_seconds"], 5.0)
            Path(destination).write_bytes(b"x" * 600)
            return destination

        client.download_clip.side_effect = download
        governance_ids = [
            "clip-export-checksum-manifest",
            "clip-export-duration-cap",
            "clip-export-index",
            "clip-export-integrity-probe",
            "clip-export-latency-metrics",
            "clip-export-overlap-deduper",
            "clip-export-retention-pruner",
            "clip-export-storage-quota",
        ]
        runtime, alerts = self._runtime(
            ["manual-bounded-clip-export", *governance_ids],
            protect_client=client,
            clock=time.time,
            camera_settings={
                "manual-bounded-clip-export": {
                    "max_clip_bytes": 700,
                    "storage_quota_bytes": 1000,
                    "retention_days": 1,
                    "timeout_seconds": 5,
                }
            },
        )
        clips = runtime.evidence_root / "clips"
        clips.mkdir(parents=True, exist_ok=True)
        old = clips / "old.mp4"
        old.write_bytes(b"old")
        old_time = time.time() - 2 * 86400
        os.utime(old, (old_time, old_time))

        first = runtime.export_clip(
            "manual-bounded-clip-export",
            "camera-one",
            1_800_000_000_000,
            1_800_000_010_000,
        )
        self.assertFalse(old.exists())
        self.assertEqual(first["bytes"], 600)
        self.assertFalse(first["reused"])
        second = runtime.export_clip(
            "manual-bounded-clip-export",
            "camera-one",
            1_800_000_000_000,
            1_800_000_010_000,
        )
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertTrue(second["reused"])
        self.assertEqual(client.download_clip.call_count, 1)

        by_detector = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(by_detector["clip-export-retention-pruner"]["pruned_count"], 1)
        self.assertTrue(by_detector["clip-export-overlap-deduper"]["reused"])
        self.assertEqual(by_detector["clip-export-storage-quota"]["storage_bytes"], 600)
        self.assertEqual(by_detector["clip-export-checksum-manifest"]["sha256"], first["sha256"])
        self.assertGreaterEqual(by_detector["clip-export-latency-metrics"]["latency_ms"], 0)
        ledger = runtime.evidence_root / "clip-export-index.jsonl"
        self.assertTrue(ledger.is_file())
        self.assertEqual(os.stat(ledger).st_mode & 0o777, 0o600)

        with self.assertRaises(APIRuntimeError) as quota:
            runtime.export_clip(
                "manual-bounded-clip-export",
                "camera-one",
                1_800_000_020_000,
                1_800_000_030_000,
            )
        self.assertEqual(quota.exception.code, "clip_storage_quota")
        self.assertEqual(sum(path.stat().st_size for path in clips.glob("*.mp4")), 600)

        with self.assertRaises(APIRuntimeError) as profile:
            runtime.export_clip(
                "clip-export-integrity-probe",
                "camera-one",
                1_800_000_000_000,
                1_800_000_010_000,
            )
        self.assertEqual(profile.exception.code, "function_not_exportable")

    def test_event_clip_profiles_export_only_matching_bounded_windows(self):
        client = Mock()

        def download(_camera_id, _start_ms, _end_ms, destination, **_kwargs):
            Path(destination).write_bytes(b"event-clip")
            return destination

        client.download_clip.side_effect = download
        runtime, alerts = self._runtime(
            [
                "event-pre-post-roll-clip-export",
                "motion-event-clip-export",
                "smart-event-clip-export",
            ],
            protect_client=client,
            camera_settings={
                "event-pre-post-roll-clip-export": {"pre_seconds": 2, "post_seconds": 3},
                "motion-event-clip-export": {"pre_seconds": 1, "post_seconds": 1},
                "smart-event-clip-export": {"pre_seconds": 4, "post_seconds": 5},
            },
        )
        runtime.on_protect_event(
            {
                "id": "motion-one",
                "ts": 1_800_000_000_000,
                "camera_id": "camera-one",
                "type": "motion",
                "smart_types": [],
                "score": 0,
            }
        )
        motion_calls = {
            call["detector"]: call["meta"]
            for call in alerts.calls
            if call["detector"].endswith("clip-export")
        }
        self.assertEqual(
            set(motion_calls),
            {"event-pre-post-roll-clip-export", "motion-event-clip-export"},
        )
        self.assertEqual(motion_calls["motion-event-clip-export"]["start_ms"], 1_799_999_999_000)
        self.assertEqual(motion_calls["motion-event-clip-export"]["end_ms"], 1_800_000_001_000)

        alerts.calls.clear()
        runtime.on_protect_event(
            {
                "id": "smart-one",
                "ts": 1_800_000_010_000,
                "camera_id": "camera-one",
                "type": "smartDetectZone",
                "smart_types": ["person"],
                "score": 80,
            }
        )
        smart_calls = {
            call["detector"]: call["meta"]
            for call in alerts.calls
            if call["detector"].endswith("clip-export")
        }
        self.assertEqual(
            set(smart_calls),
            {"event-pre-post-roll-clip-export", "smart-event-clip-export"},
        )
        self.assertEqual(smart_calls["smart-event-clip-export"]["start_ms"], 1_800_000_006_000)
        self.assertEqual(smart_calls["smart-event-clip-export"]["end_ms"], 1_800_000_015_000)
        self.assertEqual(client.download_clip.call_count, 4)

    def test_scheduled_snapshots_capture_once_per_local_day_and_manual_never_auto_captures(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")
        runtime, alerts = self._runtime(
            [
                "opening-time-snapshot",
                "closing-time-snapshot",
                "scheduled-reference-snapshot",
                "manual-review-snapshot",
            ],
            camera_settings={
                "opening-time-snapshot": {
                    "local_time": "08:00",
                    "schedule_window_seconds": 90,
                    "sample_interval_seconds": 1,
                },
                "closing-time-snapshot": {
                    "local_time": "17:00",
                    "schedule_window_seconds": 90,
                    "sample_interval_seconds": 1,
                },
                "scheduled-reference-snapshot": {
                    "local_time": "12:00",
                    "schedule_window_seconds": 90,
                    "sample_interval_seconds": 1,
                },
                "manual-review-snapshot": {"sample_interval_seconds": 1},
            },
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        noon = datetime(2027, 1, 2, 12, 0, 10, tzinfo=timezone.utc).timestamp()
        runtime.on_frame(camera, frame, noon)
        runtime.on_frame(camera, frame, noon + 30)
        files = list((runtime.evidence_root / "snapshots").glob("*.jpg"))
        self.assertEqual(len(files), 1)
        self.assertIn("scheduled-reference-snapshot", files[0].name)
        self.assertNotIn("manual-review-snapshot", files[0].name)
        self.assertEqual(
            [call["detector"] for call in alerts.calls],
            ["scheduled-reference-snapshot"],
        )
        self.assertEqual(alerts.calls[0]["meta"]["trigger"], "scheduled")
        self.assertEqual(len(alerts.calls[0]["meta"]["snapshot_sha256"]), 64)

        runtime.on_frame(camera, frame, noon + 86400)
        files = list((runtime.evidence_root / "snapshots").glob("*.jpg"))
        self.assertEqual(len(files), 2)

    def test_manual_snapshot_uses_latest_frame_is_idempotent_and_audits_privacy_suppression(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")
        frame = np.full((48, 64, 3), 100, dtype=np.uint8)
        camera = {"id": "camera-one", "name": "Camera One"}
        runtime, alerts = self._runtime(
            ["manual-review-snapshot", "snapshot-write-health"],
            camera_settings={"manual-review-snapshot": {"sample_interval_seconds": 1}},
        )
        runtime.on_frame(camera, frame, 1_800_000_001.0)
        self.assertFalse((runtime.evidence_root / "snapshots").exists())
        result = runtime.request_snapshot(
            "manual-review-snapshot",
            "camera-one",
            request_id="snapshot-request-one",
        )
        self.assertFalse(result["suppressed"])
        self.assertEqual(len(result["snapshot_sha256"]), 64)
        self.assertTrue((runtime.evidence_root / result["snapshot_path"]).is_file())
        self.assertEqual(alerts.calls[-1]["detector"], "snapshot-write-health")
        self.assertTrue(alerts.calls[-1]["meta"]["write_ok"])
        with self.assertRaises(APIRuntimeError) as duplicate:
            runtime.request_snapshot(
                "manual-review-snapshot",
                "camera-one",
                request_id="snapshot-request-one",
            )
        self.assertEqual(duplicate.exception.code, "duplicate_snapshot_request")

        private_runtime, private_alerts = self._runtime(
            ["manual-review-snapshot", "snapshot-privacy-suppression-audit"],
            camera_settings={
                "privacy_mode": "skeleton",
                "manual-review-snapshot": {"sample_interval_seconds": 1},
            },
        )
        private_runtime.on_frame(camera, frame, 1_800_000_001.0)
        suppressed = private_runtime.request_snapshot(
            "manual-review-snapshot",
            "camera-one",
            request_id="snapshot-private-one",
        )
        self.assertTrue(suppressed["suppressed"])
        self.assertFalse((private_runtime.evidence_root / "snapshots").exists())
        self.assertEqual(private_alerts.calls[-1]["detector"], "snapshot-privacy-suppression-audit")
        self.assertEqual(private_alerts.calls[-1]["meta"]["suppressed_count"], 1)

    def test_snapshot_writes_enforce_age_count_and_storage_bounds(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")

        now = 1_800_000_001.0
        with patch.dict(
            os.environ,
            {
                "VISION_SNAPSHOT_RETENTION_DAYS": "1",
                "VISION_SNAPSHOT_MAX_FILES": "2",
                "VISION_SNAPSHOT_STORAGE_QUOTA_BYTES": "1500",
            },
            clear=False,
        ):
            runtime, _alerts = self._runtime(
                ["manual-review-snapshot"],
                camera_settings={"manual-review-snapshot": {"sample_interval_seconds": 1}},
                clock=lambda: now,
            )

        directory = runtime.evidence_root / "snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        old = directory / "old.jpg"
        recent_one = directory / "recent-one.jpg"
        recent_two = directory / "recent-two.jpg"
        old.write_bytes(b"o" * 500)
        recent_one.write_bytes(b"1" * 800)
        recent_two.write_bytes(b"2" * 800)
        os.utime(old, (now - 2 * 86400, now - 2 * 86400))
        os.utime(recent_one, (now - 20, now - 20))
        os.utime(recent_two, (now - 10, now - 10))

        camera = {"id": "camera-one", "name": "Camera One"}
        runtime.on_frame(camera, np.full((48, 64, 3), 100, dtype=np.uint8), now)
        result = runtime.request_snapshot(
            "manual-review-snapshot",
            "camera-one",
            request_id="bounded-snapshot-one",
        )

        files = list(directory.glob("*.jpg"))
        self.assertFalse(old.exists())
        self.assertLessEqual(len(files), 2)
        self.assertLessEqual(sum(path.stat().st_size for path in files), 1500)
        self.assertGreaterEqual(result["pruned_count"], 2)
        self.assertLessEqual(result["snapshot_storage_bytes"], 1500)

    def test_last_good_snapshot_is_written_only_after_stream_health_failure(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy unavailable")
        runtime, alerts = self._runtime(
            ["snapshot-last-good-frame", "snapshot-write-health"],
            camera_settings={"snapshot-last-good-frame": {"sample_interval_seconds": 1}},
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        runtime.on_frame(camera, np.full((48, 64, 3), 90, dtype=np.uint8), 1_800_000_001.0)
        self.assertFalse((runtime.evidence_root / "snapshots").exists())
        runtime.on_stream_status(camera, {"event": "decode_error"}, 1_800_000_002.0)
        files = list((runtime.evidence_root / "snapshots").glob("*.jpg"))
        self.assertEqual(len(files), 1)
        self.assertIn("snapshot-last-good-frame", files[0].name)
        by_detector = {call["detector"]: call["meta"] for call in alerts.calls}
        self.assertEqual(by_detector["snapshot-last-good-frame"]["trigger"], "stream-health-failure")
        self.assertEqual(by_detector["snapshot-last-good-frame"]["stream_event"], "decode_error")
        self.assertTrue(by_detector["snapshot-write-health"]["write_ok"])

    def test_zone_crop_snapshot_stores_only_configured_bounding_box(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("numpy or Pillow unavailable")
        runtime, alerts = self._runtime(
            ["snapshot-zone-crop"],
            camera_settings={
                "snapshot-zone-crop": {
                    "sample_interval_seconds": 1,
                    "crop_box": [0.25, 0.25, 0.75, 0.75],
                }
            },
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[25:75, 50:150] = 200
        runtime.on_frame(camera, frame, 1_800_000_001.0)
        files = list((runtime.evidence_root / "snapshots").glob("*.jpg"))
        self.assertEqual(len(files), 1)
        with Image.open(files[0]) as image:
            self.assertEqual(image.size, (100, 50))
        self.assertEqual(alerts.calls[-1]["detector"], "snapshot-zone-crop")
        self.assertEqual(alerts.calls[-1]["meta"]["crop_pixels"], [50, 25, 150, 75])
        self.assertEqual(alerts.calls[-1]["meta"]["trigger"], "zone-crop")

    def test_audited_unlock_requires_allowlist_reason_and_unique_request(self):
        control = Mock()
        control.unlock.return_value = True
        runtime, _alerts = self._runtime(
            ["access-audited-unlock-request"],
            access_control=control,
            camera_settings={
                "access-audited-unlock-request": {
                    "door_allowlist": ["door-one"],
                    "reason_required": True,
                }
            },
        )
        result = runtime.request_unlock(
            "access-audited-unlock-request",
            "door-one",
            reason="Approved vendor arrival",
            request_id="request-one",
        )
        self.assertTrue(result["accepted"])
        control.unlock.assert_called_once_with("door-one")
        audit = (runtime.evidence_root / "access-control-audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"request_id":"request-one"', audit)
        self.assertNotIn("Approved vendor arrival", audit)
        with self.assertRaises(APIRuntimeError) as replay:
            runtime.request_unlock(
                "access-audited-unlock-request",
                "door-one",
                reason="Approved vendor arrival",
                request_id="request-one",
            )
        self.assertEqual(replay.exception.code, "duplicate_request")
        with self.assertRaises(APIRuntimeError) as denied:
            runtime.request_unlock(
                "access-audited-unlock-request",
                "door-two",
                reason="Approved vendor arrival",
                request_id="request-two",
            )
        self.assertEqual(denied.exception.code, "door_not_allowed")


if __name__ == "__main__":
    unittest.main()
