from __future__ import annotations

import calendar
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from marketplace.functions import route_verification, service_response_time


class _Alerts:
    def __init__(self):
        self.events = []

    def fire(self, **event):
        self.events.append(event)
        return True


class RouteVerificationTests(unittest.TestCase):
    def setUp(self):
        self.alerts = _Alerts()
        self.context = SimpleNamespace(site="Site", timezone="UTC", alerts=self.alerts)
        self.camera = {
            "id": "route-camera",
            "name": "Route Camera",
            "zones": {
                "route_zones": {
                    "north": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]],
                    "south": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]],
                }
            },
        }

    def test_summary_waits_until_window_closes(self):
        function = route_verification.Function({"window": [2, 7]})
        before_close = calendar.timegm((2026, 8, 15, 6, 59, 0, 0, 0, 0))
        at_close = calendar.timegm((2026, 8, 15, 7, 0, 0, 0, 0, 0))

        with patch.object(
            route_verification,
            "boxes_of",
            side_effect=[[(2, 0.25, 0.5)], []],
        ):
            function.process(self.camera, object(), before_close, self.context)
            self.assertEqual(self.alerts.events, [])
            function.process(self.camera, object(), at_close, self.context)

        self.assertEqual(len(self.alerts.events), 1)
        self.assertEqual(self.alerts.events[0]["meta"]["missing"], ["south"])

    def test_summary_reports_every_zone_missing_when_window_had_no_hits(self):
        function = route_verification.Function({"window": [2, 7]})
        before_close = calendar.timegm((2026, 8, 15, 6, 59, 0, 0, 0, 0))
        at_close = calendar.timegm((2026, 8, 15, 7, 0, 0, 0, 0, 0))

        with patch.object(route_verification, "boxes_of", return_value=[]):
            function.process(self.camera, object(), before_close, self.context)
            function.process(self.camera, object(), at_close, self.context)
            function.process(self.camera, object(), at_close + 1, self.context)

        self.assertEqual(len(self.alerts.events), 1)
        event = self.alerts.events[0]
        self.assertEqual(event["meta"]["covered"], {})
        self.assertEqual(event["meta"]["missing"], ["north", "south"])


class ServiceResponseTimeTests(unittest.TestCase):
    def test_departed_waiting_person_clears_session_before_later_staff_arrival(self):
        function = service_response_time.Function({"target_seconds": 180})
        alerts = _Alerts()
        context = SimpleNamespace(site="Site", alerts=alerts)
        camera = {
            "id": "service-camera",
            "name": "Service Camera",
            "zones": {"trigger": "trigger-zone", "staff_arrive": "staff-zone"},
        }

        def point_is_in_zone(cx, _cy, zone):
            return (zone == "trigger-zone" and cx < 0.5) or (zone == "staff-zone" and cx > 0.5)

        with patch.object(
            service_response_time,
            "boxes_of",
            side_effect=[[(0, 0.25, 0.5)], [], [(0, 0.75, 0.5)]],
        ), patch.object(service_response_time, "in_zone", side_effect=point_is_in_zone):
            function.process(camera, object(), 100.0, context)
            function.process(camera, object(), 101.0, context)
            function.process(camera, object(), 110.0, context)

        self.assertEqual(alerts.events, [])


class ClaimCalibrationTests(unittest.TestCase):
    def test_owned_function_copy_avoids_unsupported_conclusions(self):
        forbidden_by_file = {
            "abandoned_object.py": ("unattended object",),
            "banquet_setup_verify.py": ("room not set", "configured on schedule"),
            "customer_wait_alert.py": ("unacknowledged",),
            "driver_cab_time.py": ("active loading", "premature", "dock-safety interlock"),
            "fire_exit_blocked.py": ("fire exit blocked",),
            "forecourt_loiter.py": ("forecourt loitering",),
            "funeral_home_flow.py": ("unique visitors", "document service delivery"),
            "hall_pass_monitor.py": ("dean's office", "hall-roaming"),
            "machine_monopoly.py": ("eight machines", "regulars are glaring", "camped"),
            "meeting_room_usage.py": ("booking", "booked solid", "calendar"),
            "pavilion_rental.py": ("without rental", "unrented pavilion", "bill and enforce"),
            "pharmacy_window_queue.py": ("patient waiting", "per-person wait", "each person's"),
            "pool_drowning_watch.py": ("motionless", "distress signature", "possible pool distress"),
            "route_verification.py": ("prove service delivery", "route as serviced", "actually cover"),
            "safety_zone_breach.py": ("safety zone breach", "restricted zone breach", "interlock-by-camera"),
            "service_response_time.py": ("customer-to-staff", "customer event", "customer and staff zone events"),
            "uniform_check.py": ("uniform mismatch", "contractor/visitor", "dress-code gap", "lacks the uniform"),
        }
        functions_dir = SRC / "marketplace" / "functions"
        for filename, phrases in forbidden_by_file.items():
            source = (functions_dir / filename).read_text(encoding="utf-8").casefold()
            for phrase in phrases:
                self.assertNotIn(phrase, source, f"{filename}: {phrase}")


if __name__ == "__main__":
    unittest.main()
