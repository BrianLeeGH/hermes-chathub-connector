"""Assert both device-plane handlers build their URLs under ``be-api/``.

The ChatHub ingress only routes the ``be-api/`` prefix to the API host
(``/api/*`` falls through to the web front-end), so a regression here means a
silent 302/404 in production. The test is hermetic: ``tools.py`` imports
``requests`` lazily inside the HTTP helpers, so a stand-in module is injected
into ``sys.modules`` (no network library required to run these tests).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
HERMES_SOURCE = REPO_ROOT.parent / "hermes-agent-upstream"
sys.path.insert(0, str(REPO_ROOT))
if str(HERMES_SOURCE) not in sys.path:
    sys.path.insert(0, str(HERMES_SOURCE))

from hermes_chathub_connector import tools  # noqa: E402

GATEWAY = "http://gateway.test"


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeRequests:
    """Stand-in for the ``requests`` module; records every request made."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse([])

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _FakeResponse({"success": True})


class EndpointPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = dict(os.environ)
        self.addCleanup(self._restore_env)
        os.environ["CHATHUB_TURN_SECRET"] = "test-turn-secret"
        os.environ["CHATHUB_GATEWAY_URL"] = GATEWAY
        self.requests = _FakeRequests()
        patcher = mock.patch.dict(sys.modules, {"requests": self.requests})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_list_uses_be_api_prefix(self) -> None:
        tools._handle_list_chathub_tools({})

        method, url, _ = self.requests.calls[-1]
        self.assertEqual((method, url), ("GET", f"{GATEWAY}/be-api/connectors/tools"))

    def test_exec_uses_be_api_prefix(self) -> None:
        tools._handle_exec_chathub_tools({"name": "ms365/list_events", "args": "{}"})

        method, url, kwargs = self.requests.calls[-1]
        self.assertEqual(
            (method, url), ("POST", f"{GATEWAY}/be-api/connectors/tools:call")
        )
        self.assertEqual(kwargs["json"]["name"], "ms365/list_events")


if __name__ == "__main__":
    unittest.main()
