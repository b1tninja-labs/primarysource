"""One exception type for every state with a known remedy.

A tool that answers "no results" when the real state is "no ZIM files are installed" is the bug this portfolio
keeps rediscovering, so each such state raises `ZimloreError` carrying the command that fixes it, and the CLI
and the MCP server both turn it into an error object naming that command.
"""

from __future__ import annotations

MCP_ONLY = ("tool_hint", "user_action", "user_command")
"""Extra keys that speak to a model: `tool_hint` names MCP tools, `user_action` says what only the human can do and
`user_command` is the command to give them. The CLI's reader is the human, so it never prints these."""
CLI_ONLY = ("snapshot_hint",)
"""Extra keys worded as CLI commands, which a model with only tools cannot run."""


class ZimloreError(Exception):
    def __init__(self, message: str, hint: str = "", **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.extra = extra

    def as_dict(self) -> dict[str, object]:
        """The CLI wording: `hint` names commands, and the keys meant for a model are left out."""
        payload: dict[str, object] = {"error": self.message}
        if self.hint:
            payload["hint"] = self.hint
        payload.update({k: v for k, v in self.extra.items() if k not in MCP_ONLY})
        return payload

    def as_mcp_dict(self) -> dict[str, object]:
        """The wording for a model that has tools and no shell: `tool_hint` replaces `hint` when there is one, the
        CLI command survives only as `user_command` where a human must act, and CLI-only keys are dropped."""
        payload: dict[str, object] = {"error": self.message}
        hint = self.extra.get("tool_hint") or self.hint
        if hint:
            payload["hint"] = hint
        payload.update({k: v for k, v in self.extra.items() if k not in CLI_ONLY and k != "tool_hint"})
        return payload


class LibraryNotFound(ZimloreError):
    """No installed library matches a name. A subclass so callers (the service) can add what is obtainable
    without matching on message text."""
