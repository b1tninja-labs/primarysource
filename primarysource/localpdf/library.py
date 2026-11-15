"""Read, outline, search and cite a local-PDF collection's imported documents. Local files only; nothing fetches.

A ref is `<doc>[§section][¶n]` (`gm:17OBDG01-hybrid§p12¶3`, `can:bosch-2.0§2.1`): `section` is as the extraction
numbers it (a bookmarked clause, or `p<page>` for a table PDF cut by page) and `¶n` the nth unit of the section's
span, which is the section's own text and then each subsection as a `§id Title` line with its text. A ref with no
section is the whole document. Search goes through the core FTS5 index; read, outline and cite read the stored
extraction.

Every function passes the gate first (`terms.require_served`): the owner's variable must say yes and a terms
acknowledgement must be recorded for each document answered from.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource import budget, cursor, index, terms
from primarysource.ecma._pdf import PdfDocument, PdfSection
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.localpdf.refs import LocalRefs
from primarysource.localpdf.spec import LocalPdfSpec
from primarysource.localpdf.store import EXTRACTED, INDEX_FILE, read_record
from primarysource.model import span_hash
from primarysource.refs import Ref
from primarysource.render import render

RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    label: str
    title: str
    document: PdfDocument


def default_home(spec: LocalPdfSpec) -> Path:
    return collection_home(spec.name)


def _gate(
    spec: LocalPdfSpec, home: Path, what: str, docs: list[str] | None, environ: Mapping[str, str] | None
) -> dict[str, Any]:
    """Pass the gate for `docs` (None: every imported document) and return the install record."""
    terms.require_accepted(spec.terms, home, what, environ)
    record = read_record(home)
    wanted = list(record["documents"]) if docs is None else docs
    terms.require_served(spec.terms, record, wanted, home, what, spec.import_command, environ)
    return record


def _not_imported(spec: LocalPdfSpec, what: str, home: Path, record: dict[str, Any]) -> LibError:
    have = ", ".join(sorted(record["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        f"{spec.prefix}docs lists what is imported",
        f"put the PDF in {home}, then run: {spec.import_command}",
    )


def resolve(spec: LocalPdfSpec, token: str, home: Path, record: dict[str, Any]) -> str:
    """The imported document `token` names: exactly, else ignoring case when that is unambiguous."""
    documents = record["documents"]
    if token in documents:
        return token
    folded = [d for d in documents if str(d).casefold() == token.casefold()]
    if len(folded) == 1:
        return str(folded[0])
    raise _not_imported(spec, f"{spec.name}:{token}", home, record)


def load(
    spec: LocalPdfSpec, token: str, home: Path | None = None, environ: Mapping[str, str] | None = None
) -> Loaded:
    home = home or default_home(spec)
    terms.require_accepted(spec.terms, home, f"reading {spec.name}:{token}", environ)
    record = read_record(home)
    doc = resolve(spec, token, home, record)
    terms.require_served(spec.terms, record, [doc], home, f"reading {spec.name}:{doc}", spec.import_command, environ)
    entry = record["documents"][doc]
    try:
        raw: Any = json.loads((home / EXTRACTED / f"{entry['key']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise LibError(
            f"cannot read the import of {entry.get('label', doc)}: {exc}", "", f"re-import it: {spec.import_command}"
        ) from exc
    document = PdfDocument.from_json(raw)
    return Loaded(doc, str(entry["label"]), str(entry.get("title") or document.title), document)


def _cite_text(doc: Loaded, section: PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    title = "" if doc.title.startswith(doc.label) else doc.title
    return f"{doc.label}{', ' + title if title else ''}{where}"


def _doc(ref: Ref) -> str:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the document id")
    return ref.doc


def _select(
    spec: LocalPdfSpec, ref: Ref, home: Path | None, environ: Mapping[str, str] | None
) -> tuple[Loaded, PdfSection | None, tuple[str, ...], str]:
    doc = load(spec, _doc(ref), home, environ)
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return doc, None, tuple(units), ""
    position, warning = doc.document.find(ref.section)
    return doc, doc.document.sections[position], doc.document.span(position), warning


def read(
    spec: LocalPdfSpec,
    ref_text: str,
    max_tokens: int = 2000,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """The text of a ref, cut at unit boundaries within `max_tokens`. A `¶n` ref starts at unit n and runs to the
    end of its scope; the `next:` footer is the ref that reads the next page."""
    ref = LocalRefs(spec).parse(ref_text)
    doc, section, units, warning = _select(spec, ref, home, environ)
    if not units:
        raise LibError(
            f"{ref_text}: that section has no text of its own", f"read its subsections, see {spec.prefix}outline"
        )
    first = cursor.first_unit(ref.para, len(units), f"{spec.unit.value}s", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"{spec.name}:{doc.doc}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite_text(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": spec.unit.value,
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(
    spec: LocalPdfSpec,
    token: str,
    start: int = 0,
    limit: int = 200,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """A document's sections, indented by depth, each with the ref that reads it and its PDF page."""
    doc = load(spec, token, home, environ)
    rows = [
        f"{'  ' * section.depth}{section.id} {section.title}  {spec.name}:{doc.doc}§{section.id}  (p. {section.page})"
        for section in doc.document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    head = f"{doc.label} {doc.title}  [{spec.name}:{doc.doc}, {doc.document.pages} pages]"
    return render("\n".join([head, *shown]), {"next": nxt})


def search(
    spec: LocalPdfSpec,
    query: str,
    doc: str | None = None,
    limit: int = 10,
    start: int = 0,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Sections containing every query word (else any, flagged `relaxed`), best first by BM25: one line per hit,
    `<ref>  <section title>: <snippet>`."""
    home = home or default_home(spec)
    terms.require_accepted(spec.terms, home, f"a {spec.name} search", environ)
    record = read_record(home)
    if not record["documents"]:
        raise LibError(
            f"no {spec.title} documents are imported",
            f"{spec.prefix}docs lists what is imported",
            f"put your PDFs in {home}, then run: {spec.import_command}",
        )
    terms.require_served(
        spec.terms, record, list(record["documents"]), home, f"a {spec.name} search", spec.import_command, environ
    )
    wanted = resolve(spec, doc, home, record) if doc else None
    try:
        conn = index.open_read(home / INDEX_FILE, rebuild_command=spec.rebuild_command)
    except LibError as exc:
        raise LibError(exc.message, "", spec.rebuild_command) from exc
    try:
        found = index.search(conn, query, ranking=RANKING, limit=SEARCH_WINDOW)
    finally:
        conn.close()
    hits = [hit for hit in found.hits if wanted is None or hit.doc_id == wanted]
    if not hits:
        return render("no matches", {})
    shown, nxt = cursor.window(hits, start, limit)
    lines = [
        f"{spec.name}:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown
    ]
    footer = {"next": nxt, "relaxed": "only some query words matched" if found.relaxed else ""}
    return render("\n".join(lines), footer)


def cite(
    spec: LocalPdfSpec, ref_text: str, home: Path | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """The citation string for a ref, with the span hash of the exact text cited."""
    ref = LocalRefs(spec).parse(ref_text)
    doc, section, units, warning = _select(spec, ref, home, environ)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} {spec.unit.value}s", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    footer = {
        "cite": _cite_text(doc, section, ref.para),
        "unit": spec.unit.value,
        "span": span_hash("\n".join(units)),
        "warning": warning,
    }
    label = f"{spec.name}:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(label, footer)


def docs(spec: LocalPdfSpec, home: Path | None = None, environ: Mapping[str, str] | None = None) -> str:
    """What is imported, with each source file's state (present, changed since import, or missing) and when the
    owner's terms acknowledgement was first recorded for it."""
    home = home or default_home(spec)
    record = _gate(spec, home, f"listing the {spec.name} documents", None, environ)
    entries = record["documents"]
    if not entries:
        return render(f"nothing imported; put your PDFs in {home} and run: {spec.import_command}", {})
    acknowledged = terms.recorded(record)
    lines = []
    for doc, entry in sorted(entries.items()):
        source = Path(str(entry.get("source", "")))
        try:
            stat = source.stat()
            state = (
                "source unchanged"
                if stat.st_size == entry.get("size") and stat.st_mtime_ns == entry.get("mtime_ns")
                else "source changed since import"
            )
        except OSError:
            state = "source file missing"
        lines.append(
            f"{spec.name}:{doc}  {entry['label']}  {entry.get('title', '')}  "
            f"({state}; terms acknowledged {acknowledged[doc]})"
        )
    return render("\n".join(lines), {})
