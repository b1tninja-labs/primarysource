"""The one exception type for every state with a known remedy: a `LibError` (primarysource/errors.py).

A tool that answers "no results" when the real state is "the corpus was never synced" sends an agent to conclude a
CVE does not exist. Each such state raises `CvelibError` with the command that fixes it in `action` (what a human
must run, e.g. `primarysource cve sync --source kev`) and the call to make next in `hint`. The CLI prints its
`error:`, `hint:` and `action:` lines with exit status 2; the MCP server returns the same lines as an `isError`
result (PLAN.md §5.10).
"""

from __future__ import annotations

from primarysource.errors import LibError


class CvelibError(LibError):
    """A `LibError` raised by the cve collection; the name is kept so the code that raises it reads as it did."""
