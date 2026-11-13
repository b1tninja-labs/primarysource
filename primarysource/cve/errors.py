"""One exception type for every state with a known remedy.

A tool that answers "no results" when the real state is "the corpus was never synced" sends an agent to conclude a
CVE does not exist. Each such state raises `CvelibError` carrying the command that fixes it; the CLI prints it with
exit status 2 and the MCP server returns it as an `{"error", "hint"}` object.
"""

from __future__ import annotations


class CvelibError(Exception):
    def __init__(self, message: str, hint: str = "", **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.extra = extra

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"error": self.message}
        if self.hint:
            payload["hint"] = self.hint
        payload.update(self.extra)
        return payload
