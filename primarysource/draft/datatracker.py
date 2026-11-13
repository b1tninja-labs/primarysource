"""Draft metadata from the IETF datatracker: three small JSON documents per draft, validated before use.

- `/doc/<name>/doc.json`, the datatracker's simplified document API (no key, no parameters): title, state,
  latest revision, expiry, authors and the whole revision history with posting dates;
- `/api/v1/doc/relateddocument/` filtered by relationship, twice: which draft *replaces* this one, and which RFC
  this draft *became* (the `replaces` and `became_rfc` relationship names).

Everything the server sends is data, never trusted: every field is type-checked and length-capped, a name
extracted from a resource URI must match the draft or RFC name grammar, and a response for a different draft
than the one asked about is refused.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from primarysource.draft import names
from primarysource.draft.net import ARCHIVE, DATATRACKER, Fetcher, Response
from primarysource.draft.status import Status
from primarysource.errors import LibError

_DRAFT_URI = re.compile(r"/api/v1/doc/document/(draft-[a-z0-9]+(?:-[a-z0-9]+)*)/")
_RFC_URI = re.compile(r"/api/v1/doc/document/rfc([0-9]{1,5})/")
_MAX_TEXT = 500
_MAX_REVISIONS = 100
_MAX_AUTHORS = 50
_MAX_LINKS = 20


def doc_url(name: str) -> str:
    return f"https://{DATATRACKER}/doc/{quote(names.parse_name(name), safe='')}/doc.json"


def replaced_by_url(name: str) -> str:
    return (
        f"https://{DATATRACKER}/api/v1/doc/relateddocument/?target__name={quote(names.parse_name(name), safe='')}"
        "&relationship__slug=replaces&format=json"
    )


def became_rfc_url(name: str) -> str:
    return (
        f"https://{DATATRACKER}/api/v1/doc/relateddocument/?source__name={quote(names.parse_name(name), safe='')}"
        "&relationship__slug=became_rfc&format=json"
    )


def archive_url(name: str, rev: str, suffix: str) -> str:
    """The IETF archive's copy of one revision: `suffix` is `txt` or `xml`."""
    if suffix not in ("txt", "xml"):
        raise ValueError(suffix)
    return f"https://{ARCHIVE}/archive/id/{names.with_revision(name, rev)}.{suffix}"


def html_url(name: str, rev: str) -> str:
    """The datatracker's rendering of one revision, which the cite string points at."""
    return f"https://{DATATRACKER}/doc/html/{names.with_revision(name, rev)}"


def _json(reply: Response, what: str) -> dict[str, Any]:
    try:
        data = json.loads(reply.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LibError(f"the datatracker's answer for {what} is not JSON", "try again later") from exc
    if not isinstance(data, dict):
        raise LibError(f"the datatracker's answer for {what} is not a JSON object", "")
    return data


def _text(data: dict[str, Any], key: str, required: bool = False) -> str:
    value = data.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise LibError(f"the datatracker's {key!r} is not text", "")
    return " ".join(value.split())[:_MAX_TEXT]


def parse_doc(reply: Response, name: str, checked: datetime) -> Status:
    """`doc.json` -> a `Status` without the relations (`replaced_by`, `became_rfc`), which come separately."""
    data = _json(reply, name)
    if data.get("name") != name:
        raise LibError(f"asked the datatracker for {name} and it answered for {str(data.get('name'))[:60]!r}", "")
    rev = _text(data, "rev", required=True)
    names.valid_revision(rev)
    history: list[tuple[str, str]] = []
    raw_history = data.get("rev_history")
    if not isinstance(raw_history, list):
        raise LibError("the datatracker's revision history is not a list", "")
    for item in raw_history[:_MAX_REVISIONS]:
        if isinstance(item, dict) and isinstance(item.get("rev"), str) and re.fullmatch(r"[0-9]{2}", item["rev"]):
            history.append((item["rev"], _text(item, "published")))
    history.sort()
    authors: list[str] = []
    for person in data.get("authors") or []:
        if isinstance(person, dict) and isinstance(person.get("name"), str) and person["name"].strip():
            authors.append(" ".join(person["name"].split())[:100])
    group = data.get("group")
    pages = data.get("pages")
    return Status(
        name=name,
        title=_text(data, "title", required=True),
        state=_text(data, "state", required=True),
        rev=rev,
        expires=_text(data, "expires"),
        replaced_by=(),
        became_rfc=None,
        revisions=tuple(history),
        authors=tuple(authors[:_MAX_AUTHORS]),
        group=_text(group, "acronym") if isinstance(group, dict) else "",
        stream=_text(data, "stream"),
        pages=pages if isinstance(pages, int) and not isinstance(pages, bool) else None,
        checked=checked.replace(microsecond=0).isoformat(),
    )


def _related(reply: Response, field: str, pattern: re.Pattern[str]) -> list[str]:
    data = _json(reply, "a relationship query")
    objects = data.get("objects")
    if not isinstance(objects, list):
        raise LibError("the datatracker's relationship answer has no object list", "")
    found: list[str] = []
    for item in objects[:_MAX_LINKS]:
        match = (
            pattern.fullmatch(item.get(field, ""))
            if isinstance(item, dict) and isinstance(item.get(field), str)
            else None
        )
        if match:
            found.append(match.group(1))
    return found


def fetch_status(fetcher: Fetcher, name: str, now: datetime | None = None) -> Status:
    """Three requests: the document, who replaces it, and whether it became an RFC. A 404 on the document means
    the datatracker has never heard of the name."""
    name = names.parse_name(name)
    checked = now or datetime.now(UTC)
    reply = fetcher.get(doc_url(name))
    if reply.status == 404:
        raise LibError(
            f"the datatracker has no draft named {name}", "check the spelling, or search datatracker.ietf.org"
        )
    if reply.status != 200:
        raise LibError(f"the datatracker answered {reply.status} for {name}", "try again later")
    base = parse_doc(reply, name, checked)
    replaced = fetcher.get(replaced_by_url(name))
    became = fetcher.get(became_rfc_url(name))
    if replaced.status != 200 or became.status != 200:
        raise LibError(f"the datatracker's relationship queries for {name} failed", "try again later")
    by = tuple(sorted(_related(replaced, "source", _DRAFT_URI)))
    rfcs = _related(became, "target", _RFC_URI)
    return replace(base, replaced_by=by, became_rfc=f"RFC{int(rfcs[0])}" if rfcs else None)
