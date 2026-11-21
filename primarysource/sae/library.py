"""Read, outline, search and cite imported SAE documents. Local files only."""

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
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render
from primarysource.sae.designation import DOC, parse
from primarysource.sae.identify import SAE_SECTION
from primarysource.sae.importer import EXTRACTED, IMPORT_COMMAND, INDEX_FILE, REBUILD_COMMAND, read_record

PREFIX = re.compile(r"^sae:", re.IGNORECASE)
_PRINTED = re.compile(r"^(?P<head>SAE[^§¶]*?)\s*(?P<rest>(?:§|¶).*)?$", re.IGNORECASE)
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


def grammar() -> RefGrammar:
    return RefGrammar(DOC, SAE_SECTION)


def default_home() -> Path:
    return collection_home("sae")


def parse_ref(text: str) -> Ref:
    body = PREFIX.sub("", text.strip(), count=1)
    printed = _PRINTED.match(body)
    if printed:
        body = parse(printed["head"]).doc + (printed["rest"] or "")
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not an sae ref: {text!r}", "sae refs are j2534@2002[§clause][¶n]")
    if ref.doc is None:
        raise LibError(f"not an sae ref: {text!r}", "start with the document, e.g. j2534@2002")
    return ref


def resolve(token: str, home: Path) -> str:
    documents = read_record(home)["documents"]
    if "@" in token:
        if token not in documents:
            raise _missing(token, home)
        return token
    candidates = [str(doc) for doc in documents if str(doc).split("@", 1)[0] == token]
    if not candidates:
        raise _missing(token, home)
    return max(candidates)


def _missing(what: str, home: Path) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        "sae_docs lists what is imported",
        f"put the PDF where you keep research, then run: {IMPORT_COMMAND}",
    )


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    designation: str
    title: str
    document: PdfDocument


def load(token: str, home: Path | None = None) -> Loaded:
    home = home or default_home()
    doc = resolve(token, home)
    entry = read_record(home)["documents"][doc]
    try:
        raw: Any = json.loads((home / EXTRACTED / f"{entry['key']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise LibError(f"cannot read the import of {doc}: {exc}", "", IMPORT_COMMAND) from exc
    document = PdfDocument.from_json(raw)
    return Loaded(doc, str(entry["designation"]), document.title or str(entry["designation"]), document)


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, PdfSection | None, tuple[str, ...]]:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with j2534@2002")
    doc = load(ref.doc, home)
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return doc, None, tuple(units)
    position, _warning = doc.document.find(ref.section)
    return doc, doc.document.sections[position], doc.document.span(position)


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    ref = parse_ref(ref_text)
    doc, section, units = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "see sae_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    scope = f"sae:{doc.doc}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash("\n".join(chosen.units)),
        "next": cursor.read_next(scope, chosen),
    }
    return render("\n".join(chosen.units), footer)


def outline(token: str, start: int = 0, limit: int = 200, home: Path | None = None) -> str:
    doc = load(token, home)
    rows = [
        f"{'  ' * section.depth}{section.id} {section.title}  sae:{doc.doc}§{section.id}  (p. {section.page})"
        for section in doc.document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    head = f"{doc.designation} {doc.title}  [sae:{doc.doc}, {doc.document.pages} pages]"
    return render("\n".join([head, *shown]), {"next": nxt})


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    home = home or default_home()
    if not read_record(home)["documents"]:
        raise LibError("no SAE documents are imported", "sae_docs lists what is imported", IMPORT_COMMAND)
    wanted = resolve(doc, home) if doc else None
    conn = index.open_read(home / INDEX_FILE, rebuild_command=REBUILD_COMMAND)
    try:
        found = index.search(conn, query, ranking=RANKING, limit=SEARCH_WINDOW)
    finally:
        conn.close()
    hits = [hit for hit in found.hits if wanted is None or hit.doc_id == wanted]
    if not hits:
        return render("no matches", {})
    shown, nxt = cursor.window(hits, start, limit)
    lines = [f"sae:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    footer = {"next": nxt, "relaxed": "only some query words matched" if found.relaxed else ""}
    return render("\n".join(lines), footer)


def cite(ref_text: str, home: Path | None = None) -> str:
    ref = parse_ref(ref_text)
    doc, section, units = _select(ref, home)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} sentences", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    label = f"sae:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    footer = {"cite": _cite(doc, section, ref.para), "unit": "sentence", "span": span_hash("\n".join(units))}
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    home = home or default_home()
    record = read_record(home)["documents"]
    if not record:
        return render(f'nothing imported; run: {IMPORT_COMMAND} FILE --designation "SAE J2534:2002"', {})
    lines = [
        f"{entry.get('designation') or entry.get('label') or doc}  sae:{doc}  {entry.get('source', '')}"
        for doc, entry in sorted(record.items())
    ]
    return render("\n".join(lines), {})


def _cite(doc: Loaded, section: PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    return f"{doc.designation}{where}"
