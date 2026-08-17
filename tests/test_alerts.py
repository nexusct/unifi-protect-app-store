from __future__ import annotations

import base64
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _write_test_jpeg(path, _frame):
    Path(path).write_bytes(b"\xff\xd8unit-test-jpeg\xff\xd9")
    return True


cv2_stub = sys.modules.setdefault("cv2", types.ModuleType("cv2"))
setattr(cv2_stub, "imwrite", _write_test_jpeg)

from alerts import AlertEngine


class _Response:
    def __init__(self, status_code=200):
        self.status_code = status_code


class AlertDeliveryTests(unittest.TestCase):
    def test_delivery_readiness_tracks_unresolved_delivery_state(self):
        environment = {
            "BASE44_ALERT_URL": "https://base44.invalid/alerts",
            "BASE44_INTERNAL_TOKEN": "unit-test-only",
            "EXTRA_WEBHOOK_URL": "",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, environment, clear=False
        ), patch("alerts.requests.post", return_value=_Response(500)):
            engine = AlertEngine({"alerts": {"dedup_seconds": 0}}, temporary)
            initial = engine.delivery_readiness()
            engine.fire(
                site="Test Site",
                camera={"id": "cam-1", "name": "Camera 1"},
                detector="wrong-way",
                title="Test alert",
                detail="Test detail",
            )
            degraded = engine.delivery_readiness()
            with patch("alerts.requests.post", return_value=_Response(200)):
                engine.retry_pending()
            recovered = engine.delivery_readiness()

        self.assertEqual(initial, {
            "ok": True,
            "configured": ["base44"],
            "degraded_destinations": [],
            "pending_events": 0,
            "pending_occurrences": 0,
            "dropped": 0,
        })
        self.assertEqual(degraded, {
            "ok": False,
            "configured": ["base44"],
            "degraded_destinations": ["base44"],
            "pending_events": 1,
            "pending_occurrences": 1,
            "dropped": 0,
        })
        self.assertEqual(recovered, initial)

    def test_configured_destinations_receive_jpeg_bytes_and_webhook_does_not_receive_base44_token(self):
        calls = []

        def fake_post(url, *, json, timeout):
            calls.append((url, json, timeout))
            return _Response()

        environment = {
            "BASE44_ALERT_URL": "https://base44.invalid/alerts",
            "BASE44_INTERNAL_TOKEN": "unit-test-only",
            "EXTRA_WEBHOOK_URL": "https://webhook.invalid/alerts",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment, clear=False), patch(
            "alerts.cv2.imwrite", side_effect=_write_test_jpeg
        ), patch(
            "alerts.requests.post", side_effect=fake_post
        ):
            engine = AlertEngine({"alerts": {"dedup_seconds": 0}}, temporary)
            sent = engine.fire(
                site="Test Site",
                camera={"id": "cam-1", "name": "Camera 1"},
                detector="wrong-way",
                title="Test alert",
                detail="Test detail",
                frame=object(),
            )

        self.assertTrue(sent)
        self.assertEqual(
            [url for url, _payload, _timeout in calls],
            [environment["BASE44_ALERT_URL"], environment["EXTRA_WEBHOOK_URL"]],
        )
        base44_payload = calls[0][1]
        webhook_payload = calls[1][1]
        self.assertEqual(base44_payload["internalToken"], environment["BASE44_INTERNAL_TOKEN"])
        self.assertNotIn("internalToken", webhook_payload)
        for payload in (base44_payload, webhook_payload):
            snapshot = payload["snapshot"]
            self.assertEqual(snapshot["contentType"], "image/jpeg")
            self.assertTrue(snapshot["filename"].endswith(".jpg"))
            self.assertTrue(base64.b64decode(snapshot["base64"]).startswith(b"\xff\xd8"))

    def test_skeleton_privacy_mode_suppresses_local_and_outbound_snapshot(self):
        calls = []

        def fake_post(url, *, json, timeout):
            calls.append((url, json, timeout))
            return _Response()

        environment = {
            "BASE44_ALERT_URL": "",
            "BASE44_INTERNAL_TOKEN": "",
            "EXTRA_WEBHOOK_URL": "https://webhook.invalid/alerts",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment, clear=False), patch(
            "alerts.requests.post", side_effect=fake_post
        ):
            engine = AlertEngine({"alerts": {"dedup_seconds": 0}}, temporary)
            sent = engine.fire(
                site="Test Site",
                camera={"id": "cam-private", "name": "Private Camera", "privacy_mode": "skeleton"},
                detector="possible-fall",
                title="Test alert",
                detail="Test detail",
                frame=object(),
            )
            self.assertEqual(list((Path(temporary) / "snapshots").iterdir()), [])

        self.assertTrue(sent)
        self.assertEqual(len(calls), 1)
        payload = calls[0][1]
        self.assertIsNone(payload["snapshotPath"])
        self.assertNotIn("snapshot", payload)

    def test_failed_destination_is_not_counted_or_deduplicated_before_retry(self):
        responses = iter((_Response(500), _Response(200)))
        calls = []

        def fake_post(url, *, json, timeout):
            calls.append((url, json, timeout))
            return next(responses)

        environment = {
            "BASE44_ALERT_URL": "https://base44.invalid/alerts",
            "BASE44_INTERNAL_TOKEN": "unit-test-only",
            "EXTRA_WEBHOOK_URL": "",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment, clear=False), patch(
            "alerts.requests.post", side_effect=fake_post
        ):
            engine = AlertEngine({"alerts": {"dedup_seconds": 120}}, temporary)
            alert = {
                "site": "Test Site",
                "camera": {"id": "cam-1", "name": "Camera 1"},
                "detector": "wrong-way",
                "title": "Test alert",
                "detail": "Test detail",
            }
            self.assertFalse(engine.fire(**alert))
            self.assertTrue(engine.fire(**alert))
            self.assertFalse(engine.fire(**alert))
            stats = engine.stats()

        self.assertEqual(len(calls), 2)
        self.assertEqual(stats, {"alerts_sent": 1, "alerts_failed": 1, "alerts_suppressed": 1})

    def test_partial_delivery_retries_only_the_failed_destination(self):
        calls = []
        base44_attempts = 0

        def fake_post(url, *, json, timeout):
            nonlocal base44_attempts
            calls.append(url)
            if url == "https://base44.invalid/alerts":
                base44_attempts += 1
                return _Response(500 if base44_attempts == 1 else 200)
            return _Response(200)

        environment = {
            "BASE44_ALERT_URL": "https://base44.invalid/alerts",
            "BASE44_INTERNAL_TOKEN": "unit-test-only",
            "EXTRA_WEBHOOK_URL": "https://webhook.invalid/alerts",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment, clear=False), patch(
            "alerts.requests.post", side_effect=fake_post
        ):
            engine = AlertEngine({"alerts": {"dedup_seconds": 120}}, temporary)
            alert = {
                "site": "Test Site",
                "camera": {"id": "cam-1", "name": "Camera 1"},
                "detector": "wrong-way",
                "title": "Test alert",
                "detail": "Test detail",
            }
            self.assertFalse(engine.fire(**alert))
            self.assertTrue(engine.fire(**alert))
            self.assertFalse(engine.fire(**alert))
            stats = engine.stats()

        self.assertEqual(
            calls,
            [
                environment["BASE44_ALERT_URL"],
                environment["EXTRA_WEBHOOK_URL"],
                environment["BASE44_ALERT_URL"],
            ],
        )
        self.assertEqual(stats, {"alerts_sent": 1, "alerts_failed": 1, "alerts_suppressed": 1})


if __name__ == "__main__":
    unittest.main()
