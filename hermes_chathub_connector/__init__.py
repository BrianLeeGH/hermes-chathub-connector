"""ChatHub connector-platform plugin for Hermes Agent."""

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


__all__ = ["register"]
