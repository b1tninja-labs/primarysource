"""The terms-acknowledgement gate for collections built from files whose publisher's terms the owner must accept.

A collection that holds a publisher's files (`gm`, `can`, and later `autosar`) imports them into a home folder and
serves text from them. Whether the owner may do that is the owner's reading of the publisher's terms, not
something this package can check. The gate makes the owner say so, once, in a place the program can see:

- the environment variable `PRIMARYSOURCE_<NAME>_ACCEPT_TERMS` (`1`, `true` or `yes`, in any case) asserts that the
  owner has read the publisher's terms for the files in that collection's home and accepts them. Unset, blank,
  `0`, `false`, `no` and `off` mean not accepted; any other value is an error naming the variable, as
  `settings.py` does for the network variable, never a silent "no";
- without it `import` and every read command refuse, with a `LibError` naming the variable, the home folder and,
  only when the collection gave one that was verified, the publisher's terms URL;
- with it, an import records the acknowledgement in the collection's `install.json`
  (`terms_acknowledgement`: the variable, and for each document the UTC time it was first recorded);
- serving a document needs both the variable and a recorded acknowledgement for that document, so an index built
  by anything other than the gated import is refused rather than answered.

The gate records an assertion; it does not check anyone's licence. `docs/terms-gate.md` says so, and why the
existing `iso` collection is not behind it. No publisher's terms text is held here.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource.errors import LibError

RECORD_KEY = "terms_acknowledgement"
ACCEPT = ("1", "true", "yes")
DECLINE = ("0", "false", "no", "off")


@dataclass(frozen=True, slots=True)
class Terms:
    """What a collection says about the terms of the files it holds. `url` is the publisher's terms page, given
    only when it was read and checked; None otherwise (the error then does not point at a page nobody verified)."""

    collection: str
    publisher: str
    url: str | None = None

    @property
    def variable(self) -> str:
        return f"PRIMARYSOURCE_{self.collection.upper()}_ACCEPT_TERMS"


def accepted(terms: Terms, environ: Mapping[str, str] | None = None) -> bool:
    """True when the owner's variable says yes. A value that is neither a yes nor a no is a `LibError`."""
    env = os.environ if environ is None else environ
    value = (env.get(terms.variable) or "").strip()
    if not value or value.lower() in DECLINE:
        return False
    if value.lower() in ACCEPT:
        return True
    raise LibError(
        f"{terms.variable}={value!r} is not a yes or a no",
        f"set {terms.variable} to 1 (you have read {terms.publisher}'s terms and accept them), or leave it unset",
    )


def refusal(terms: Terms, home: Path, what: str) -> LibError:
    """The error for `what` being refused because the variable is not set to a yes."""
    where = f" (the publisher's terms are at {terms.url})" if terms.url else ""
    return LibError(
        f"{what} is refused: {terms.variable} is not set to 1, true or yes. The {terms.collection} collection holds "
        f"{terms.publisher}'s files in {home}, and its owner must first accept the publisher's terms for them",
        f"read {terms.publisher}'s terms for those files{where}; if you accept them, set {terms.variable}=1. "
        "The variable is your assertion, it is not checked against anything",
    )


def require_accepted(terms: Terms, home: Path, what: str, environ: Mapping[str, str] | None = None) -> None:
    """Return if the variable says yes; else raise `refusal`."""
    if not accepted(terms, environ):
        raise refusal(terms, home, what)


def recorded(record: Mapping[str, Any]) -> dict[str, str]:
    """document id -> the UTC time its acknowledgement was first recorded, from an `install.json` record. A
    malformed entry counts as absent."""
    block = record.get(RECORD_KEY)
    documents = block.get("documents") if isinstance(block, dict) else None
    if not isinstance(documents, dict):
        return {}
    return {str(doc): str(when) for doc, when in documents.items() if isinstance(when, str) and when}


def record_acceptance(
    terms: Terms,
    record: dict[str, Any],
    docs: Iterable[str],
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    """Record, in `record`, that `docs` were imported with the variable set. Documents already recorded keep their
    first timestamp; the others get now (UTC). Refuses if the variable is not set, so nothing is recorded for an
    owner who did not assert."""
    if not accepted(terms, environ):
        raise LibError(f"{terms.variable} is not set to 1, true or yes", f"set {terms.variable}=1 and import again")
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
    documents = recorded(record)
    for doc in docs:
        documents.setdefault(doc, stamp)
    record[RECORD_KEY] = {"variable": terms.variable, "documents": dict(sorted(documents.items()))}


def require_served(
    terms: Terms,
    record: Mapping[str, Any],
    docs: Iterable[str],
    home: Path,
    what: str,
    import_command: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Serving `docs` needs the variable and a recorded acknowledgement for each. A document with none was indexed
    outside the gate: the error names it and the import that records one."""
    require_accepted(terms, home, what, environ)
    have = recorded(record)
    missing = sorted(d for d in docs if d not in have)
    if missing:
        raise LibError(
            f"{what} is refused: no terms acknowledgement is recorded for {', '.join(missing)} in {home}",
            f"the index was not built by the gated import; import the document again with {terms.variable} set",
            import_command,
        )
