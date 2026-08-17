from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from unifi_protect import ProtectClient


class _Response:
    def __init__(self, chunks, *, error=None):
        self.chunks = chunks
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def iter_content(self, _size):
        yield from self.chunks


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ProtectClipDownloadTests(unittest.TestCase):
    def _client(self, response):
        client = object.__new__(ProtectClient)
        client.base = "https://controller.example/proxy/protect/api"
        client.session = _Session(response)
        return client

    def test_download_clip_streams_to_atomic_partial_and_enforces_limit(self):
        client = self._client(_Response([b"123456", b"abcdef"]))
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "clip.mp4"
            result = client.download_clip(
                "camera-one",
                1_800_000_000_000,
                1_800_000_010_000,
                str(destination),
                max_bytes=10,
                timeout_seconds=5,
            )
            self.assertIsNone(result)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(".mp4.partial").exists())

    def test_download_clip_atomically_installs_owner_only_file(self):
        client = self._client(_Response([b"123", b"456"]))
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "clip.mp4"
            result = client.download_clip(
                "camera-one",
                1_800_000_000_000,
                1_800_000_010_000,
                str(destination),
                max_bytes=10,
                timeout_seconds=5,
            )
            self.assertEqual(result, str(destination))
            self.assertEqual(destination.read_bytes(), b"123456")
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            self.assertEqual(client.session.calls[0][1]["timeout"], (5.0, 5.0))

    def test_download_clip_logs_only_error_class(self):
        client = self._client(_Response([], error=RuntimeError("rtsps://secret password")))
        with tempfile.TemporaryDirectory() as temporary, self.assertLogs("unifi_protect", logging.WARNING) as captured:
            result = client.download_clip(
                "camera-one",
                1_800_000_000_000,
                1_800_000_010_000,
                str(Path(temporary) / "clip.mp4"),
                max_bytes=10,
                timeout_seconds=5,
            )
        self.assertIsNone(result)
        logs = "\n".join(captured.output)
        self.assertIn("RuntimeError", logs)
        self.assertNotIn("rtsps://", logs)
        self.assertNotIn("password", logs)


if __name__ == "__main__":
    unittest.main()
