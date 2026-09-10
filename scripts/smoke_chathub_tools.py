#!/usr/bin/env python3
"""Smoke test for the hermes-chathub-connector plugin (runs inside Hermes).

Proves, without any real turn secret:
  1. The deployed plugin modules import cleanly (same namespace mechanism the
     Hermes loader uses: hermes_plugins.<slug>).
  2. Both tool handlers attach the X-Turn-Secret header read from env via
     get_secret("CHATHUB_TURN_SECRET") on every call.
  3. list returns the catalog JSON on HTTP 200; exec posts {name, args} and
     returns the result.
  4. HTTP 401 (and other non-2xx) are surfaced as tool error results (status +
     body), never raised.
  5. A missing turn secret fails closed with a descriptive tool error.
  6. Gateway base URL resolution honors CHATHUB_GATEWAY_URL env override.

Run (Hermes-WSL):
  /usr/local/lib/hermes-agent/venv/bin/python scripts/smoke_chathub_tools.py \
      --plugin-dir /root/.hermes/plugins/chathub-connector \
      [--install-dir /usr/local/lib/hermes-agent] \
      [--gateway http://127.0.0.1:44340]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PASS = 0
_FAIL = 0


def report(ok: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    tag = "PASS" if ok else "FAIL"
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    print(f"[{tag}] {label}" + (f" — {detail}" if detail else ""), flush=True)


def load_plugin_module(plugin_dir: str, install_dir: str):
    """Mirror hermes_cli.plugins._load_directory_module to import the plugin."""
    # The directory loader supplies the plugin package path, while the thin
    # compatibility shell imports the installable child package by name.
    sys.path.insert(0, plugin_dir)
    sys.path.insert(0, install_dir)
    ns_name = "hermes_plugins"
    if ns_name not in sys.modules:
        ns_pkg = types.ModuleType(ns_name)
        ns_pkg.__path__ = []
        ns_pkg.__package__ = ns_name
        sys.modules[ns_name] = ns_pkg
    slug = "chathub_connector"
    module_name = f"{ns_name}.{slug}"
    init_file = os.path.join(plugin_dir, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        module_name, init_file, submodule_search_locations=[plugin_dir]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [plugin_dir]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    import hermes_plugins.chathub_connector.tools as tools  # noqa: PLC0415

    return tools


# ---------------------------------------------------------------------------
# Mock gateway
# ---------------------------------------------------------------------------

class MockGateway(BaseHTTPRequestHandler):
    seen: dict = {}
    mode: str = "ok"

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).seen["GET"] = {
            "path": self.path,
            "x_turn_secret": self.headers.get("X-Turn-Secret"),
        }
        if self.path == "/api/connectors/tools":
            if type(self).mode == "unauthorized":
                self._respond(
                    401,
                    {"error": "invalid_token", "error_description": "turn secret expired or revoked"},
                )
            else:
                self._respond(
                    200,
                    [
                        {
                            "name": "ms365/get_current_user",
                            "description": "Get signed-in user profile",
                            "inputSchemaJson": "{}",
                        },
                        {"name": "ms365/list_events", "description": "List calendar events"},
                    ],
                )
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {"__raw__": raw}
        type(self).seen["POST"] = {
            "path": self.path,
            "x_turn_secret": self.headers.get("X-Turn-Secret"),
            "body": body,
        }
        if self.path == "/api/connectors/tools:call":
            if type(self).mode == "unauthorized":
                self._respond(
                    401,
                    {"error": "invalid_token", "error_description": "turn secret expired or revoked"},
                )
            else:
                self._respond(
                    200,
                    {"success": True, "output": f"executed {body.get('name')}"},
                )
        else:
            self._respond(404, {"error": "not found"})

    def log_message(self, *args):  # silence
        pass


def start_mock(mode: str) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (MockGateway,), {"mode": mode})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", default="/root/.hermes/plugins/chathub-connector")
    parser.add_argument("--install-dir", default="/usr/local/lib/hermes-agent")
    parser.add_argument("--gateway", default="http://127.0.0.1:44340")
    args = parser.parse_args()

    print(f"== plugin-dir: {args.plugin_dir}")
    print(f"== install-dir: {args.install_dir}")
    tools = load_plugin_module(args.plugin_dir, args.install_dir)
    report(True, "plugin imports", "hermes_plugins.chathub_connector.tools loaded")

    secret = "smoke-turn-secret-abc123"
    os.environ["CHATHUB_TURN_SECRET"] = secret

    # --- 1. list via mock (200) + header injection + env override of base URL
    server, mock_base = start_mock("ok")
    try:
        os.environ["CHATHUB_GATEWAY_URL"] = mock_base
        result = tools._handle_list_chathub_tools({})
        seen = MockGateway.seen.get("GET", {})
        header_ok = seen.get("x_turn_secret") == secret
        report(header_ok, "list attaches X-Turn-Secret", f"seen={seen.get('x_turn_secret')!r}")
        parsed = json.loads(result)
        names = [t.get("name") for t in parsed] if isinstance(parsed, list) else []
        report(
            isinstance(parsed, list) and "ms365/get_current_user" in names,
            "list returns catalog JSON on 200",
            f"entries={names}",
        )
        report(
            seen.get("path") == "/api/connectors/tools",
            "list hits GET /api/connectors/tools",
        )

        # --- 2. exec via mock (200): body shape + header
        MockGateway.seen.clear()
        result = tools._handle_exec_chathub_tools(
            {"name": "ms365/list_events", "args": json.dumps({"max": 5})}
        )
        seen = MockGateway.seen.get("POST", {})
        header_ok = seen.get("x_turn_secret") == secret
        report(header_ok, "exec attaches X-Turn-Secret", f"seen={seen.get('x_turn_secret')!r}")
        report(
            seen.get("path") == "/api/connectors/tools:call",
            "exec hits POST /api/connectors/tools:call",
        )
        body = seen.get("body", {})
        report(
            body.get("name") == "ms365/list_events" and body.get("args") == {"max": 5},
            "exec posts {name, args} with parsed JSON args",
            f"body={body}",
        )
        parsed = json.loads(result)
        report(
            isinstance(parsed, dict) and parsed.get("success") is True,
            "exec returns result on 200",
            f"result={result[:80]}",
        )
    finally:
        server.shutdown()

    # --- 3. exec via mock (401): error passthrough, not an exception
    server, mock_base = start_mock("unauthorized")
    try:
        os.environ["CHATHUB_GATEWAY_URL"] = mock_base
        result = tools._handle_exec_chathub_tools({"name": "ms365/x", "args": {}})
        parsed = json.loads(result)
        ok = parsed.get("error") and parsed.get("status") == 401
        report(ok, "exec surfaces HTTP 401 as tool error result", f"result={result[:160]}")
        MockGateway.seen.clear()
        result = tools._handle_list_chathub_tools({})
        parsed = json.loads(result)
        ok = parsed.get("error") and parsed.get("status") == 401
        report(ok, "list surfaces HTTP 401 as tool error result", f"result={result[:160]}")
    finally:
        server.shutdown()

    # --- 4. missing secret: fail closed with descriptive error
    os.environ.pop("CHATHUB_TURN_SECRET", None)
    result = tools._handle_list_chathub_tools({})
    parsed = json.loads(result)
    report(
        bool(parsed.get("error")) and "CHATHUB_TURN_SECRET" in parsed.get("error", ""),
        "missing turn secret fails closed (no HTTP attempted)",
        f"result={result[:120]}",
    )
    os.environ["CHATHUB_TURN_SECRET"] = secret

    # --- 5. real gateway probe (old LocalSIT binary: 401/404/empty reply OK)
    os.environ["CHATHUB_GATEWAY_URL"] = args.gateway
    print(f"== real gateway probe: {args.gateway}")
    result = tools._handle_list_chathub_tools({})
    parsed = json.loads(result)
    ok = bool(parsed.get("error"))  # must come back as an error result, not raise
    report(ok, "real gateway list returns graceful tool error", f"result={result[:200]}")
    result = tools._handle_exec_chathub_tools(
        {"name": "ms365/get_current_user", "args": "{}"}
    )
    parsed = json.loads(result)
    ok = bool(parsed.get("error"))
    report(ok, "real gateway exec returns graceful tool error", f"result={result[:200]}")

    os.environ.pop("CHATHUB_GATEWAY_URL", None)
    os.environ.pop("CHATHUB_TURN_SECRET", None)

    print(f"\n== SUMMARY: {_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
