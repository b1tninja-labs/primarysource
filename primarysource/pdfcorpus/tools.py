"""The five tools as plain functions returning `render()` text. ``ToolError`` marks a caller mistake.

Every error is a `LibError`: the message says what is wrong, `hint` names the tool call that helps next (with the
collection's prefix, `nist_outline('sp800-73pt2-5')`), and `action` the fetch or index command when a human must
act. A search that matches nothing is text saying so, not an error.

Cursors (PLAN.md §5.11): a read stops at its token budget and its `next:` is a ref, `<doc_id>:<first>-<last>`, that
`read` takes back as its `doc`; search and outline are lists whose `next:` is `start=<n>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource import budget, index
from primarysource.errors import LibError
from primarysource.pdfcorpus import fts
from primarysource.pdfcorpus.corpus import Corpus
from primarysource.pdfcorpus.models import Document, Section
from primarysource.refs import RefGrammar
from primarysource.render import next_start, render
from primarysource.standing import join as join_warning
from primarysource.standing import notes as standing_notes

# Document ids are file-safe slugs (`sp800-73pt2-5`, `sp800-53r5-oscal`), matched without regard to case.
# Section ids are dotted numbers, appendix letters and control ids (`3.2.4`, `A.1`, `AC-2(1)`).
GRAMMAR = RefGrammar(r"[A-Za-z0-9][A-Za-z0-9._-]*", r"[0-9A-Za-z][0-9A-Za-z.()_-]*")

REF_FORMS = "use <doc_id>§<section> or <doc_id>:<first>-<last>"
READ_TOKENS = 2000
OUTLINE_ROWS = 200


class ToolError(LibError):
    """A bad argument or unknown reference; `hint` says what to call instead."""


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def resolve_doc(corpus: Corpus, doc: str) -> Document:
    """Find a document by ``doc_id`` or by ``number`` (case/space-insensitive).

    Failing that, a bare name with no revision resolves through the corpus's defaults (NIST: "NIST SP 800-53"
    -> the current final revision), when the collection supplies them. An explicit id or number always wins.
    """
    key = _norm(doc)
    for d in corpus.documents:
        if _norm(d.doc_id) == key or _norm(d.number) == key:
            return d
    if corpus.defaults:
        wanted = corpus.defaults.get(corpus.alias(key) if corpus.alias else key)
        if wanted is not None:
            for d in corpus.documents:
                if d.doc_id == wanted:
                    return d
    known = ", ".join(d.doc_id for d in corpus.documents) or "none"
    raise ToolError(f"unknown document {doc!r} (known doc_ids: {known})", f"{corpus.tool('search')}('<words>')")


def resolve_section(corpus: Corpus, document: Document, section: str) -> Section:
    sid = section.strip().lstrip("§").strip()
    for s in document.sections:
        if s.id == sid:
            return s
    raise ToolError(f"{document.doc_id} has no section {sid!r}", f"{corpus.tool('outline')}({document.doc_id!r})")


def parse_lines(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-:]\s*(\d+))?\s*", spec)
    if not m:
        raise ToolError(f"cannot parse lines={spec!r}", "give 'START-END', e.g. lines='120-160'")
    start = int(m.group(1))
    return start, int(m.group(2) or start)


@dataclass(frozen=True, slots=True)
class Target:
    """What a read or cite names: a document and a section, a line range, or neither."""

    document: Document
    section: Section | None = None
    lines: tuple[int, int] | None = None


def resolve(corpus: Corpus, doc: str, section: str | None = None, lines: str | None = None) -> Target:
    """`doc` is a doc_id, a number, or a ref: `<doc_id>§<section>` or `<doc_id>:<first>-<last>` (a read's `next:`).

    A ref's section or range and an explicit `section`/`lines` argument may not both be given.
    """
    if section is not None and lines is not None:
        raise ToolError("give one of section or lines, not both", "")
    ref = None
    if "§" in doc or "::" in doc or ":" in doc:
        ref = GRAMMAR.parse(doc)
        if ref.para is not None or ref.anchor is not None:
            raise ToolError(f"{doc!r}: this collection has no ¶ or # refs", REF_FORMS)
        if ref.doc is None:
            raise ToolError(f"{doc!r} names no document", REF_FORMS)
        if section is not None or lines is not None:
            raise ToolError(f"{doc!r} already names a section or lines; drop the section/lines argument", "")
    document = resolve_doc(corpus, ref.doc if ref is not None and ref.doc else doc)
    if ref is not None and ref.section is not None:
        section = ref.section
    if section is not None:
        return Target(document, section=resolve_section(corpus, document, section))
    span = ref.lines if ref is not None else (parse_lines(lines) if lines is not None else None)
    return Target(document, lines=span)


def _warning(corpus: Corpus, document: Document) -> str:
    """Status that is not final, and a later document when the collection recorded one."""
    status = f"status is {document.status!r}, not 'final'" if document.status.lower() != "final" else ""
    later = corpus.standing(document, corpus.defaults) if corpus.standing is not None else ""
    return join_warning(status, later)


def _numbered(lines: list[str], start: int, end: int, width: int) -> list[str]:
    return [f"{n:>{width}}: {lines[n - 1]}" for n in range(start, end + 1)]


def _section_lines(document: Document) -> dict[str, Section]:
    return {s.id: s for s in document.sections}


def search(corpus: Corpus, query: str, doc: str | None = None, limit: int = 8, start: int = 0) -> str:
    """Sections best matching `query` from the FTS5 index, `limit` from the 0-based `start`."""
    if not index.query_terms(query):
        raise ToolError("the query has no words to search for", f"{corpus.tool('search')}('<words>')")
    if limit < 1:
        raise ToolError("limit must be at least 1", "")
    if start < 0:
        raise ToolError("start is a 0-based offset", "pass the start=<n> of a next: line")
    only = resolve_doc(corpus, doc).doc_id if doc else None
    conn = fts.open_index(corpus)
    try:
        result = fts.search(conn, query, doc_id=only, limit=limit, start=start)
    finally:
        conn.close()
    if not result.hits:
        if start:
            return render(f"No more passages for {query!r} after {start}.", {})
        return render(f"No passages match {query!r}.", {})
    documents = {d.doc_id: d for d in corpus.documents}
    out = [f"Passages {start + 1}-{start + len(result.hits)} for {query!r}, best first:"]
    for hit in result.hits:
        document = documents.get(hit.doc_id)
        section = _section_lines(document).get(hit.section_id) if document else None
        where = f"lines {section.start_line}-{section.end_line}, " if section else ""
        snippet = " ".join(hit.snippet.split())
        out.append(f"\n{hit.doc_id}§{hit.section_id}  {hit.title}  ({where}score {hit.score:.3g})\n  {snippet}")
    footer = {
        "next": next_start(result.next_start),
        "relaxed": "no section holds every query word; these hold some" if result.relaxed else "",
        "warning": join_warning(
            *standing_notes(
                (hit.doc_id, _warning(corpus, documents[hit.doc_id]))
                for hit in result.hits
                if hit.doc_id in documents
            )
        ),
    }
    return render("\n".join(out), footer)


def read(
    corpus: Corpus,
    doc: str,
    section: str | None = None,
    lines: str | None = None,
    max_tokens: int = READ_TOKENS,
) -> str:
    """Numbered lines of a section or a line range, cut at whole lines within `max_tokens`."""
    if max_tokens < 1:
        raise ToolError("max_tokens must be at least 1", "")
    target = resolve(corpus, doc, section, lines)
    d = target.document
    if target.section is not None:
        s = target.section
        start, end, label = s.start_line, s.end_line, f"{d.doc_id}§{s.id} {s.heading}"
    elif target.lines is not None:
        start, end = target.lines
        label = d.doc_id
    else:
        raise ToolError(
            f"say what to read in {d.doc_id}: a section or a line range",
            f"{corpus.tool('outline')}({d.doc_id!r}) lists sections; then {corpus.tool('read')}('{d.doc_id}§<id>')",
        )
    if start < 1 or end < start:
        raise ToolError(f"invalid line range {start}-{end}", "lines are 1-based and START <= END")
    text = corpus.text_lines(d)
    if end > len(text):
        raise ToolError(f"line range {start}-{end} is past the end of {d.doc_id} ({len(text)} lines)", "")
    width = len(str(end))
    taken: list[str] = []
    used = 0
    for row in _numbered(text, start, end, width):
        cost = budget.tokens(row + "\n")
        if taken and used + cost > max_tokens:
            break
        taken.append(row)
        used += cost
    last = start + len(taken) - 1
    shown = f"lines {start}-{last}" + ("" if last == end else f" of {start}-{end}")
    cite = f"{d.number} §{target.section.id}" if target.section is not None else f"{d.number}, lines {start}-{last}"
    footer = {
        "cite": cite,
        "next": f"{d.doc_id}:{last + 1}-{end}" if last < end else "",
        "warning": _warning(corpus, d),
    }
    return render(f"{label} ({shown})\n" + "\n".join(taken), footer)


def outline(corpus: Corpus, doc: str, start: int = 0, limit: int = OUTLINE_ROWS) -> str:
    d = resolve_doc(corpus, doc)
    if limit < 1:
        raise ToolError("limit must be at least 1", "")
    if start < 0:
        raise ToolError("start is a 0-based offset", "pass the start=<n> of a next: line")
    if not d.sections:
        return render(f"{d.doc_id}: the index lists no sections for this document.", {})
    rows = d.sections[start : start + limit]
    out = [f"{d.number}, {d.title}"]
    for s in rows:
        indent = "  " * s.id.count(".")
        out.append(f"{indent}{s.id}  {s.heading}  (lines {s.start_line}-{s.end_line})")
    more = start + limit < len(d.sections)
    return render("\n".join(out), {"next": next_start(start + limit if more else None)})


def info(corpus: Corpus, doc: str) -> str:
    d = resolve_doc(corpus, doc)
    out = [
        f"doc_id: {d.doc_id}",
        f"number: {d.number}",
        f"title: {d.title}",
        f"date: {d.date}",
        f"status: {d.status}",
        f"url: {d.url}",
        f"sha256: {d.sha256}",
        f"sections: {len(d.sections)}",
    ]
    warning = ""
    if d.status.lower() != "final":
        warning = f"status is {d.status!r}, not 'final'. Check for a current version before relying on it."
    later = corpus.standing(d, corpus.defaults) if corpus.standing is not None else ""
    return render("\n".join(out), {"warning": join_warning(warning, later)})


def cite(corpus: Corpus, doc: str, section: str | None = None) -> str:
    target = resolve(corpus, doc, section)
    d = target.document
    if target.section is not None:
        s = target.section
        return render(f"{d.number} §{s.id}\n{d.url}\nHeading: {s.heading}", {})
    if target.lines is not None:
        first, last = target.lines
        return render(f"{d.number}, lines {first}-{last}\n{d.url}", {})
    return render(f"{d.number}\n{d.url}", {})
