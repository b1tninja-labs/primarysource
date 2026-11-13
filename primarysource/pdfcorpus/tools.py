"""The five tools as plain functions returning text. ``ToolError`` marks a caller mistake."""

from __future__ import annotations

import re

from primarysource.pdfcorpus.corpus import Corpus
from primarysource.pdfcorpus.models import Document, Section

MAX_READ_LINES = 400
SNIPPET_LINES = 3
_TOKEN = re.compile(r"[a-z0-9]+")


class ToolError(Exception):
    """A bad argument or unknown reference; the message says what to do instead."""


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


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
    raise ToolError(f"Unknown document {doc!r}. Known doc_ids: {known}.")


def resolve_section(document: Document, section: str) -> Section:
    sid = section.strip().lstrip("§").strip()
    for s in document.sections:
        if s.id == sid:
            return s
    raise ToolError(
        f"{document.doc_id} has no section {sid!r}. Use outline({document.doc_id!r}) to list section ids."
    )


def _numbered(lines: list[str], start: int, end: int) -> str:
    width = len(str(end))
    return "\n".join(f"{n:>{width}}: {lines[n - 1]}" for n in range(start, end + 1))


def search(corpus: Corpus, query: str, doc: str | None = None, limit: int = 8) -> str:
    qtoks = list(dict.fromkeys(tokens(query)))
    if not qtoks:
        raise ToolError("Empty query: give at least one word or number to search for.")
    if limit < 1:
        raise ToolError("limit must be at least 1.")
    docs = [resolve_doc(corpus, doc)] if doc else list(corpus.documents)
    hits: list[tuple[float, Document, Section, int, int]] = []
    for d in docs:
        lines = corpus.text_lines(d)
        # A line belongs to the narrowest section containing it, so a parent
        # section is not credited with its children's text.
        owner: dict[int, Section] = {}
        for s in sorted(d.sections, key=lambda s: s.end_line - s.start_line, reverse=True):
            for n in range(s.start_line, min(s.end_line, len(lines)) + 1):
                owner[n] = s
        per_sec: dict[str, dict[int, set[str]]] = {}
        for n, s in owner.items():
            found = set(tokens(lines[n - 1])).intersection(qtoks)
            if found:
                per_sec.setdefault(s.id, {})[n] = found
        by_id = {s.id: s for s in d.sections}
        for sid, matched in per_sec.items():
            s = by_id[sid]
            head = set(tokens(s.heading)).intersection(qtoks)
            body = [t for ln in matched for t in tokens(lines[ln - 1])]
            distinct = set().union(*matched.values()) | head
            score = float(sum(body.count(t) for t in qtoks)) + 3.0 * len(head) + 5.0 * len(distinct)
            best = max(matched, key=lambda ln: (len(matched[ln]), -ln))
            first = max(s.start_line, best - 1)
            last = min(s.end_line, len(lines), first + SNIPPET_LINES - 1)
            hits.append((score, d, s, first, last))
    if not hits:
        return f"No passages match {query!r}."
    hits.sort(key=lambda h: (-h[0], h[1].doc_id, h[3]))
    out = [f"{min(limit, len(hits))} of {len(hits)} passages for {query!r}:"]
    for score, d, s, first, last in hits[:limit]:
        snippet = _numbered(corpus.text_lines(d), first, last)
        out.append(f"\n{d.doc_id} §{s.id} {s.heading} (lines {first}-{last}, score {score:g})\n{snippet}")
    return "\n".join(out)


def parse_lines(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-:]\s*(\d+))?\s*", spec)
    if not m:
        raise ToolError(f"Cannot parse lines={spec!r}; use 'START-END', e.g. '120-160'.")
    start = int(m.group(1))
    return start, int(m.group(2) or start)


def read(corpus: Corpus, doc: str, section: str | None = None, lines: str | None = None) -> str:
    d = resolve_doc(corpus, doc)
    if (section is None) == (lines is None):
        raise ToolError("Give exactly one of section (an id from outline) or lines ('START-END').")
    text = corpus.text_lines(d)
    if section is not None:
        s = resolve_section(d, section)
        start, end, label = s.start_line, s.end_line, f"{d.doc_id} §{s.id} {s.heading}"
    elif lines is not None:
        start, end = parse_lines(lines)
        label = d.doc_id
    if start < 1 or end < start:
        raise ToolError(f"Invalid line range {start}-{end}.")
    if end > len(text):
        raise ToolError(f"Line range {start}-{end} is past the end of {d.doc_id} ({len(text)} lines).")
    note = ""
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
        note = f"\n[truncated at {MAX_READ_LINES} lines; continue with lines='{end + 1}-...']"
    return f"{label} (lines {start}-{end})\n{_numbered(text, start, end)}{note}"


def outline(corpus: Corpus, doc: str) -> str:
    d = resolve_doc(corpus, doc)
    if not d.sections:
        return f"{d.doc_id}: the index lists no sections for this document."
    out = [f"{d.number}, {d.title}"]
    for s in d.sections:
        indent = "  " * s.id.count(".")
        out.append(f"{indent}{s.id}  {s.heading}  (lines {s.start_line}-{s.end_line})")
    return "\n".join(out)


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
    if d.status.lower() != "final":
        out.append(f"WARNING: status is {d.status!r}, not 'final'. Check for a current version before relying on it.")
    return "\n".join(out)


def cite(corpus: Corpus, doc: str, section: str | None = None) -> str:
    d = resolve_doc(corpus, doc)
    if section is None:
        return f"{d.number}\n{d.url}"
    s = resolve_section(d, section)
    return f"{d.number} §{s.id}\n{d.url}\nHeading: {s.heading}"
