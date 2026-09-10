"""ChatHub connector-platform bridge tools (self-contained handler module).

Imports only Hermes top-level modules (``agent.secret_scope``,
``tools.registry``) so it can also be exercised directly by scripts in
``scripts/`` via ``importlib`` against the same install tree.

Two static meta-tools:

* ``list_chathub_tools()``  -> GET {gateway}/be-api/connectors/tools
* ``exec_chathub_tools(name, args)`` -> POST {gateway}/be-api/connectors/tools:call

Both attach ``X-Turn-Secret`` (value from ``get_secret("CHATHUB_TURN_SECRET")``,
re-read on every call for turn-level freshness). Non-2xx responses (notably
401) are returned to the model as tool error results, never raised.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from agent.secret_scope import get_secret
from tools.registry import tool_error, tool_result

# Default gateway base URL — matches the local integration backend (LocalSIT).
# Override via config.yaml key ``connector.gateway_url`` or env
# ``CHATHUB_GATEWAY_URL`` (see _resolve_gateway_base_url).
DEFAULT_GATEWAY_BASE_URL = "http://127.0.0.1:44340"

TURN_SECRET_ENV_KEY = "CHATHUB_TURN_SECRET"
REQUEST_TIMEOUT_SECONDS = 30
# Guard against an enormous catalog flooding the context window.
MAX_LIST_BODY_CHARS = 60_000


def _tls_verify() -> bool:
    """TLS certificate verification toggle (dev-only convenience).

    The local integration backend (LocalSIT, https://127.0.0.1:44340) uses a
    self-signed certificate, so verification is disabled by default. Set
    ``CHATHUB_GATEWAY_TLS_VERIFY=1`` to re-enable verification (production).
    """
    return os.environ.get("CHATHUB_GATEWAY_TLS_VERIFY", "0") == "1"

LIST_CHATHUB_TOOLS_SCHEMA = {
    "name": "list_chathub_tools",
    "description": (
        "List the tools the user has registered with the ChatHub connector "
        "platform. Each entry's name is already fully prefixed with its "
        "connector key (e.g. ms365/get_current_user). Call this tool FIRST to "
        "discover the exact tool names and their input schemas, then invoke "
        "exec_chathub_tools with the complete name."
    ),
    "parameters": {"type": "object", "properties": {}},
}

EXEC_CHATHUB_TOOLS_SCHEMA = {
    "name": "exec_chathub_tools",
    "description": (
        "Execute a single ChatHub connector-platform tool by its full "
        "prefixed name as returned by list_chathub_tools (e.g. "
        "ms365/list_events). Provide args as a JSON string (or structured "
        "object) matching the tool's input schema. Authentication failures "
        "(401) and upstream errors are returned as the tool result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Full prefixed tool name from list_chathub_tools.",
            },
            "args": {
                "description": (
                    "Arguments for the tool as a JSON string, or a structured "
                    "JSON object."
                ),
            },
        },
        "required": ["name", "args"],
    },
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _resolve_gateway_base_url() -> str:
    """Resolve the gateway base URL.

    Precedence:
      1. ``CHATHUB_GATEWAY_URL`` env var (deployment override).
      2. Custom key ``connector.gateway_url`` in Hermes config.yaml
         (single source shared by every hermes process; static, never a secret).
      3. Built-in default (local integration backend).
    """
    env_url = os.environ.get("CHATHUB_GATEWAY_URL")
    if env_url:
        return env_url.rstrip("/")
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        connector_cfg = cfg.get("connector") if isinstance(cfg, dict) else None
        if isinstance(connector_cfg, dict):
            url = connector_cfg.get("gateway_url")
            if isinstance(url, str) and url.strip():
                return url.strip().rstrip("/")
    except Exception:
        # config.yaml read must never break a tool call.
        pass
    return DEFAULT_GATEWAY_BASE_URL


def _turn_secret() -> Optional[str]:
    """Read the current turn secret (fresh on every call)."""
    return get_secret(TURN_SECRET_ENV_KEY)


def _auth_headers(secret: str) -> dict:
    return {
        "X-Turn-Secret": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _normalize_args(raw: Any) -> Any:
    """Accept ``args`` as a structured object or a JSON string."""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return raw  # pass through verbatim; backend decides
    if raw is None:
        return {}
    return raw


def _catalog_payload(data: Any) -> Any:
    """Extract the tool list from the gateway response regardless of wrapper."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "tools", "data", "result"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        return data
    return data


def _http_get_json(url: str, headers: dict) -> tuple[int, Optional[Any], str]:
    """GET + JSON parse. Returns (status, parsed, raw_text)."""
    import requests

    resp = requests.get(
        url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, verify=_tls_verify()
    )
    return resp.status_code, _safe_json(resp), resp.text


def _http_post_json(url: str, headers: dict, body: dict) -> tuple[int, Optional[Any], str]:
    """POST JSON + parse. Returns (status, parsed, raw_text)."""
    import requests

    resp = requests.post(
        url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS, verify=_tls_verify()
    )
    return resp.status_code, _safe_json(resp), resp.text


def _safe_json(resp: Any) -> Optional[Any]:
    try:
        if not resp.text:
            return None
        return resp.json()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_list_chathub_tools(args: dict, **kw) -> str:
    """GET {gateway}/be-api/connectors/tools -> catalog string (or error result)."""
    secret = _turn_secret()
    if not secret:
        return tool_error(
            "No CHATHUB_TURN_SECRET available in this context. "
            "The connector bridge is only usable inside an active ChatHub turn "
            "that has provisioned a turn secret.",
            code="missing-turn-secret",
        )

    base = _resolve_gateway_base_url()
    url = f"{base}/be-api/connectors/tools"
    try:
        status, parsed, raw = _http_get_json(url, _auth_headers(secret))
    except Exception as exc:  # network-level failure — keep the model informed
        return tool_error(
            f"ChatHub gateway unreachable at {base}: "
            f"{type(exc).__name__}: {exc}",
            code="gateway-unreachable",
            gateway=base,
        )

    if status == 200:
        payload = _catalog_payload(parsed)
        text = json.dumps(payload, ensure_ascii=False) if parsed is not None else (raw or "")
        if len(text) > MAX_LIST_BODY_CHARS:
            text = text[:MAX_LIST_BODY_CHARS] + "\n...[truncated]"
        return text
    # Non-2xx: surface status + body so the model sees 401/404/429/502 reasons.
    detail = _trim(raw or (json.dumps(parsed, ensure_ascii=False) if parsed is not None else ""))
    return tool_error(
        f"ChatHub gateway list failed with HTTP {status}",
        status=status,
        detail=detail,
        gateway=base,
    )


def _handle_exec_chathub_tools(args: dict, **kw) -> str:
    """POST {gateway}/be-api/connectors/tools:call {name, args} -> result string."""
    secret = _turn_secret()
    if not secret:
        return tool_error(
            "No CHATHUB_TURN_SECRET available in this context. "
            "The connector bridge is only usable inside an active ChatHub turn "
            "that has provisioned a turn secret.",
            code="missing-turn-secret",
        )

    name = str(args.get("name") or "").strip()
    if not name:
        return tool_error("exec_chathub_tools requires a 'name' (full prefixed tool name).")
    tool_args = _normalize_args(args.get("args"))

    base = _resolve_gateway_base_url()
    url = f"{base}/be-api/connectors/tools:call"
    body = {"name": name, "args": tool_args}
    try:
        status, parsed, raw = _http_post_json(url, _auth_headers(secret), body)
    except Exception as exc:
        return tool_error(
            f"ChatHub gateway unreachable at {base}: "
            f"{type(exc).__name__}: {exc}",
            code="gateway-unreachable",
            gateway=base,
        )

    if 200 <= status < 300:
        if parsed is not None:
            return tool_result(parsed)
        return tool_result({"success": True, "output": raw})
    detail = _trim(raw or (json.dumps(parsed, ensure_ascii=False) if parsed is not None else ""))
    return tool_error(
        f"ChatHub gateway exec of '{name}' failed with HTTP {status}",
        status=status,
        detail=detail,
        tool=name,
        gateway=base,
    )


def _trim(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")
