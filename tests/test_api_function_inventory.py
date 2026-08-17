from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace import loader
from marketplace.api_functions import (
    AccessEventRule,
    ProtectEventFeed,
    ProtectEventRule,
    load_api_function_manifests,
)
from marketplace.contract import validate_manifest
from unifi_protect import ProtectEventPoller, normalize_protect_event


BASELINE_PATH = ROOT / "tests" / "fixtures" / "marketplace-baseline-130-ids.json"
API_FUNCTIONS_PATH = SRC / "marketplace" / "api_functions.json"
CATALOG_PATH = ROOT / "storefront" / "catalog.json"


class AlertSink:
    def __init__(self):
        self.calls = []

    def fire(self, **kwargs):
        self.calls.append(kwargs)


class APIFunctionInventoryTests(unittest.TestCase):
    def test_source_archive_preserves_original_130_and_all_121_api_ids(self):
        baseline = set(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))
        manifests = load_api_function_manifests(API_FUNCTIONS_PATH)
        protect = [m for m in manifests if m["api"]["surface"] == "protect"]
        access = [m for m in manifests if m["api"]["surface"] == "access"]
        added_ids = {m["id"] for m in manifests}

        self.assertEqual(len(baseline), 130)
        self.assertEqual(len(protect), 101)
        self.assertEqual(len(access), 20)
        self.assertEqual(len(manifests), 121)
        self.assertEqual(len(added_ids), 121)
        self.assertFalse(baseline.intersection(added_ids))

        archive, errors = loader.load_all(include_archived=True)
        self.assertEqual(errors, {})
        self.assertEqual(len(archive), 271)
        self.assertTrue(baseline.issubset(archive))
        self.assertTrue(added_ids.issubset(archive))

        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(catalog), 100)
        self.assertEqual({row["id"] for row in catalog}, set(loader.load_all()[0]))

    def test_every_api_contract_is_valid_bounded_and_honestly_bound(self):
        manifests = load_api_function_manifests(API_FUNCTIONS_PATH)
        allowed = {
            "protect": {
                "camera_inventory",
                "events",
                "rtsp_stream",
                "clip_export",
            },
            "access": {"developer_logs", "door_unlock"},
        }
        runners = {
            "protect": {"protect_event", "protect_stream", "protect_inventory", "protect_evidence"},
            "access": {"access_event", "access_unlock_request"},
        }
        for manifest in manifests:
            self.assertEqual(validate_manifest(manifest), [], manifest["id"])
            binding = manifest["api"]
            surface = binding["surface"]
            self.assertIn(binding["primitive"], allowed[surface], manifest["id"])
            self.assertIn(binding["runner"], runners[surface], manifest["id"])
            self.assertEqual(binding["control"], binding["runner"] == "access_unlock_request")
            if surface == "protect":
                self.assertFalse(binding["control"])
            self.assertLessEqual(len(binding.get("event_types", [])), 16)
            self.assertLessEqual(len(binding.get("smart_types", [])), 16)

    def test_loader_registers_100_active_and_271_archived_without_collisions(self):
        registry, errors = loader.load_all()
        self.assertEqual(errors, {})
        self.assertEqual(len(registry), 100)
        archive, archive_errors = loader.load_all(include_archived=True)
        self.assertEqual(archive_errors, {})
        self.assertEqual(len(archive), 271)
        for manifest in load_api_function_manifests(API_FUNCTIONS_PATH):
            entry = archive[manifest["id"]]
            self.assertEqual(entry["manifest"], manifest)
            self.assertTrue(issubclass(entry["cls"], (ProtectEventRule, AccessEventRule)))


class ProtectAPIRuntimeTests(unittest.TestCase):
    def test_protect_event_normalization_and_poller_are_bounded_and_deduplicated(self):
        raw = {
            "id": "evt-one",
            "type": "smartDetectZone",
            "start": 1_800_000_000_123,
            "end": 1_800_000_010_123,
            "camera": "camera-one",
            "smartDetectTypes": ["person", "vehicle"],
            "score": 91,
            "firmwareExtra": "not retained",
            "password": "must never survive normalization",
        }
        normalized = normalize_protect_event(raw)
        self.assertEqual(
            normalized,
            {
                "id": "evt-one",
                "ts": 1_800_000_000_123,
                "camera_id": "camera-one",
                "type": "smartDetectZone",
                "smart_types": ["person", "vehicle"],
                "score": 91.0,
                "duration_seconds": 10.0,
                "start_present": True,
                "end_present": True,
                "camera_reference_present": True,
                "source_fields": [
                    "camera",
                    "end",
                    "firmwareExtra",
                    "id",
                    "score",
                    "smartDetectTypes",
                    "start",
                    "type",
                ],
            },
        )
        self.assertNotIn("must never survive normalization", json.dumps(normalized))

        client = Mock()
        client.recent_events.side_effect = [[raw, raw], []]
        received = []
        health = []
        poller = ProtectEventPoller(
            received.append,
            on_poll=health.append,
            client=client,
            start_ms=1_800_000_000_000,
        )
        self.assertEqual(poller.poll_once(), 1)
        self.assertEqual(poller.poll_once(), 0)
        self.assertEqual(len(received), 1)
        self.assertGreater(poller.last_seen_ms, normalized["ts"])
        self.assertEqual(health[0]["raw_event_count"], 2)
        self.assertEqual(health[0]["emitted_event_count"], 1)
        self.assertEqual(health[0]["duplicate_event_count"], 1)
        self.assertTrue(health[0]["ok"])
        self.assertFalse(health[0]["page_saturated"])

    def test_protect_event_rule_filters_surface_camera_type_and_smart_type(self):
        manifest = {
            "id": "protect-test-rule",
            "name": "Protect Test Rule",
            "tagline": "Reports a matching Protect event for testing.",
            "category": "Intelligence",
            "tier": "starter",
            "requires_gpu": False,
            "config_schema": {},
            "api": {
                "surface": "protect",
                "primitive": "events",
                "runner": "protect_event",
                "control": False,
                "event_types": ["smartDetectZone"],
                "smart_types": ["person"],
            },
        }
        rule = ProtectEventRule({}, manifest=manifest)
        alerts = AlertSink()
        context = SimpleNamespace(
            site="Test",
            alerts=alerts,
            protect_events=[
                {
                    "id": "match",
                    "ts": 1_800_000_000_000,
                    "camera_id": "camera-one",
                    "type": "smartDetectZone",
                    "smart_types": ["person"],
                    "score": 88,
                },
                {
                    "id": "other-camera",
                    "ts": 1_800_000_000_000,
                    "camera_id": "camera-two",
                    "type": "smartDetectZone",
                    "smart_types": ["person"],
                    "score": 88,
                },
            ],
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        rule.process(camera, object(), 1_800_000_001.0, context)
        rule.process(camera, object(), 1_800_000_002.0, context)
        self.assertEqual(len(alerts.calls), 1)
        self.assertEqual(alerts.calls[0]["detector"], "protect-test-rule")
        self.assertEqual(alerts.calls[0]["meta"]["protect_event_id"], "match")
        self.assertNotIn("raw", alerts.calls[0]["meta"])

    def test_access_event_rule_never_calls_unlock_and_requires_explicit_kind(self):
        manifest = {
            "id": "access-test-rule",
            "name": "Access Test Rule",
            "tagline": "Reports a matching Access event for testing.",
            "category": "Security & Access",
            "tier": "starter",
            "requires_gpu": False,
            "config_schema": {},
            "api": {
                "surface": "access",
                "primitive": "developer_logs",
                "runner": "access_event",
                "control": False,
                "event_kinds": ["denied"],
            },
        }
        rule = AccessEventRule({}, manifest=manifest)
        alerts = AlertSink()
        context = SimpleNamespace(
            site="Test",
            timezone=ZoneInfo("UTC"),
            alerts=alerts,
            access_events=[
                {
                    "id": "denied-one",
                    "ts": 1_800_000_000_000,
                    "door_id": "door-one",
                    "door_name": "Front Door",
                    "type": "access_denied",
                    "result": "denied",
                    "credential_granted": False,
                },
                {
                    "id": "grant-one",
                    "ts": 1_800_000_000_000,
                    "door_id": "door-one",
                    "type": "access_granted",
                    "credential_granted": True,
                },
            ],
            access=SimpleNamespace(unlock=Mock(side_effect=AssertionError("unlock must not run"))),
        )
        camera = {"id": "camera-one", "name": "Camera One"}
        rule.process(camera, object(), 1_800_000_001.0, context)
        self.assertEqual(len(alerts.calls), 1)
        self.assertEqual(alerts.calls[0]["meta"]["access_event_id"], "denied-one")
        context.access.unlock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
