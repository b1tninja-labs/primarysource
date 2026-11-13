"""An error that names its remedy.

Every library in the family has the same rule: a missing corpus or index is an error that says what to run,
never an empty result. An empty list has to mean "nothing matched".
"""

from __future__ import annotations


class LibError(Exception):
    """A failure the caller can act on. `hint` is the command or step that fixes it, or empty."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def as_text(self) -> str:
        """One line for a CLI or a tool result: the message, then the hint if there is one."""
        return f"error: {self.message}" + (f"\nhint: {self.hint}" if self.hint else "")
