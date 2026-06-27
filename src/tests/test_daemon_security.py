from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
import warnings
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-test-appdata-")
os.environ["APPDATA"] = _APPDATA_DIR.name

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from daemon.locking import get_or_create_token
from daemon.server import create_app


class DaemonSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.token = get_or_create_token()

    def _client(self, host: str = "127.0.0.1") -> TestClient:
        return TestClient(create_app(), client=(host, 50000))

    def test_health_is_public_but_context_requires_token(self) -> None:
        client = self._client()

        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertIs(health.json().get("ok"), True)

        missing = client.post("/context", json={})
        self.assertEqual(missing.status_code, 403)

        bad = client.post("/context", json={}, headers={"X-Ra3Copilot-Token": "bad-token"})
        self.assertEqual(bad.status_code, 403)

        ok = client.post("/context", json={}, headers={"X-Ra3Copilot-Token": self.token})
        self.assertEqual(ok.status_code, 200)
        self.assertIs(ok.json().get("ok"), True)

    def test_non_local_client_is_rejected_even_with_token(self) -> None:
        client = self._client("192.0.2.10")
        response = client.post("/context", json={}, headers={"X-Ra3Copilot-Token": self.token})
        self.assertEqual(response.status_code, 403)

    def test_browser_preflight_allows_token_header(self) -> None:
        client = self._client()
        response = client.options(
            "/context",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-ra3copilot-token,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertIn(
            "x-ra3copilot-token",
            response.headers.get("access-control-allow-headers", "").lower(),
        )


class EntryPointTests(unittest.TestCase):
    def test_frozen_dispatch_entrypoint_is_importable(self) -> None:
        entry_path = Path(__file__).resolve().parents[1] / "__main__.py"
        spec = importlib.util.spec_from_file_location("ra3copilot_entry", entry_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))


if __name__ == "__main__":
    unittest.main()
