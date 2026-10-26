from __future__ import annotations

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

cv2_stub = sys.modules.setdefault("cv2", types.ModuleType("cv2"))
cv2_stub.imwrite = lambda *_args, **_kwargs: False

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import api
import subscriptions
from alerts import AlertEngine
from detectors import video_search
from marketplace.runtime import build_camera_detectors


class RuntimeConfigurationPreflightTests(unittest.TestCase):
    def test_duplicate_camera_ids_fail_closed(self):
        cameras = [
            {"id": "lobby", "name": "Lobby One", "detectors": []},
            {"id": "lobby", "name": "Lobby Two", "detectors": []},
        ]
        with self.assertRaisesRegex(ValueError, "duplicate camera id.*lobby"):
            build_camera_detectors(cameras, {}, {})

    def test_video_search_camera_name_cannot_escape_vision_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "vision-data"
            embed_dir = data_dir / "embeddings"
            with patch.object(video_search, "DATA_DIR", data_dir), patch.object(
                video_search, "EMBED_DIR", embed_dir
            ), patch.object(video_search, "_embed_image", return_value=video_search.np.array([1.0])):
                indexer = video_search.VideoSearchIndexer(
                    {"embed_every_seconds": 0, "retention_days": 0, "max_embeddings": 10}
                )
                indexer.process(
                    {"id": "camera-1", "name": "../../escaped"},
                    object(),
                    1_800_000_000.0,
                    SimpleNamespace(),
                )

            files = list(Path(temporary).rglob("*.npy"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].parent.resolve(), embed_dir.resolve())
            self.assertTrue(files[0].resolve().is_relative_to(data_dir.resolve()))


class AlertReliabilityPreflightTests(unittest.TestCase):
    def test_identical_failed_occurrences_are_durably_counted_and_bounded(self):
        environment = {
            "BASE44_ALERT_URL": "https://alerts.invalid/ingest",
            "BASE44_INTERNAL_TOKEN": "unit-test-token",
            "EXTRA_WEBHOOK_URL": "",
        }
        config = {
            "alerts": {
                "dedup_seconds": 0,
                "outbox_max_events": 2,
                "outbox_max_occurrences_per_event": 3,
            }
        }
        failure = SimpleNamespace(status_code=500)
        alert = {
            "site": "Site",
            "camera": {"id": "camera-1", "name": "Camera One"},
            "detector": "tailgating",
            "title": "Possible tailgating",
            "detail": "review",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, environment, clear=False
        ), patch("alerts.requests.post", return_value=failure):
            engine = AlertEngine(config, temporary)
            for _ in range(4):
                self.assertFalse(engine.fire(**alert))
            self.assertEqual(engine.pending_count(), 1)
            self.assertEqual(engine.pending_occurrence_count(), 3)
            self.assertEqual(engine.outbox_dropped, 1)

            restarted = AlertEngine(config, temporary)
            self.assertEqual(restarted.pending_count(), 1)
            self.assertEqual(restarted.pending_occurrence_count(), 3)
            self.assertEqual(restarted.outbox_dropped, 1)

    def test_snapshot_larger_than_payload_cap_is_not_embedded(self):
        calls = []

        def write_large_snapshot(path, _frame):
            Path(path).write_bytes(b"x" * 512)
            return True

        def fail_delivery(_url, *, json, timeout):
            calls.append((json, timeout))
            return SimpleNamespace(status_code=500)

        environment = {
            "BASE44_ALERT_URL": "https://alerts.invalid/ingest",
            "BASE44_INTERNAL_TOKEN": "unit-test-token",
            "EXTRA_WEBHOOK_URL": "",
        }
        config = {"alerts": {"dedup_seconds": 0, "snapshot_payload_max_bytes": 128}}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, environment, clear=False
        ), patch("alerts.cv2.imwrite", side_effect=write_large_snapshot), patch(
            "alerts.requests.post", side_effect=fail_delivery
        ):
            engine = AlertEngine(config, temporary)
            self.assertFalse(
                engine.fire(
                    site="Site",
                    camera={"id": "camera-1", "name": "Camera One"},
                    detector="tailgating",
                    title="Possible tailgating",
                    detail="review",
                    frame=object(),
                )
            )

            self.assertEqual(len(calls), 1)
            self.assertNotIn("snapshot", calls[0][0])
            self.assertIsNotNone(calls[0][0]["snapshotPath"])
            outbox = json.loads((Path(temporary) / "alert-outbox.json").read_text())
            self.assertNotIn("snapshot", outbox["pending"][0]["payload"])

    def test_outbox_is_bounded_by_serialized_bytes_as_well_as_event_count(self):
        environment = {
            "BASE44_ALERT_URL": "https://alerts.invalid/ingest",
            "BASE44_INTERNAL_TOKEN": "unit-test-token",
            "EXTRA_WEBHOOK_URL": "",
        }
        config = {
            "alerts": {
                "dedup_seconds": 0,
                "outbox_max_events": 100,
                "outbox_max_bytes": 900,
            }
        }
        failure = SimpleNamespace(status_code=500)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, environment, clear=False
        ), patch("alerts.requests.post", return_value=failure):
            engine = AlertEngine(config, temporary)
            outbox_path = Path(temporary) / "alert-outbox.json"
            for index in range(10):
                self.assertFalse(
                    engine.fire(
                        site="Site",
                        camera={"id": "camera-1", "name": "Camera One"},
                        detector="tailgating",
                        title=f"Possible tailgating {index}",
                        detail="x" * 100,
                    )
                )
                self.assertLessEqual(outbox_path.stat().st_size, 900)

            self.assertLess(engine.pending_count(), 10)
            self.assertGreater(engine.outbox_dropped, 0)


class AlertReadinessPreflightTests(unittest.TestCase):
    def test_alert_delivery_state_degrades_readiness_but_not_liveness(self):
        delivery = {
            "ok": False,
            "configured": ["base44"],
            "degraded_destinations": [],
            "pending_events": 1,
            "pending_occurrences": 2,
            "dropped": 1,
        }
        alerts = SimpleNamespace(
            stats=lambda: {},
            destination_stats=lambda: {},
            delivery_readiness=lambda: dict(delivery),
        )
        pipeline = SimpleNamespace(
            site="Test Site",
            cameras=[{"id": "camera-1"}],
            alerts=alerts,
            camera_detectors={},
            detector_failures={},
        )
        worker = SimpleNamespace(connected=True, last_frame_at=1_800_000_000.0)
        streams = SimpleNamespace(workers=[worker], status=lambda: [])
        fake_store = SimpleNamespace(init_db=lambda: None)
        fake_app = types.ModuleType("subscriptions.app")
        fake_app.router = APIRouter()
        with patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules,
            {"subscriptions.store": fake_store, "subscriptions.app": fake_app},
        ), patch("api.time.time", return_value=1_800_000_000.0):
            from fastapi.testclient import TestClient

            client = TestClient(api.create_app(pipeline, streams))
            health = client.get("/health")
            not_ready = client.get("/ready")
            delivery.update(
                ok=True,
                pending_events=0,
                pending_occurrences=0,
                dropped=0,
            )
            ready = client.get("/ready")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(not_ready.status_code, 503)
        self.assertEqual(not_ready.json()["alert_delivery"], {
            "ok": False,
            "configured": ["base44"],
            "degraded_destinations": [],
            "pending_events": 1,
            "pending_occurrences": 2,
            "dropped": 1,
        })
        self.assertEqual(ready.status_code, 200)


class PublicSignupPreflightTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _pipeline():
        return SimpleNamespace(
            site="Test Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}, destination_stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
        )

    async def _post_signup_chunks(self, chunks: list[bytes], headers: list[tuple[bytes, bytes]]):
        router = APIRouter(prefix="/api/subscriptions")

        @router.post("")
        async def signup(request: Request):
            await request.body()
            return {"ok": True}

        fake_store = SimpleNamespace(init_db=lambda: None)
        fake_app = types.ModuleType("subscriptions.app")
        fake_app.router = router
        streams = SimpleNamespace(workers=[], status=lambda: [])
        with patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules,
            {"subscriptions.store": fake_store, "subscriptions.app": fake_app},
        ), patch.dict(os.environ, {"VISION_SIGNUP_MAX_BODY_BYTES": "1024"}, clear=False):
            app = api.create_app(self._pipeline(), streams)

        messages = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        sent = []

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/subscriptions",
            "raw_path": b"/api/subscriptions",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("203.0.113.8", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        status = next(message["status"] for message in sent if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
        return status, body

    def test_signup_rate_limiter_evicts_sources_to_a_fixed_bound(self):
        limiter = api.SignupRateLimiter(limit=2, window_seconds=60, max_sources=3)
        for index in range(4):
            self.assertTrue(limiter.allow(f"source-{index}", now=0))
        self.assertEqual(limiter.tracked_source_count(), 3)
        self.assertTrue(limiter.allow("source-0", now=1), "oldest source should have been evicted")
        self.assertEqual(limiter.tracked_source_count(), 3)

    async def test_signup_body_cap_counts_streamed_bytes_without_trusting_content_length(self):
        chunks = [b"x" * 700, b"y" * 700]
        for headers in (
            [(b"content-type", b"application/json")],
            [(b"content-type", b"application/json"), (b"content-length", b"1")],
        ):
            with self.subTest(headers=headers):
                status, body = await self._post_signup_chunks(chunks, headers)
                self.assertEqual(status, 413)
                self.assertIn(b"signup request is too large", body)


if __name__ == "__main__":
    unittest.main()
