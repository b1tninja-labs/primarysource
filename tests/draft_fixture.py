"""Synthesised Internet-Drafts and a fake IETF for the draft collection's tests.

Everything here is invented: the prose is about a protocol that does not exist, the names are not real drafts,
and the layout is the xml2rfc text layout (table of contents with dot leaders, `[Page N]` footers, form feeds,
a running header). Nothing is copied from any real draft.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from primarysource.draft.net import Response

NAME = "draft-example-frob-proto"
SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "1",
        "Introduction",
        [
            "The Frobnicator Control Protocol moves invented gaskets between invented flanges.",
            "A second paragraph says that every sprocket MUST be acknowledged by a flange before\n"
            "the gasket is released, and that a flange SHOULD log the exchange.",
        ],
    ),
    ("2", "Protocol Overview", ["The overview has no text of its own beyond this sentence about gaskets."]),
    (
        "2.1",
        "Messages",
        [
            "Messages are carried in frames. A frame holds one sprocket and zero or more gaskets, and the receiver\n"
            "discards a frame it cannot parse.",
            "     +--------+--------+\n     | Sprock | Gasket |\n     +--------+--------+",
            "The third paragraph of the messages section mentions the word flange once.",
        ],
    ),
    ("2.2", "Timers", ["A retransmission timer runs for thirty invented seconds."]),
    ("3", "Security Considerations", ["Gaskets are not secret. Flanges authenticate nobody."]),
    ("4", "IANA Considerations", ["This document asks for nothing."]),
    ("5", "References", []),
    ("5.1", "Normative References", ['[FLANGE]  Nobody, "The Flange Specification", 1999.']),
    ("Appendix A", "Worked Example", ["Appendix text about a worked example with a sprocket."]),
]


def _wrap(text: str) -> list[str]:
    out: list[str] = []
    for chunk in text.split("\n"):
        out.append(chunk if chunk.startswith("     ") else "   " + chunk)
    return out


def _toc(label: str, title: str, page: int) -> str:
    depth = label.count(".") if not label.startswith("Appendix") else 0
    shown = (label + ".") if not label.startswith("Appendix") else label + "."
    head = "   " + "  " * depth + f"{shown}  {title} "
    dots = ". " * ((72 - len(head)) // 2)
    return f"{head}{dots}".ljust(72) + f"{page:>3}"


def _toc_plain(title: str, page: int) -> str:
    head = f"   {title} "
    return f"{head}{'. ' * ((72 - len(head)) // 2)}".ljust(72) + f"{page:>3}"


def build_txt(
    name: str = NAME,
    rev: str = "03",
    title: str = "Frobnicator Control Protocol",
    year: int = 2026,
    legend: str = "",
    pages: bool = True,
    sections: list[tuple[str, str, list[str]]] | None = None,
) -> str:
    """An xml2rfc-layout draft with a table of contents, page furniture mid-paragraph, an appendix, unnumbered
    sections, and (when `legend` is set) a licence legend in the copyright notice."""
    secs = SECTIONS if sections is None else sections
    lines = [
        "",
        "",
        "",
        "Network Working Group                                         A. Example",
        "Internet-Draft                                             Example Corp.",
        "Intended status: Standards Track                        November 3, 2026",
        "Expires: May 7, 2027",
        "",
        "",
        f"                    {title}",
        f"                    {name}-{rev}",
        "",
        "Abstract",
        "",
        "   This invented document specifies the Frobnicator Control Protocol for tests.",
        "",
        "Status of This Memo",
        "",
        "   This is an invented status paragraph. It is not the boilerplate of any real draft.",
        "",
        "Copyright Notice",
        "",
        f"   Copyright (c) {year} IETF Trust and the persons identified as the",
        "   document authors.  All rights reserved.",
        "",
    ]
    if legend:
        lines += [f"   {part}" for part in legend.split("\n")] + [""]
    lines += ["Table of Contents", ""]
    for n, (label, ttl, _paras) in enumerate(secs):
        lines.append(_toc(label, ttl, 2 + n // 3))
    lines.append(_toc_plain("Author's Address", 9))
    lines.append("")
    for label, ttl, paras in secs:
        lines.append(f"{label}.  {ttl}" if not label.startswith("Appendix") else f"{label}.  {ttl}")
        lines.append("")
        for para in paras:
            lines += _wrap(para) + [""]
    lines += ["Author's Address", "", "   A. Example", "   Example Corp.", ""]
    if pages:
        lines = _paginate(lines, name, rev, 42)
    return "\n".join(lines) + "\n"


def _paginate(lines: list[str], name: str, rev: str, per_page: int) -> list[str]:
    """Insert a footer, a form feed and a running header every `per_page` lines, even inside a paragraph."""
    out: list[str] = []
    page = 1
    for n, line in enumerate(lines, start=1):
        out.append(line)
        if n % per_page == 0 and n < len(lines):
            footer = f"Example                 Expires May 7, 2027                [Page {page}]"
            header = "Internet-Draft        Frobnicator Control Protocol          November 2026"
            out += ["", footer, "\f", header, ""]
            page += 1
    return out


def v2_xml(name: str = NAME, rev: str = "03", ipr: str = "trust200902") -> bytes:
    """A submitted-source XML in the xml2rfc v2 shape: an external DTD reference, no `version` attribute, and an
    entity (`&nbsp;`) that only the DTD defines, which is why the whole file is never parsed."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE rfc SYSTEM "rfc2629.dtd">\n'
        f'<rfc category="std" docName="{name}-{rev}" ipr="{ipr}" submissionType="IETF">\n'
        "<front><title>Frobnicator Control Protocol</title></front>\n"
        '<middle><section title="Introduction"><t>Gaskets&nbsp;and flanges.</t></section></middle>\n</rfc>\n'
    ).encode()


def v3_xml(name: str = NAME, rev: str = "03") -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<rfc version="3" docName="{name}-{rev}" ipr="trust200902" '
        'category="info" submissionType="independent"><front><title>T</title></front><middle/></rfc>\n'
    ).encode()


HOSTILE_XML = (
    b'<?xml version="1.0"?>\n<!DOCTYPE rfc [\n<!ENTITY a "aaaaaaaaaa">\n<!ENTITY b "&a;&a;&a;&a;&a;&a;">\n]>\n'
    b'<rfc docName="x-00">&b;</rfc>\n'
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class DraftSpec:
    """What the fake IETF knows about one draft."""

    name: str = NAME
    state: str = "Active"
    revs: tuple[str, ...] = ("00", "01", "02", "03")
    expires: str = "2027-05-07 12:00:00"
    replaced_by: tuple[str, ...] = ()
    became_rfc: int | None = None
    txt: dict[str, bytes] = field(default_factory=dict)
    xml: dict[str, bytes] = field(default_factory=dict)
    title: str = "Frobnicator Control Protocol"
    authors: tuple[str, ...] = ("Alice Example", "Bob Sample")

    def text_for(self, rev: str) -> bytes:
        return self.txt.get(rev) or build_txt(self.name, rev, self.title).encode()


class FakeIetf:
    """A transport that answers like the datatracker and the archive for the drafts it is given, records every
    URL with a counter, and can be told to misbehave once per URL."""

    def __init__(self, *specs: DraftSpec) -> None:
        self.specs = {s.name: s for s in specs}
        self.calls: list[str] = []
        self.overrides: dict[str, list[Response]] = {}

    def __call__(self, url: str) -> Response:
        self.calls.append(url)
        queued = self.overrides.get(url)
        if queued:
            return queued.pop(0)
        return self._answer(url)

    def _answer(self, url: str) -> Response:
        prefix = "https://datatracker.ietf.org/doc/"
        if url.startswith(prefix) and url.endswith("/doc.json"):
            spec = self.specs.get(url[len(prefix) : -len("/doc.json")])
            if spec is None:
                return Response(404, b"", "text/html")
            return Response(200, json.dumps(self._doc(spec)).encode(), "application/json")
        if "relateddocument" in url:
            return Response(200, json.dumps(self._related(url)).encode(), "application/json")
        archive = "https://www.ietf.org/archive/id/"
        if url.startswith(archive):
            stem, _, suffix = url[len(archive) :].rpartition(".")
            name, rev = stem.rsplit("-", 1)
            spec = self.specs.get(name)
            if spec is None or rev not in spec.revs:
                return Response(404, b"<html>not found</html>", "text/html")
            if suffix == "txt":
                return Response(200, spec.text_for(rev), "text/plain; charset=utf-8")
            if suffix == "xml" and rev in spec.xml:
                return Response(200, spec.xml[rev], "text/xml; charset=utf-8")
            return Response(404, b"<html>not found</html>", "text/html; charset=utf-8")
        return Response(404, b"", "")

    @staticmethod
    def _doc(spec: DraftSpec) -> dict[str, object]:
        return {
            "name": spec.name,
            "rev": spec.revs[-1],
            "pages": 9,
            "title": spec.title,
            "state": spec.state,
            "expires": spec.expires,
            "group": {"name": "Example WG", "acronym": "exwg"},
            "stream": "IETF",
            "authors": [{"name": a, "email": f"{a.split()[0].lower()}@example.invalid"} for a in spec.authors],
            "rev_history": [
                {"name": spec.name, "rev": r, "published": f"2026-0{1 + int(r)}-03T10:00:00+00:00", "pages": 9}
                for r in spec.revs
            ],
        }

    def _related(self, url: str) -> dict[str, object]:
        objects: list[dict[str, str]] = []
        for spec in self.specs.values():
            if f"target__name={spec.name}&" in url and "replaces" in url:
                objects += [
                    {"source": f"/api/v1/doc/document/{r}/", "target": f"/api/v1/doc/document/{spec.name}/"}
                    for r in spec.replaced_by
                ]
            if f"source__name={spec.name}&" in url and "became_rfc" in url and spec.became_rfc:
                objects.append(
                    {
                        "source": f"/api/v1/doc/document/{spec.name}/",
                        "target": f"/api/v1/doc/document/rfc{spec.became_rfc}/",
                    }
                )
        return {"meta": {"total_count": len(objects)}, "objects": objects}


class Clock:
    """A clock and a sleep that advance together, so the importer's one-request-a-second spacing can be checked
    without waiting: `sleeps` records what was asked for, `stamps` when each request was made."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def timed(transport: Callable[[str], Response], clock: Clock, stamps: list[float]) -> Callable[[str], Response]:
    """Wrap a transport so each call is stamped with the fake clock and takes 0.1 fake seconds."""

    def call(url: str) -> Response:
        stamps.append(clock.now)
        clock.now += 0.1
        return transport(url)

    return call
