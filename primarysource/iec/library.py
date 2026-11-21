"""Read, outline, search and cite the owner's imported IEC publications. Local files only; nothing here fetches.

A ref is `iec:60835-2-1@1990§1¶2`: the publication's number, `@` and its year (the newest imported year when
omitted), `§` and a clause as the PDF's bookmarks number it, and `¶n`, the nth sentence of that clause's span.
A printed designation works too: `IEC 60835-2-1:1990§1`. A commented version is `ca-01@2020+csv`. ISO and
ISO/IEC editions are the iso collection's.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource import budget, cursor, index
from primarysource.ecma._pdf import PdfDocument, PdfSection
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iec.designation import parse, split_doc
from primarysource.iec.importer import EXTRACTED, IMPORT_COMMAND, INDEX_FILE, REBUILD_COMMAND, read_record
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render
from primarysource.standing import dated_family
from primarysource.standing import join as join_warning
from primarysource.standing import notes as standing_notes

PREFIX = re.compile(r"^iec:", re.IGNORECASE)
_PRINTED = re.compile(r"^(?P<head>IEC[^§¶]*?)\s*(?P<rest>(?:§|¶).*)?$", re.IGNORECASE)
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


def grammar() -> RefGrammar:
    from primarysource.iec.designation import DOC, SECTION

    return RefGrammar(DOC, SECTION)


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    designation: str
    title: str
    document: PdfDocument


def default_home() -> Path:
    return collection_home("iec")


def _dated(doc: str, home: Path | None) -> str:
    root = home or default_home()
    return dated_family(doc, read_record(root)["documents"], split_doc, "iec")


def _not_imported(what: str, home: Path) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        "iec_docs lists what is imported",
        f"put the PDF in {home / 'pdfs'}, then run: {IMPORT_COMMAND}",
    )


def parse_ref(text: str) -> Ref:
    """Parse an iec ref, accepting the `iec:` prefix and a printed designation for the document."""
    body = PREFIX.sub("", text.strip(), count=1)
    printed = _PRINTED.match(body)
    if printed and printed["head"].strip():
        with suppress(LibError):
            body = parse(printed["head"]).doc + (printed["rest"] or "")
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(
            f"not an iec ref: {text!r}", "iec refs are <number>[@year][§clause][¶n], e.g. 60835-2-1@1990§1"
        )
    if ref.doc is None:
        raise LibError(f"not an iec ref: {text!r}", "start with the publication's number, e.g. 60835-2-1@1990")
    return ref


def resolve(token: str, home: Path) -> str:
    """The imported document a token names: exact when it carries `@year`, else the newest imported year."""
    number, rest = split_doc(token)
    documents = read_record(home)["documents"]
    if rest is not None:
        doc = f"{number}@{rest}"
        if doc not in documents:
            raise _not_imported(f"IEC {doc}", home)
        return doc
    candidates = [str(doc) for doc in documents if str(doc).split("@", 1)[0] == number]
    if not candidates:
        raise _not_imported(f"IEC {number}", home)
    return max(candidates)


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


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, PdfSection | None, tuple[str, ...], str]:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the publication's number")
    doc = load(ref.doc, home)
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return doc, None, tuple(units), ""
    position, warning = doc.document.find(ref.section)
    return doc, doc.document.sections[position], doc.document.span(position), warning


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at sentence boundaries within `max_tokens`."""
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "read its subsections, see iec_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"iec:{doc.doc}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite_text(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": join_warning(warning, _dated(doc.doc, home)),
    }
    return render(body, footer)


def outline(token: str, start: int = 0, limit: int = 200, home: Path | None = None) -> str:
    """A publication's bookmarked clauses, indented by depth, each with the ref that reads it."""
    doc = load(token, home)
    rows = [
        f"{'  ' * section.depth}{section.id} {section.title}  iec:{doc.doc}§{section.id}  (p. {section.page})"
        for section in doc.document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    head = f"{doc.designation} {_title(doc)}  [iec:{doc.doc}, {doc.document.pages} pages]"
    return render("\n".join([head, *shown]), {"next": nxt})


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    """Clauses containing every query word (else any, flagged `relaxed`), best first."""
    home = home or default_home()
    if not read_record(home)["documents"]:
        raise LibError(
            "no IEC publications are imported",
            "iec_docs lists what is imported",
            f"put your PDFs in {home / 'pdfs'}, then run: {IMPORT_COMMAND}",
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
    lines = [f"iec:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    footer = {
        "next": nxt,
        "relaxed": "only some query words matched" if found.relaxed else "",
        "warning": join_warning(*standing_notes((f"iec:{hit.doc_id}", _dated(hit.doc_id, home)) for hit in shown)),
    }
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
        "warning": join_warning(warning, _dated(doc.doc, home)),
    }
    label = f"iec:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    """What is imported, with each source file's state: present, changed since import, or missing."""
    home = home or default_home()
    record = read_record(home)["documents"]
    if not record:
        return render(f"nothing imported; put IEC PDFs in {home / 'pdfs'} and run: {IMPORT_COMMAND}", {})
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
        lines.append(f"iec:{doc}  {entry['designation']}  {entry.get('title', '')}  ({state})")
    return render("\n".join(lines), {})
