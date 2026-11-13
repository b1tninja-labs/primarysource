"""One exception type for every state with a known remedy: a `LibError` (PLAN.md §5.10).

A tool that answers "no results" when the real state is "no ZIM files are installed" is the bug this portfolio
keeps rediscovering, so each such state raises `ZimloreError` carrying the fix. It has the core's three fields:

- `hint`: what a model with only tools should call next (`zim_available`, `zim_outline ref=...`), or prose that
  names no command;
- `action`: the command a human must run (`primarysource zim catalog --refresh`), only where only a human can act.

zimlore's two audiences (`hint` for the CLI, `tool_hint` for MCP) survive in how an error is *built*: a call site
still passes a CLI-worded `hint` (a command line) and, where a model can act on its own, `tool_hint=` (the tool to
call), `user_action=` (what to ask the user) and `user_command=` (the command to give them). The constructor
sorts them into `hint` and `action`; `cli_text` is the CLI's reading, which puts the command first.
"""

from __future__ import annotations

from primarysource.errors import LibError

_COMMAND = "primarysource zim"
CLI_ONLY = ("snapshot_hint",)
"""Extra keys worded as CLI commands, which a model with only tools cannot run."""
SORTED_OUT = ("tool_hint", "user_action", "user_command")
"""Extra keys the constructor turns into `hint` and `action`."""


def _name(item: object) -> str:
    return str(item["name"]) if isinstance(item, dict) and "name" in item else str(item)


def _listed(extra: dict[str, object]) -> list[str]:
    """`did_you_mean`, `candidates` and `installed` as hint text: the error text has no other place for them."""
    found = []
    for key in ("did_you_mean", "candidates", "installed"):
        value = extra.get(key)
        if isinstance(value, list) and value:
            found.append(f"{key.replace('_', ' ')}: {', '.join(_name(item) for item in value)}")
    obtainable = extra.get("obtainable")
    if isinstance(obtainable, list) and obtainable:
        names = ", ".join(_name(item) for item in obtainable)
        found.append(
            f"not installed, but in the catalogue snapshot: {names} (zim_available gives the install command)"
        )
    return found


class ZimloreError(LibError):
    def __init__(self, message: str, hint: str = "", **extra: object) -> None:
        super().__init__(message)
        self.cli_hint = hint
        self.extra = extra
        self.settle()

    def settle(self) -> None:
        """(Re)build `hint` and `action` from the CLI hint and the extras; call it after changing `extra`."""
        extra = self.extra
        tool = str(extra.get("tool_hint") or "")
        user = str(extra.get("user_action") or "")
        command = str(extra.get("user_command") or "")
        if self.cli_hint and _COMMAND in self.cli_hint:
            cli_command, prose = self.cli_hint, ""
        else:
            cli_command, prose = "", self.cli_hint
        # A command the model can replace with a tool is not an action; one it cannot (`catalog --refresh` touches
        # the network, `get` downloads) is the human's.
        self.action = command or ("" if tool else cli_command)
        self.hint = "; ".join(part for part in (user, tool, prose, *_listed(extra)) if part)

    def cli_text(self) -> str:
        """The CLI's reading: the command to run, then what a model would call, without the lines it cannot use."""
        lines = [f"error: {self.message}"]
        fix = self.cli_hint or self.hint
        if fix:
            lines.append(f"hint: {fix}")
        if self.action and self.action != self.cli_hint:
            lines.append(f"action: {self.action}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        """The CLI's `--json` wording: `hint` names commands, and the keys meant for a model are left out."""
        payload: dict[str, object] = {"error": self.message}
        if self.cli_hint:
            payload["hint"] = self.cli_hint
        payload.update({k: v for k, v in self.extra.items() if k not in SORTED_OUT})
        return payload

    def detail(self) -> str:
        """The extras that name something (`did_you_mean`, `candidates`, `installed`, `anchors`), one line each,
        for the places an error is shown as text."""
        lines = []
        for key in ("did_you_mean", "candidates", "installed", "anchors", "obtainable"):
            value = self.extra.get(key)
            if value:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)


class LibraryNotFound(ZimloreError):
    """No installed library matches a name. A subclass so callers (the service) can add what is obtainable
    without matching on message text."""
