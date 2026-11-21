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
from primarysource.ecma.catalogue import Edition, same_text
from primarysource.ecma.catalogue import catalogue as ecma_catalogue
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iso import joint
from primarysource.iso.designation import DOC, parse, split_doc
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
from primarysource.standing import dated_family
from primarysource.standing import join as join_warning
from primarysource.standing import notes as standing_notes

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
    source: str = ""


def default_home() -> Path:
    return collection_home("iso")


def _dated(doc: str, home: Path | None) -> str:
    root = home or default_home()
    return dated_family(doc, read_record(root)["documents"], split_doc, "iso")


def _ecma_imported(edition: Edition) -> bool:
    path = collection_home("ecma") / "install.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    editions = loaded.get("editions") if isinstance(loaded, dict) else None
    return isinstance(editions, dict) and edition.key in editions


def _same_detail(editions: tuple[Edition, ...]) -> tuple[str, str, str]:
    """The statement, the next tool call, and the import command for editions Ecma states are the same text."""
    parts: list[str] = []
    hints: list[str] = []
    actions: list[str] = []
    for edition in editions:
        ref = f"ecma:{edition.number}@{edition.edition}"
        label = ", ".join(edition.identical)
        stated = f"Ecma states that {edition.designation} ({edition.edition_name}) is fully identical with {label}"
        if _ecma_imported(edition):
            parts.append(f"{stated}, and that text is imported as {ref}")
            hints.append(f"ecma_read {ref}")
        else:
            parts.append(stated)
            hints.append("ecma_docs lists the catalogue")
            actions.append(f"primarysource ecma import {edition.number}")
    return " ".join(parts), "; ".join(dict.fromkeys(hints)), "; ".join(actions)


def _same_error(what: str, editions: tuple[Edition, ...]) -> LibError:
    """A missing ISO standard whose identical text Ecma publishes under its own designation."""
    detail, hint, action = _same_detail(editions)
    return LibError(f"{what} is not imported. {detail}", hint, action)


def _twins(doc: str | None) -> tuple[Edition, ...]:
    if not doc or not re.fullmatch(DOC, doc):
        return ()
    number, year = split_doc(doc)
    return same_text(number, year)


def _asked(query: str) -> tuple[str, str | None] | None:
    """A search query that is only an ISO document (`2022`, `2022@1994`, `ISO/IEC 2022:1994`), else None."""
    text = PREFIX.sub("", query.strip(), count=1)
    try:
        return split_doc(text)
    except LibError:
        pass
    try:
        found = parse(text)
    except LibError:
        return None
    if found.supplement:
        return None
    return found.number, str(found.year)


def _same_line(query: str, *, require_year: bool = False) -> str:
    """The identical-edition line for a query that is only a document id.

    `require_year` keeps a bare number (`2022`) out of a result that already has hits: that query is a word
    search. A designation (`ISO/IEC 2022:1994`, `2022@1994`) is a request for the standard.
    """
    asked = _asked(query)
    if asked is None or (require_year and asked[1] is None):
        return ""
    lines: list[str] = []
    for edition in same_text(*asked):
        ref = f"ecma:{edition.number}@{edition.edition}"
        label = ", ".join(edition.identical)
        stated = f"Ecma states that {edition.designation} ({edition.edition_name}) is fully identical with {label}"
        if _ecma_imported(edition):
            lines.append(f"same text: {ref}  {stated}. ecma_read {ref}")
        else:
            lines.append(f"same text: {ref}  {stated}. primarysource ecma import {edition.number}")
    return "\n".join(lines)


def _docs_twins() -> str:
    lines: list[str] = []
    for edition in ecma_catalogue().editions:
        if not edition.identical:
            continue
        ref = f"ecma:{edition.number}@{edition.edition}"
        label = ", ".join(edition.identical)
        if _ecma_imported(edition):
            lines.append(f"same text  {ref}  {label}  (imported; ecma_read {ref})")
        else:
            lines.append(f"same text  {ref}  {label}  (not imported; primarysource ecma import {edition.number})")
    return "\n".join(lines)


def _not_imported(what: str, home: Path, doc: str | None = None) -> LibError:
    have = ", ".join(sorted(read_record(home)["documents"])) or "nothing"
    item = joint.lookup(doc) if doc else None
    present = joint.on_disk(item, home) if item is not None else None
    if item is not None and present is not None:
        return LibError(
            f"{what} is the free joint publication {item.reference}, already at {present}, and it is not imported",
            "iso_docs lists what is imported",
            f'{IMPORT_COMMAND} "{present}"',
        )
    twins = _twins(doc)
    if twins:
        return _same_error(what, twins)
    return LibError(
        f"{what} is not imported (have: {have})",
        "iso_docs lists what is imported",
        f"put the PDF in {home}, then run: {IMPORT_COMMAND}",
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


def _same_file(doc: str, home: Path, documents: dict[str, Any]) -> str | None:
    """An imported document whose source is the free-joint file `doc` names, when the cover year differs."""
    item = joint.lookup(doc)
    present = joint.on_disk(item, home) if item is not None else None
    if present is None:
        return None
    source = str(present)
    for key, entry in documents.items():
        if str(entry.get("source")) == source:
            return str(key)
    return None


def _is_free(doc: str, source: str, known: dict[str, joint.FreeJoint]) -> bool:
    return joint.lookup(doc, known) is not None or joint.by_name(Path(source).name, known) is not None


def resolve(token: str, home: Path) -> str:
    """The imported document a token names: exact when it carries `@year`, else the newest imported year of that
    number (the standard itself before an amendment). A free-joint year that the cover prints differently still
    resolves to the import of that file."""
    number, rest = split_doc(token)
    documents = read_record(home)["documents"]
    if rest is not None:
        doc = f"{number}@{rest}"
        if doc not in documents:
            alias = _same_file(doc, home, documents)
            if alias is None:
                raise _not_imported(f"ISO {doc}", home, doc)
            return alias
        return doc
    candidates: list[str] = [str(d) for d in documents if str(d).split("@", 1)[0] == number]
    if not candidates:
        raise _not_imported(f"ISO {number}", home, number)
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
    return Loaded(
        doc,
        str(entry["designation"]),
        document.title or str(entry["designation"]),
        document,
        str(entry.get("source", "")),
    )


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
    free = ", free joint publication" if _is_free(doc.doc, doc.source, joint.catalogue()) else ""
    return f"{doc.designation}{', ' + title if title else ''}{where}{free}"


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
        "warning": join_warning(warning, _dated(doc.doc, home)),
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
        twins = _twins(doc) if doc else ()
        if not twins:
            asked = _asked(query)
            twins = same_text(*asked) if asked else ()
        if twins:
            detail, hint, action = _same_detail(twins)
            raise LibError(f"no ISO standards are imported. {detail}", hint, action)
        raise LibError(
            "no ISO standards are imported",
            "iso_docs lists what is imported",
            f"put your PDFs in {home}, then run: {IMPORT_COMMAND}",
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
        line = _same_line(query) if wanted is None else ""
        return render("no matches" if not line else f"no matches\n{line}", {})
    shown, nxt = cursor.window(hits, start, limit)
    lines = [f"iso:{hit.doc_id}§{hit.section_id}  {hit.title}: {' '.join(hit.snippet.split())}" for hit in shown]
    line = _same_line(query, require_year=True) if wanted is None else ""
    if line:
        lines.append(line)
    footer = {
        "next": nxt,
        "relaxed": "only some query words matched" if found.relaxed else "",
        "warning": join_warning(*standing_notes((f"iso:{hit.doc_id}", _dated(hit.doc_id, home)) for hit in shown)),
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
    label = f"iso:{doc.doc}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    """What is imported, with each source file's state: present, changed since import, or missing."""
    home = home or default_home()
    record = read_record(home)["documents"]
    twins = _docs_twins()
    if not record:
        body = f"nothing imported; put your purchased ISO PDFs in {home} and run: {IMPORT_COMMAND}"
        return render(body if not twins else f"{body}\n{twins}", {})
    known = joint.catalogue()
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
        if _is_free(str(doc), str(source), known):
            state += ", free joint publication"
        lines.append(f"iso:{doc}  {entry['designation']}  {entry.get('title', '')}  ({state})")
    if twins:
        lines.append(twins)
    return render("\n".join(lines), {})
