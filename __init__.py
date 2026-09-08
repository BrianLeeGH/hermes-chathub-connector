"""ChatHub connector-platform plugin — two static meta-tools.

Registers ``list_chathub_tools`` / ``exec_chathub_tools`` into the ``chathub``
toolset. Handlers live in the self-contained ``tools`` module.

Deployment contract (see chathub-connector-platform-design.md §8):

* The plugin knows nothing about individual connectors / upstream MCP servers.
* Every call reads the current turn secret with ``get_secret("CHATHUB_TURN_SECRET")``
  (turn-level freshness — the secret is written to the profile ``.env`` right
  before each prompt submit and revoked when the turn ends).
* The gateway base URL is static configuration: ``connector.gateway_url`` in
  Hermes config.yaml, or ``CHATHUB_GATEWAY_URL`` env, else a baked default.

Model-facing flow: call ``list_chathub_tools`` first to get the full prefixed
tool names (``{connectorKey}/{toolName}``), then call ``exec_chathub_tools``
with the exact name and its JSON args.
"""

from __future__ import annotations

from .tools import (
    EXEC_CHATHUB_TOOLS_SCHEMA,
    LIST_CHATHUB_TOOLS_SCHEMA,
    _handle_exec_chathub_tools,
    _handle_list_chathub_tools,
)

_TOOLS = (
    ("list_chathub_tools", LIST_CHATHUB_TOOLS_SCHEMA, _handle_list_chathub_tools, "📇"),
    ("exec_chathub_tools", EXEC_CHATHUB_TOOLS_SCHEMA, _handle_exec_chathub_tools, "🔌"),
)


def register(ctx) -> None:
    """Register both tools. Called once by the Hermes plugin loader."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="chathub",
            schema=schema,
            handler=handler,
            check_fn=None,
            emoji=emoji,
        )
