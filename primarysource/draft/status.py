"""A draft's life cycle as the datatracker last reported it, and what that means for someone about to cite it.

`Status` is a snapshot with the time it was taken. It is stored beside the draft's revisions and printed by
`info`, and every read and cite result puts its verdict in the `warning:` line, so a caller never quotes a dead
draft without being told: RFC 2026 §2.2 says an Internet-Draft is removed after six months unchanged, has no
formal status and is subject to change or removal at any time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from primarysource.errors import LibError

STALE_DAYS = 14

ACTIVE = "active"
EXPIRED = "expired"
REPLACED = "replaced"
RFC = "rfc"
WITHDRAWN = "withdrawn"
UNKNOWN = "unknown"

_LEVELS = {
    "active": ACTIVE,
    "expired": EXPIRED,
    "replaced": REPLACED,
    "rfc": RFC,
    "withdrawn by submitter": WITHDRAWN,
    "withdrawn by ietf": WITHDRAWN,
}


@dataclass(frozen=True, slots=True)
class Status:
    """What the datatracker said about `name` at `checked`. `rev` is the latest revision it knew then;
    `revisions` are (revision, publication date) pairs; `replaced_by` are the drafts that replace this one and
    `became_rfc` the RFC it was published as (`RFC8210`), if any."""

    name: str
    title: str
    state: str
    rev: str
    expires: str
    replaced_by: tuple[str, ...]
    became_rfc: str | None
    revisions: tuple[tuple[str, str], ...]
    authors: tuple[str, ...]
    group: str
    stream: str
    pages: int | None
    checked: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, ensure_ascii=False) + "\n"

    @staticmethod
    def from_json(text: str) -> Status:
        """Read a stored snapshot; a damaged one is a LibError that names the command that rewrites it."""
        try:
            raw: dict[str, Any] = json.loads(text)
            return Status(
                name=str(raw["name"]),
                title=str(raw["title"]),
                state=str(raw["state"]),
                rev=str(raw["rev"]),
                expires=str(raw["expires"]),
                replaced_by=tuple(str(x) for x in raw["replaced_by"]),
                became_rfc=None if raw["became_rfc"] is None else str(raw["became_rfc"]),
                revisions=tuple((str(a), str(b)) for a, b in raw["revisions"]),
                authors=tuple(str(x) for x in raw["authors"]),
                group=str(raw["group"]),
                stream=str(raw["stream"]),
                pages=None if raw["pages"] is None else int(raw["pages"]),
                checked=str(raw["checked"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise LibError("a stored status snapshot is damaged", "", "primarysource draft refresh") from exc

    def published(self, rev: str) -> str:
        """The date revision `rev` was posted (YYYY-MM-DD), or ''."""
        for known, when in self.revisions:
            if known == rev:
                return when[:10]
        return ""


def _day(text: str) -> date | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date() if text else None
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """`level` is one of the module constants; `text` is one sentence for a person; `alive` is True only for a
    draft that is active and not past its expiry date."""

    level: str
    text: str
    alive: bool


def lifecycle(status: Status, today: date | None = None) -> Lifecycle:
    """The verdict on a snapshot. A draft whose datatracker state is still Active but whose expiry date has
    passed is reported as expired by date, because the snapshot may simply be old."""
    today = today or datetime.now(UTC).date()
    level = _LEVELS.get(status.state.strip().lower(), UNKNOWN)
    when = status.expires[:10]
    if level == RFC or (status.became_rfc and level != REPLACED):
        rfc = status.became_rfc or "an RFC"
        return Lifecycle(RFC, f"published as {rfc}: cite the RFC, not this draft", False)
    if level == REPLACED:
        by = ", ".join(status.replaced_by) or "another draft"
        return Lifecycle(REPLACED, f"replaced by {by}: this draft is dead, read and cite its successor", False)
    if level == WITHDRAWN:
        return Lifecycle(WITHDRAWN, f"{status.state.lower()}: do not rely on it", False)
    if level == EXPIRED:
        return Lifecycle(
            EXPIRED,
            f"expired on {when or 'an unknown date'}: not an active draft, and may have been abandoned",
            False,
        )
    if level == ACTIVE:
        end = _day(status.expires)
        if end is not None and end < today:
            return Lifecycle(
                EXPIRED,
                f"past its expiry date {when} though the datatracker listed it Active at the last check",
                False,
            )
        return Lifecycle(
            ACTIVE, f"active, expires {when}: work in progress" if when else "active: work in progress", True
        )
    return Lifecycle(UNKNOWN, f"the datatracker reported the state {status.state!r}: check it before citing", False)


def staleness(status: Status, today: date | None = None) -> int:
    """Days since the snapshot was taken (0 if its date cannot be read)."""
    today = today or datetime.now(UTC).date()
    taken = _day(status.checked)
    return max(0, (today - taken).days) if taken else 0
