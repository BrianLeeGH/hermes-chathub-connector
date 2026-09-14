"""Grep-style ``query`` filtering for list_chathub_tools (hermetic).

Same stand-in ``requests`` injection as test_endpoint_paths.py so the handler
runs offline. Behavior under test:

  1. No query -> full catalog passthrough (backward compatible).
  2. Single keyword -> case-insensitive substring match over name+description.
  3. Multiple keywords -> OR semantics (entry matching one keyword is kept).
  4. Keyword matches description as well as name.
  5. Zero matches -> did-you-mean message with closest bare tool names
     (suggestions match the bare part after the {Key}/ prefix, e.g. a typo
     "sendmail" suggests "ms365/send_mail").
  6. List-form query (some models send arrays) is tolerated.
  7. Chinese keywords match substring-wise (no tokenization).
  8. Non-list payload (dict wrapper fallback) is passed through untouched.
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

CATALOG = [
    {"name": "ms365/get_current_user", "description": "Get the current user profile."},
    {"name": "ms365/send_mail", "description": "Send an email via Outlook."},
    {"name": "cal/list_events", "description": "List calendar events. 日程查询"},
    {"name": "kb/search", "description": "Search the knowledge base."},
]


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse(self.payload)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _FakeResponse({"success": True})


class ListFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = dict(os.environ)
        self.addCleanup(self._restore_env)
        os.environ["CHATHUB_TURN_SECRET"] = "test-turn-secret"
        os.environ["CHATHUB_GATEWAY_URL"] = "http://gateway.test"

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)

    def _run(self, payload, args: dict) -> str:
        patcher = mock.patch.dict(sys.modules, {"requests": _FakeRequests(payload)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return tools._handle_list_chathub_tools(args)

    def _names(self, text: str) -> list:
        return [item["name"] for item in json.loads(text)]

    def test_no_query_returns_full_catalog(self) -> None:
        text = self._run(CATALOG, {})
        self.assertEqual(self._names(text), [c["name"] for c in CATALOG])

    def test_single_keyword_is_case_insensitive_substring(self) -> None:
        text = self._run(CATALOG, {"query": "EMAIL"})
        self.assertEqual(self._names(text), ["ms365/send_mail"])

    def test_multiple_keywords_use_or_semantics(self) -> None:
        text = self._run(CATALOG, {"query": "mail calendar"})
        self.assertEqual(
            self._names(text), ["ms365/send_mail", "cal/list_events"]
        )

    def test_keyword_matches_description_too(self) -> None:
        text = self._run(CATALOG, {"query": "profile"})
        self.assertEqual(self._names(text), ["ms365/get_current_user"])

    def test_no_match_returns_did_you_mean_with_full_names(self) -> None:
        text = self._run(CATALOG, {"query": "sendmail"})
        self.assertIn("No ChatHub connector tools matched", text)
        self.assertIn("ms365/send_mail", text)  # typo-tolerant suggestion

    def test_no_match_with_no_close_name_keeps_message_clean(self) -> None:
        text = self._run(CATALOG, {"query": "qqqq zzzz"})
        self.assertIn("No ChatHub connector tools matched", text)
        self.assertIn("No close name found.", text)

    def test_list_form_query_is_tolerated(self) -> None:
        text = self._run(CATALOG, {"query": ["mail", "kb"]})
        self.assertEqual(self._names(text), ["ms365/send_mail", "kb/search"])

    def test_chinese_keyword_substring_match(self) -> None:
        text = self._run(CATALOG, {"query": "日程"})
        self.assertEqual(self._names(text), ["cal/list_events"])

    def test_non_list_payload_passes_through(self) -> None:
        payload = {"unexpected": "shape"}
        text = self._run(payload, {"query": "mail"})
        self.assertEqual(json.loads(text), {"unexpected": "shape"})

    def test_schema_exposes_optional_query_param(self) -> None:
        params = tools.LIST_CHATHUB_TOOLS_SCHEMA["parameters"]
        self.assertIn("query", params["properties"])
        self.assertEqual(params["properties"]["query"]["type"], "string")
        self.assertEqual(params.get("required", []), [])


if __name__ == "__main__":
    unittest.main()
