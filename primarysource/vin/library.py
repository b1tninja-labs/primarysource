"""Read, search and list imported GM VIN filings. Local files only; nothing here fetches.

A ref is `vin:gm-vin-2016§33`: the filing's id, `§`, and the 1-based PDF page. `¶n` is the nth line of that
page. Search goes through the core FTS5 index (`index.sqlite`, BM25, page titles weighted 4). Read and the
document list use the stored extraction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource import budget, cursor, index
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render
from primarysource.vin.identify import VIN_DOC, VIN_SECTION, part565
from primarysource.vin.importer import (
    EXTRACTED,
    IMPORT_COMMAND,
    INDEX_FILE,
    REBUILD_COMMAND,
    document_label,
    read_record,
)

PREFIX = re.compile(r"^vin:", re.IGNORECASE)
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)
SEARCH_WINDOW = 500


def grammar() -> RefGrammar:
    return RefGrammar(VIN_DOC, VIN_SECTION)


@dataclass(frozen=True, slots=True)
class _Page:
    id: str
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Loaded:
    doc: str
    label: str
    pages: tuple[_Page, ...]
    cite_part: str


def default_home() -> Path:
    return collection_home("vin")


def _not_imported(what: str, home: Path) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    return LibError(
        f"{what} is not imported (have: {have})",
        "vin_docs lists what is imported",
        f"put the PDF in {home}, then run: {IMPORT_COMMAND}",
    )


def parse_ref(text: str) -> Ref:
    """Parse a vin ref. The document id is `gm-vin-<year>`; the section is the PDF page."""
    body = PREFIX.sub("", text.strip(), count=1)
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not a vin ref: {text!r}", "vin refs are gm-vin-<year>[§page][¶n], e.g. gm-vin-2016§33")
    if ref.doc is None:
        raise LibError(f"not a vin ref: {text!r}", "start with the filing id, e.g. gm-vin-2016")
    return ref


def load(doc: str, home: Path | None = None) -> Loaded:
    home = home or default_home()
    documents = read_record(home)["documents"]
    entry = documents.get(doc)
    if not isinstance(entry, dict):
        raise _not_imported(doc, home)
    try:
        raw: Any = json.loads((home / EXTRACTED / f"{entry['key']}.json").read_text(encoding="utf-8"))
        pages = tuple(
            _Page(str(item["id"]), str(item["title"]), tuple(line for line in str(item["text"]).split("\n") if line))
            for item in raw["sections"]
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LibError(
            f"cannot read the import of {document_label(entry, doc)}: {exc}",
            "",
            f"re-import it: {IMPORT_COMMAND}",
        ) from exc
    first = "\n".join(pages[0].lines) if pages else ""
    return Loaded(doc, document_label(entry, doc), pages, part565(first))


def _cite_text(doc: Loaded, page: _Page | None, para: int | str | None) -> str:
    where = f", §{page.id} {page.title}" if page else ""
    if para:
        where += f" ¶{para}"
    filed = f", {doc.cite_part}" if doc.cite_part else ""
    return f"{doc.label}{filed}{where}"


def _find(doc: Loaded, section: str) -> _Page:
    for page in doc.pages:
        if page.id == section:
            return page
    raise LibError(f"no section {section!r}", "the section is the PDF page number, e.g. §33")


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, _Page | None, tuple[str, ...]]:
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the filing id, e.g. gm-vin-2016")
    doc = load(ref.doc, home)
    if ref.section is None:
        units: list[str] = []
        for page in doc.pages:
            units.append(f"§{page.id} {page.title}")
            units.extend(page.lines)
        return doc, None, tuple(units)
    page = _find(doc, ref.section)
    return doc, page, page.lines or (page.title,)


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at line boundaries within `max_tokens`. A `¶n` ref starts at line n."""
    ref = parse_ref(ref_text)
    doc, page, units = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that page has no text", "vin_docs lists the imported filings")
    first = cursor.first_unit(ref.para, len(units), "lines", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"vin:{doc.doc}" + (f"§{page.id}" if page else "")
    footer = {
        "cite": _cite_text(doc, page, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
    }
    return render(body, footer)


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    """Pages containing every query word (else any, flagged `relaxed`), best first by BM25: one line per hit,
    `<ref>  <page title>: <snippet>`."""
    home = home or default_home()
    documents = read_record(home)["documents"]
    if not documents:
        raise LibError(
            "no GM VIN filings are imported",
            "vin_docs lists what is imported",
            f"put the PDFs in {home}, then run: {IMPORT_COMMAND}",
        )
    if doc is not None:
        doc = PREFIX.sub("", doc.strip(), count=1)
        if doc not in documents:
            raise _not_imported(doc, home)
    try:
        conn = index.open_read(home / INDEX_FILE, rebuild_command=REBUILD_COMMAND)
    except LibError as exc:
        raise LibError(exc.message, "", REBUILD_COMMAND) from exc
    try:
        found = index.search(conn, query, ranking=RANKING, limit=SEARCH_WINDOW)
    finally:
        conn.close()
    hits = [hit for hit in found.hits if doc is None or hit.doc_id == doc]
    if not hits:
        return render("no matches", {})
    shown, nxt = cursor.window(hits, start, limit)
    lines = [f"vin:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    footer = {"next": nxt, "relaxed": "only some query words matched" if found.relaxed else ""}
    return render("\n".join(lines), footer)


def docs(home: Path | None = None) -> str:
    """What is imported, with each source file's state: present, changed since import, or missing."""
    home = home or default_home()
    record = read_record(home)["documents"]
    if not record:
        return render(f"nothing imported; put the GM VIN filings in {home} and run: {IMPORT_COMMAND}", {})
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
        pages = entry.get("pages")
        count = f"  {pages} pages" if pages else ""
        lines.append(f"vin:{doc}  {document_label(entry, doc)}{count}  ({state})")
    return render("\n".join(lines), {})
