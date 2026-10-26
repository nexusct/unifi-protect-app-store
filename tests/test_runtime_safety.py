from __future__ import annotations

import calendar
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Keep this contract test independent of the host OpenCV/NumPy binary pairing.
sys.modules.setdefault("cv2", types.ModuleType("cv2"))

from fastapi.testclient import TestClient
from fastapi import APIRouter

from api import create_app
from detectors import tailgating
from marketplace.functions import site_theft_watch
from site_time import site_time
import subscriptions


class _AccessRecorder:
    def __init__(self):
        self.enabled = True
        self.result = True
        self.unlocked = []

    def unlock(self, door_id):
        self.unlocked.append(door_id)
        return self.result


class _AlertRecorder:
    def __init__(self):
        self.events = []

    def fire(self, **event):
        self.events.append(event)
        return True

    def stats(self):
        return {}


class RuntimeSafetyTests(unittest.TestCase):
    def test_unlock_requires_configured_bearer_token_and_valid_door_id(self):
        access = _AccessRecorder()
        pipeline = SimpleNamespace(
            site="Test Site",
            access=access,
            alerts=_AlertRecorder(),
            camera_detectors={},
        )
        streams = SimpleNamespace(workers=[], status=lambda: {})

        fake_store = SimpleNamespace(init_db=lambda: None)
        fake_app = types.ModuleType("subscriptions.app")
        setattr(fake_app, "router", APIRouter())
        with patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules, {"subscriptions.store": fake_store, "subscriptions.app": fake_app}
        ), patch.dict(os.environ, {"VISION_CONTROL_TOKEN": "unit-test-control-token"}, clear=False):
            client = TestClient(create_app(pipeline, streams))
            self.assertEqual(client.post("/unlock/door-1").status_code, 401)
            self.assertEqual(
                client.post("/unlock/door-1", headers={"Authorization": "Bearer wrong-token"}).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/unlock/bad$id",
                    headers={"Authorization": "Bearer unit-test-control-token"},
                ).status_code,
                400,
            )
            response = client.post(
                "/unlock/door-1",
                headers={"Authorization": "Bearer unit-test-control-token"},
            )
            access.result = False
            rejected = client.post(
                "/unlock/door-1",
                headers={"Authorization": "Bearer unit-test-control-token"},
            )
            access.enabled = False
            unavailable = client.post(
                "/unlock/door-1",
                headers={"Authorization": "Bearer unit-test-control-token"},
            )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(rejected.status_code, 410)
        self.assertEqual(unavailable.status_code, 410)
        self.assertEqual(access.unlocked, [])

    def test_readiness_fails_until_every_configured_worker_is_connected(self):
        pipeline = SimpleNamespace(
            site="Test Site",
            alerts=_AlertRecorder(),
            camera_detectors={},
            cameras=[{"id": "camera-1"}],
        )
        worker = SimpleNamespace(connected=False, last_frame_at=None)
        streams = SimpleNamespace(workers=[worker], status=lambda: {})
        fake_store = SimpleNamespace(init_db=lambda: None)
        fake_app = types.ModuleType("subscriptions.app")
        setattr(fake_app, "router", APIRouter())
        with patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules, {"subscriptions.store": fake_store, "subscriptions.app": fake_app}
        ):
            client = TestClient(create_app(pipeline, streams))
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 503)
            worker.connected = True
            worker.last_frame_at = __import__("time").time()
            ready = client.get("/ready")

        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["streams_up"], 1)

    def test_unlock_is_disabled_for_placeholder_control_token(self):
        access = _AccessRecorder()
        pipeline = SimpleNamespace(
            site="Test Site",
            access=access,
            alerts=_AlertRecorder(),
            camera_detectors={},
        )
        streams = SimpleNamespace(workers=[], status=lambda: {})

        fake_store = SimpleNamespace(init_db=lambda: None)
        fake_app = types.ModuleType("subscriptions.app")
        setattr(fake_app, "router", APIRouter())
        with patch.object(subscriptions, "store", fake_store, create=True), patch.dict(
            sys.modules, {"subscriptions.store": fake_store, "subscriptions.app": fake_app}
        ), patch.dict(os.environ, {"VISION_CONTROL_TOKEN": "change-me"}, clear=False):
            client = TestClient(create_app(pipeline, streams))
            response = client.post(
                "/unlock/door-1",
                headers={"Authorization": "Bearer change-me"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(access.unlocked, [])

    def test_weekends_active_applies_configured_crew_hours_on_weekends(self):
        saturday_noon = calendar.timegm((2026, 8, 15, 12, 0, 0, 0, 0, 0))
        camera = {
            "id": "cam-yard",
            "name": "Yard Camera",
            "zones": {"yard": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        }
        boxes = [(0, 0.5, 0.5, 0.9)]

        active_alerts = _AlertRecorder()
        active_ctx = SimpleNamespace(site="Test Site", alerts=active_alerts, timezone="America/Chicago")
        active = site_theft_watch.Function(
            {"crew_hours": [6, 17], "weekends_active": True}
        )
        with patch.object(site_theft_watch, "boxes_of", return_value=boxes), patch.object(
            site_theft_watch, "in_zone", return_value=True
        ):
            active.process(camera, object(), saturday_noon, active_ctx)
        self.assertEqual(active_alerts.events, [])

        inactive_alerts = _AlertRecorder()
        inactive_ctx = SimpleNamespace(site="Test Site", alerts=inactive_alerts, timezone="America/Chicago")
        inactive = site_theft_watch.Function(
            {"crew_hours": [6, 17], "weekends_active": False}
        )
        with patch.object(site_theft_watch, "boxes_of", return_value=boxes), patch.object(
            site_theft_watch, "in_zone", return_value=True
        ):
            inactive.process(camera, object(), saturday_noon, inactive_ctx)
        self.assertEqual(len(inactive_alerts.events), 1)

    def test_site_clock_uses_iana_timezone_and_daylight_saving(self):
        context = SimpleNamespace(timezone="America/Chicago")
        winter = calendar.timegm((2026, 1, 15, 18, 0, 0, 0, 0, 0))
        summer = calendar.timegm((2026, 7, 15, 17, 0, 0, 0, 0, 0))
        self.assertEqual(site_time(winter, context).tm_hour, 12)
        self.assertEqual(site_time(summer, context).tm_hour, 12)

    def test_tailgating_allowance_scales_with_badge_count(self):
        detector = tailgating.TailgatingDetector(
            {"door_id": "door-main", "window_seconds": 6, "max_persons_per_badge": 1}
        )
        now = 1_800_000_000.0
        alerts = _AlertRecorder()
        context = SimpleNamespace(
            site="Test Site",
            alerts=alerts,
            access_events=[
                {"id": "first", "door_id": "door-main", "ts": int((now - 2) * 1000), "credential_granted": True},
                {"id": "second", "door_id": "door-main", "ts": int((now - 1) * 1000), "credential_granted": True},
            ],
        )
        camera = {"id": "cam-entry", "name": "Main Entry"}

        with patch.object(tailgating, "boxes_of", return_value=[object()] * 2, create=True):
            detector.process(camera, object(), now, context)
        self.assertEqual(alerts.events, [])

        with patch.object(tailgating, "boxes_of", return_value=[object()] * 3, create=True):
            detector.process(camera, object(), now + 0.5, context)
        self.assertEqual(len(alerts.events), 1)
        self.assertEqual(alerts.events[0]["meta"]["allowance"], 2)

    def test_runtime_safety_copy_avoids_conclusive_or_unimplemented_phrases(self):
        paths = [path for path in SRC.rglob("*.py") if path.name != "unifi_protect.py"]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
        for phrase in (
            "bed-exit prediction",
            "prevention window",
            "intervene before feet on floor",
            "before sensors trip",
            "compliance warning",
            "fall event",
            "clip retention",
            "clip preserved",
            "email + webhook alerts",
            "same person has cased",
            "sales floor over licensed cap",
            "non-clinical person in clinical zone",
            "person without clinical attire",
            "forklift speeding",
            "compliance artifact",
            "clip evidence",
            "with a clip",
        ):
            self.assertNotIn(phrase, text)

        marketplace_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SRC / "marketplace" / "functions").glob("*.py")
        )
        self.assertNotIn("gmtime(", marketplace_source)


if __name__ == "__main__":
    unittest.main()
