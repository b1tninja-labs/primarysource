"""Import named drafts from the IETF into the library: `primarysource draft import <name>[-rev]`.

For one draft the importer makes at most five requests, one second apart (net.Fetcher), in this order:

1. `doc.json`, the replaced-by query and the became-RFC query (datatracker.fetch_status): the draft's state,
   latest revision, expiry and revision history. The snapshot is written first, so a draft found to be dead is
   recorded as dead even if the text fetch then fails;
2. the revision's `.txt` from the IETF archive: required, because it is what is segmented and cited;
3. the revision's `.xml`, the author's source: optional (many drafts and every pre-xml2rfc draft have none), and
   skipped with `want_xml=False`.

Each file is verified before anything is written. A digest pinned in the catalogue (or given as
`expected_sha256`) must match; a file with no pin is trusted on first use and its digest recorded in the
revision's `meta.json`. A text that is not text (NUL bytes, absurd lines, an HTML error page behind a 200) is
refused. A revision already stored is not fetched again: the archive's revisions do not change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from primarysource.draft import catalogue, datatracker, licence, names, segment, xmlmeta
from primarysource.draft.net import Fetcher, Response
from primarysource.draft.status import Status
from primarysource.draft.store import RevMeta, Store, readonly
from primarysource.errors import LibError


@dataclass(frozen=True, slots=True)
class Report:
    """What one import did. `new` is False when the revision was already stored (only the status was refreshed)."""

    name: str
    rev: str
    path: Path
    new: bool
    txt_bytes: int
    txt_sha256: str
    xml_state: str
    xml_sha256: str
    pinned: bool
    status: Status
    requests: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _body(reply: Response, url: str, kind: str) -> bytes | None:
    """The body of a 200 for the right kind of file. None for a 404, and for an optional file (`xml`) that came
    back as something else; a LibError for a `txt` that did, because the archive answers a missing file with an
    HTML page and that is not the draft."""
    if reply.status == 404:
        return None
    if reply.status != 200:
        raise LibError(f"the IETF archive answered {reply.status} for {url}", "try again later")
    kind_ok = "text/plain" if kind == "txt" else "xml"
    if kind_ok not in reply.content_type.lower() or "html" in reply.content_type.lower() or not reply.body.strip():
        if kind == "xml":
            return None
        raise LibError(
            f"{url} came back as {reply.content_type or 'no content type'!r} or empty, not a text draft", ""
        )
    return reply.body


def _check(got: str, pinned: str | None, expected: str | None, what: str) -> bool:
    """Compare a digest with the explicit one (it wins) or the catalogue's; True if something pinned it."""
    want = expected or pinned
    if want is not None and got != want:
        raise LibError(
            f"{what} has sha256 {got}, not the {want} pinned for it: the archive's copy changed or the download "
            "is damaged, and nothing was stored",
            "try again; if it persists, the pin in tracked.json or --sha256 is what to re-check",
        )
    return want is not None


def refresh(name: str, *, fetcher: Fetcher, store: Store, now: datetime | None = None) -> Status:
    """Fetch and store the datatracker's current word on `name` (three requests). Needs no stored revision."""
    if readonly():
        raise LibError("the library is read-only (PRIMARYSOURCE_READONLY): nothing is fetched or written", "")
    status = datatracker.fetch_status(fetcher, names.parse_name(name), now)
    store.write_status(status)
    return status


def import_draft(
    name: str,
    rev: str | None = None,
    *,
    fetcher: Fetcher,
    store: Store,
    want_xml: bool = True,
    expected_sha256: str | None = None,
    now: datetime | None = None,
) -> Report:
    """Import one revision of `name`: the latest the datatracker knows when `rev` is None."""
    name = names.parse_name(name)
    if rev is not None:
        names.valid_revision(rev)
    started = fetcher.requests
    status = refresh(name, fetcher=fetcher, store=store, now=now)
    known = [r for r, _when in status.revisions]
    rev = rev or status.rev
    if known and rev not in known:
        raise LibError(f"{name} has no revision {rev} (the datatracker lists: {', '.join(known)})", "")
    if store.has(name, rev):
        meta = store.meta(name, rev)
        return Report(
            name, rev, store.path(name, rev), False, meta.txt_bytes, meta.txt_sha256, meta.xml_state, meta.xml_sha256,
            catalogue.pin_for(name, rev) is not None, status, fetcher.requests - started,
        )  # fmt: skip
    pin = catalogue.pin_for(name, rev)
    txt_url = datatracker.archive_url(name, rev, "txt")
    txt = _body(fetcher.get(txt_url), txt_url, "txt")
    if txt is None:
        raise LibError(
            f"the IETF archive has no text for {name}-{rev}",
            "a draft submitted as XML only is not supported yet (docs/draft.md)",
        )
    pinned = _check(sha256(txt), pin.txt if pin else None, expected_sha256, f"{name}-{rev}.txt")
    text, encoding = segment.decode(txt)
    found = segment.segment(text)
    xml: bytes | None = None
    info = xmlmeta.XmlInfo("skipped")
    if want_xml:
        xml_url = datatracker.archive_url(name, rev, "xml")
        xml = _body(fetcher.get(xml_url), xml_url, "xml")
        if xml is None:
            info = xmlmeta.XmlInfo("absent")
        else:
            _check(sha256(xml), pin.xml if pin else None, None, f"{name}-{rev}.xml")
            info = xmlmeta.inspect(xml)
            if info.state == xmlmeta.REFUSED:
                xml = None  # hostile or unusual source: recorded as refused, not stored
    legend = licence.detect(text, info.ipr)
    meta = RevMeta(
        name=name,
        rev=rev,
        title=status.title,
        published=status.published(rev),
        authors=status.authors,
        txt_sha256=sha256(txt),
        txt_bytes=len(txt),
        encoding=encoding,
        xml_state=info.state,
        xml_sha256=sha256(xml) if xml is not None else "",
        xml_bytes=len(xml) if xml is not None else 0,
        restriction=legend.restriction,
        copyright_year=legend.year,
        ipr=legend.ipr,
        imported=(now or datetime.now(UTC)).replace(microsecond=0).isoformat(),
    )
    path = store.install(meta, txt, xml, found)
    return Report(
        name, rev, path, True, len(txt), meta.txt_sha256, info.state, meta.xml_sha256, pinned, status,
        fetcher.requests - started,
    )  # fmt: skip
