"""An error that names its remedy.

Every library in the family has the same rule: a missing corpus or index is an error that says what to run,
never an empty result. An empty list has to mean "nothing matched".

The text of an error is fixed lines in a fixed order (PLAN.md §5.10), the same in a CLI and in an MCP `isError`
result: `error: <message>`, then `hint: <what to call next>`, then `action: <command a human must run>`. An empty
field is left out.
"""

from __future__ import annotations

ERROR_LINES = ("error", "hint", "action")


class LibError(Exception):
    """A failure the caller can act on. `hint` is the tool call or command that fixes it, or empty; `action` is a
    command only a human can run (a fetch, an import, an install), or empty."""

    def __init__(self, message: str, hint: str = "", action: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.action = action

    def as_text(self) -> str:
        """The `error:`, `hint:` and `action:` lines, in that order, without the empty ones."""
        fields = {"error": self.message, "hint": self.hint, "action": self.action}
        return "\n".join(f"{key}: {fields[key]}" for key in ERROR_LINES if fields[key])
