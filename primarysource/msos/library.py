"""Read, outline, search and cite imported Open Specifications. Local files only; nothing here fetches.

A ref is `msos:ms-patch§2.1¶3`: the specification id (`ms-cab`, `ms-patch`, or `[MS-PATCH]`), `§` and a clause
as the PDF's bookmarks number it, and `¶n`, the nth sentence of that clause's span.
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
from primarysource.model import span_hash
from primarysource.msos.importer import EXTRACTED, IMPORT_COMMAND, INDEX_FILE, REBUILD_COMMAND, read_record
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = re.compile(r"^msos:", re.IGNORECASE)
DOC = r"ms-[a-z0-9]+(?:-[a-z0-9]+)*"
SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


def grammar() -> RefGrammar:
    return RefGrammar(DOC, SECTION)


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    designation: str
    title: str
    document: PdfDocument


def default_home() -> Path:
    return collection_home("msos")


def _not_imported(what: str, home: Path) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        "msos_docs lists what is imported",
        f"primarysource msos sync, then {IMPORT_COMMAND}",
    )


def parse_ref(text: str) -> Ref:
    body = PREFIX.sub("", text.strip(), count=1).replace("[", "").replace("]", "")
    doc, sep, rest = body.partition("§")
    body = doc.strip().lower() + sep + rest
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not an msos ref: {text!r}", "msos refs are ms-<name>[§clause][¶n], e.g. ms-patch§2")
    if ref.doc is None:
        raise LibError(f"not an msos ref: {text!r}", "start with the specification, e.g. ms-cab or ms-patch")
    return ref


def load(doc: str, home: Path | None = None) -> Loaded:
    home = home or default_home()
    entry = read_record(home)["documents"].get(doc)
    if not isinstance(entry, dict):
        raise _not_imported(doc, home)
    try:
        raw: Any = json.loads((home / EXTRACTED / f"{doc}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise LibError(
            f"cannot read the import of {entry.get('designation', doc)}: {exc}", "", f"re-import it: {IMPORT_COMMAND}"
        ) from exc
    document = PdfDocument.from_json(raw)
    return Loaded(
        doc, str(entry.get("designation") or doc), document.title or str(entry.get("designation") or doc), document
    )


def _cite(doc: Loaded, section: PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    title = doc.title
    if title.upper().startswith(doc.designation.upper()):
        title = title[len(doc.designation) :].lstrip(" -—:")
    return f"{doc.designation}{', ' + title if title else ''}{where}"


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, PdfSection | None, tuple[str, ...], str]:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the specification, e.g. ms-patch")
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
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "read its subsections, see msos_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"msos:{doc.doc}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(doc_id: str, start: int = 0, limit: int = 200, home: Path | None = None) -> str:
    doc = load(parse_ref(doc_id).doc or "", home)
    rows = [
        f"{'  ' * section.depth}{section.id} {section.title}  msos:{doc.doc}§{section.id}  (p. {section.page})"
        for section in doc.document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    head = f"{doc.designation}  [msos:{doc.doc}, {doc.document.pages} pages]"
    return render("\n".join([head, *shown]), {"next": nxt})


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    home = home or default_home()
    if not read_record(home)["documents"]:
        raise LibError(
            "no Open Specifications are imported", "msos_docs lists what is imported", "primarysource msos sync"
        )
    wanted = parse_ref(doc).doc if doc else None
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
    lines = [f"msos:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    footer = {"next": nxt, "relaxed": "only some query words matched" if found.relaxed else ""}
    return render("\n".join(lines), footer)


def cite(ref_text: str, home: Path | None = None) -> str:
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} sentences", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    footer = {
        "cite": _cite(doc, section, ref.para),
        "unit": "sentence",
        "span": span_hash("\n".join(units)),
        "warning": warning,
    }
    label = f"msos:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    home = home or default_home()
    record = read_record(home)["documents"]
    if not record:
        return render("nothing imported; run: primarysource msos sync", {})
    lines = [
        f"msos:{doc}  {entry.get('designation', doc)}  {entry.get('set', '')}  {entry.get('title', '')}"
        for doc, entry in sorted(record.items())
    ]
    return render("\n".join(lines), {})
