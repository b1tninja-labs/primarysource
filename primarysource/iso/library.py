"""Read, outline, search and cite the owner's imported ISO standards. Local files only; nothing here fetches.

A ref is `iso:9899@2024§6.5.2¶3`: the standard's number, `@` and its year (the newest imported year when omitted),
`§` and a clause as the PDF's bookmarks number it (`6.5.2`, `A` for Annex A, `A.1`) or the slug of an unnumbered
bookmark (`bibliography`), and `¶n`, the nth sentence of that clause's span. The span is the clause's own text,
then each subsection as a `§6.5.2.1 Title` line followed by its text. A printed designation works too:
`ISO/IEC 9899:2024§6.5.2`. A ref with no section is the whole standard.

Search goes through the core FTS5 index (`index.sqlite`, BM25, heading matches weighted 4); read, outline and cite
read the stored extraction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource import budget, cursor, index
from primarysource.ecma._pdf import PdfDocument, PdfSection
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iso.designation import parse, split_doc
from primarysource.iso.importer import (
    EXTRACTED,
    IMPORT_COMMAND,
    INDEX_FILE,
    REBUILD_COMMAND,
    read_record,
)
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = re.compile(r"^iso:", re.IGNORECASE)
_PRINTED = re.compile(r"^(?P<head>ISO[^§¶]*?)\s*(?P<rest>(?:§|¶).*)?$", re.IGNORECASE)
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


def grammar() -> RefGrammar:
    from primarysource.iso import ISO_DOC, ISO_SECTION

    return RefGrammar(ISO_DOC, ISO_SECTION)


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    designation: str
    title: str
    document: PdfDocument


def default_home() -> Path:
    return collection_home("iso")


def _not_imported(what: str, home: Path) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        "iso_docs lists what is imported",
        f"put the PDF in {home / 'purchased'}, then run: {IMPORT_COMMAND}",
    )


def parse_ref(text: str) -> Ref:
    """Parse an iso ref, accepting the `iso:` prefix and a printed designation for the document."""
    body = PREFIX.sub("", text.strip(), count=1)
    printed = _PRINTED.match(body)
    if printed:
        body = parse(printed["head"]).doc + (printed["rest"] or "")
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not an iso ref: {text!r}", "iso refs are <number>[@year][§clause][¶n], e.g. 9899@2024§6.5.2")
    if ref.doc is None:
        raise LibError(f"not an iso ref: {text!r}", "start with the standard's number, e.g. 9899@2024")
    return ref


def resolve(token: str, home: Path) -> str:
    """The imported document a token names: exact when it carries `@year`, else the newest imported year of that
    number (the standard itself before an amendment)."""
    number, rest = split_doc(token)
    documents = read_record(home)["documents"]
    if rest is not None:
        doc = f"{number}@{rest}"
        if doc not in documents:
            raise _not_imported(f"ISO {doc}", home)
        return doc
    candidates: list[str] = [str(d) for d in documents if str(d).split("@", 1)[0] == number]
    if not candidates:
        raise _not_imported(f"ISO {number}", home)
    return max(candidates, key=lambda d: ("+" not in d, d.split("@", 1)[1]))


def load(token: str, home: Path | None = None) -> Loaded:
    home = home or default_home()
    doc = resolve(token, home)
    entry = read_record(home)["documents"][doc]
    try:
        raw: Any = json.loads((home / EXTRACTED / f"{entry['key']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise LibError(
            f"cannot read the import of {entry.get('designation', doc)}: {exc}", "", f"re-import it: {IMPORT_COMMAND}"
        ) from exc
    document = PdfDocument.from_json(raw)
    return Loaded(doc, str(entry["designation"]), document.title or str(entry["designation"]), document)


def _title(doc: Loaded) -> str:
    """The PDF title without the designation it often starts with."""
    title = doc.title
    if title.upper().startswith(doc.designation.upper()):
        title = title[len(doc.designation) :].lstrip(" -—:")
    return title


def _cite_text(doc: Loaded, section: PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    title = _title(doc)
    return f"{doc.designation}{', ' + title if title else ''}{where}"


def _doc(ref: Ref) -> str:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the standard's number")
    return ref.doc


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, PdfSection | None, tuple[str, ...], str]:
    doc = load(_doc(ref), home)
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return doc, None, tuple(units), ""
    position, warning = doc.document.find(ref.section)
    return doc, doc.document.sections[position], doc.document.span(position), warning


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at sentence boundaries within `max_tokens`. A `¶n` ref starts at sentence n and runs to
    the end of its scope; the `next:` footer is the ref that reads the next page."""
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "read its subsections, see iso_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"iso:{doc.doc}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite_text(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(token: str, start: int = 0, limit: int = 200, home: Path | None = None) -> str:
    """A standard's bookmarked clauses, indented by depth, each with the ref that reads it and its PDF page."""
    doc = load(token, home)
    rows = [
        f"{'  ' * section.depth}{section.id} {section.title}  iso:{doc.doc}§{section.id}  (p. {section.page})"
        for section in doc.document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    head = f"{doc.designation} {_title(doc)}  [iso:{doc.doc}, {doc.document.pages} pages]"
    return render("\n".join([head, *shown]), {"next": nxt})


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    """Clauses containing every query word (else any, flagged `relaxed`), best first by BM25: one line per hit,
    `<ref>  <clause title>: <snippet>`."""
    home = home or default_home()
    if not read_record(home)["documents"]:
        raise LibError(
            "no ISO standards are imported",
            "iso_docs lists what is imported",
            f"put your PDFs in {home / 'purchased'}, then run: {IMPORT_COMMAND}",
        )
    wanted = resolve(doc, home) if doc else None
    try:
        conn = index.open_read(home / INDEX_FILE, rebuild_command=REBUILD_COMMAND)
    except LibError as exc:
        raise LibError(exc.message, "", REBUILD_COMMAND) from exc
    try:
        found = index.search(conn, query, ranking=RANKING, limit=SEARCH_WINDOW)
    finally:
        conn.close()
    hits = [hit for hit in found.hits if wanted is None or hit.doc_id == wanted]
    if not hits:
        return render("no matches", {})
    shown, nxt = cursor.window(hits, start, limit)
    lines = [f"iso:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    footer = {"next": nxt, "relaxed": "only some query words matched" if found.relaxed else ""}
    return render("\n".join(lines), footer)


def cite(ref_text: str, home: Path | None = None) -> str:
    """The citation string for a ref, with the span hash of the exact text cited."""
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} sentences", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    footer = {
        "cite": _cite_text(doc, section, ref.para),
        "unit": "sentence",
        "span": span_hash("\n".join(units)),
        "warning": warning,
    }
    label = f"iso:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    """What is imported, with each source file's state: present, changed since import, or missing."""
    home = home or default_home()
    record = read_record(home)["documents"]
    if not record:
        return render(
            f"nothing imported; put your purchased ISO PDFs in {home / 'purchased'} and run: {IMPORT_COMMAND}", {}
        )
    lines = []
    for doc, entry in sorted(record.items()):
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
        lines.append(f"iso:{doc}  {entry['designation']}  {entry.get('title', '')}  ({state})")
    return render("\n".join(lines), {})
