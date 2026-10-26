from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

cv2 = types.ModuleType("cv2")
cv2.CAP_FFMPEG = 0
sys.modules["cv2"] = cv2

import streams
from streams import StreamManager, StreamWorker


class _Capture:
    def __init__(self):
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        return False, None

    def release(self):
        self.released = True


class StreamLifecycleTests(unittest.TestCase):
    def test_worker_emits_sanitized_connect_decode_and_reconnect_status(self):
        capture = _Capture()
        cv2.VideoCapture = lambda _url, _backend: capture
        statuses = []
        holder = {}

        def on_status(camera, status, ts):
            statuses.append((camera, status, ts))
            if status["event"] == "reconnecting":
                holder["worker"].stop()

        worker = StreamWorker(
            {"id": "camera-one", "name": "Camera One", "rtsp": "rtsps://user:password@controller/live"},
            1.0,
            lambda *_args: None,
            on_status=on_status,
        )
        holder["worker"] = worker
        # Discovery may have imported streams with an earlier OpenCV stub.
        # Bind this test's complete fake explicitly and restore it afterward.
        with patch.object(streams, "cv2", cv2):
            worker.run()

        self.assertEqual([item[1]["event"] for item in statuses], ["connected", "decode_error", "reconnecting"])
        self.assertGreaterEqual(statuses[0][1]["latency_seconds"], 0.0)
        self.assertTrue(capture.released)
        serialized = repr(statuses)
        self.assertNotIn("rtsps://", serialized)
        self.assertNotIn("password", serialized)

    def test_manager_passes_one_status_callback_to_each_worker(self):
        callback = object()
        manager = StreamManager(
            [{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}],
            1.0,
            lambda *_args: None,
            on_status=callback,
        )
        self.assertEqual(len(manager.workers), 2)
        self.assertTrue(all(worker.on_status is callback for worker in manager.workers))


if __name__ == "__main__":
    unittest.main()
