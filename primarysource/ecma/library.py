"""Read, outline, search and cite imported Ecma standards. Local files only; nothing here fetches.

A ref is `ecma:427§5.3¶2`: the standard's number (`427`, or `ECMA-427`), an optional `@<edition number>`, `§` and
a clause number as the PDF's bookmarks give it (`5.3`, `A` for Annex A, `A.1`), or the slug of an unnumbered
bookmark (`bibliography`), and `¶n`, the nth sentence of that clause's span. The span is the clause's own text,
then each subsection as a `§5.3.1 Title` line followed by its text. Sentences, not paragraphs, because a PDF
gives sentences. A ref with no section is the whole standard.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from primarysource import budget, cursor
from primarysource.c2sp._fetch import sha256
from primarysource.ecma import _pdf
from primarysource.ecma.catalogue import NUMBER
from primarysource.ecma.catalogue import catalogue as packaged_catalogue
from primarysource.ecma.importer import read_record
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = re.compile(r"^(?:ecma:)?(?:ecma-)?", re.IGNORECASE)


def grammar() -> RefGrammar:
    from primarysource.ecma import ECMA_DOC, ECMA_SECTION

    return RefGrammar(ECMA_DOC, ECMA_SECTION)


@dataclass(frozen=True, slots=True)
class Loaded:
    number: str
    edition: int
    designation: str
    edition_name: str
    title: str
    page_url: str
    document: _pdf.PdfDocument

    @property
    def label(self) -> str:
        return f"{self.number}@{self.edition}"


def default_home() -> Path:
    return collection_home("ecma")


def parse_ref(text: str) -> Ref:
    """Parse an ecma ref, accepting the `ecma:` prefix and `ECMA-427` for `427`."""
    body, doc_para = cursor.split_doc_para(PREFIX.sub("", text.strip(), count=1))
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not an ecma ref: {text!r}", "ecma refs are <number>[@edition][§clause][¶n]")
    if ref.doc is None:
        raise LibError(f"not an ecma ref: {text!r}", "start with the standard's number, e.g. 427")
    return ref


def _split_doc(token: str) -> tuple[str, int | None]:
    number, _, edition = token.partition("@")
    if not NUMBER.fullmatch(number) or (edition and not edition.isdigit()):
        raise LibError(f"not an Ecma standard: {token!r}", "use the number, e.g. 427, or 427@1")
    return number, int(edition) if edition else None


def load(token: str, home: Path | None = None) -> Loaded:
    """Load `number[@edition]` (the highest imported edition if none is named), verifying the stored PDF."""
    home = home or default_home()
    number, wanted = _split_doc(token)
    record = read_record(home)
    candidates: list[tuple[int, str]] = []
    for key in record["editions"]:
        match = re.fullmatch(r"(\d{1,4})-(\d{1,2})", key)
        if match and match.group(1) == number and (wanted is None or int(match.group(2)) == wanted):
            candidates.append((int(match.group(2)), key))
    if not candidates:
        have = ", ".join(sorted(record["editions"])) or "nothing"
        raise LibError(
            f"ECMA-{number}{'@' + str(wanted) if wanted else ''} is not imported (have: {have})",
            "ecma_docs lists the catalogue",
            f"primarysource ecma import {number}",
        )
    edition, key = max(candidates)
    pin = record["editions"][key].get("sha256")
    pdf = home / f"{key}.pdf"
    stored = home / f"{key}.json"
    try:
        if not isinstance(pin, str) or sha256(pdf.read_bytes()) != pin:
            raise LibError(
                f"{key}.pdf does not match its recorded sha256",
                "",
                f"re-import it: primarysource ecma import {number}",
            )
        raw = json.loads(stored.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(
            f"cannot read the import of ECMA-{number}: {exc}", "", f"re-import it: primarysource ecma import {number}"
        ) from exc
    document = _pdf.PdfDocument.from_json(raw)
    return Loaded(
        number,
        edition,
        str(raw.get("designation", f"ECMA-{number}")),
        str(raw.get("edition", f"edition {edition}")),
        document.title or str(raw.get("designation", "")),
        str(raw.get("page_url", "")),
        document,
    )


def _cite_text(doc: Loaded, section: _pdf.PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    return f"Ecma International, {doc.designation}, {doc.title}, {doc.edition_name}{where}. {doc.page_url}"


def _doc(ref: Ref) -> str:
    """The document of a parsed ref; `parse_ref` has already refused a ref without one."""
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the document id")
    return ref.doc


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, _pdf.PdfSection | None, tuple[str, ...], str]:
    doc = load(_doc(ref), home)
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return doc, None, tuple(units), ""
    index, warning = doc.document.find(ref.section)
    return doc, doc.document.sections[index], doc.document.span(index), warning


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at sentence boundaries within `max_tokens`. A `¶n` ref starts at sentence n and runs to
    the end of its scope; the `next:` footer is the ref that reads the next page."""
    ref = parse_ref(ref_text)
    doc, section, units, warning = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "read its subsections, see ecma_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"ecma:{doc.number}@{doc.edition}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite_text(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(token: str, home: Path | None = None) -> str:
    """A standard's bookmarked clauses, indented by depth, each with the ref that reads it and its PDF page."""
    doc = load(token, home)
    lines = [f"{doc.designation} {doc.title}, {doc.edition_name}  [{doc.label}, {doc.document.pages} pages]"]
    for section in doc.document.sections:
        indent = "  " * section.depth
        lines.append(
            f"{indent}{section.id} {section.title}  ecma:{doc.number}@{doc.edition}§{section.id}  (p. {section.page})"
        )
    return "\n".join(lines)


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    """Sentences containing every query word (else at least half, flagged `relaxed`), best first: one line per
    hit, `<ref>¶n: <snippet>`."""
    terms = _pdf.query_terms(query)
    home = home or default_home()
    record = read_record(home)
    keys = sorted(record["editions"])
    if not keys:
        raise LibError(
            "no Ecma standards are imported", "ecma_docs lists the catalogue", "primarysource ecma import 427"
        )
    tokens = [doc] if doc else [k.replace("-", "@") for k in keys]
    scored: list[tuple[float, int, str, str]] = []
    relaxed = False
    for need_all in (True, False):
        for order, token in enumerate(tokens):
            loaded = load(token, home)
            for section in loaded.document.sections:
                for score, number in _pdf.score_units(section.sentences, terms, section.title, need_all):
                    ref = f"ecma:{loaded.number}@{loaded.edition}§{section.id}¶{number}"
                    scored.append((-score, order, ref, _pdf.snippet(section.sentences[number - 1], terms)))
        if scored:
            relaxed = not need_all
            break
    if not scored:
        return render("no matches", {})
    scored.sort()
    shown, nxt = cursor.window(scored, start, limit)
    footer = {"next": nxt, "relaxed": "only some query words matched" if relaxed else ""}
    return render("\n".join(f"{ref}: {snip}" for _, _, ref, snip in shown), footer)


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
    label = f"ecma:{doc.number}@{doc.edition}" + (f"§{section.id}" if section else "")
    return render(label, footer)


def docs(home: Path | None = None) -> str:
    """The catalogue and which editions are imported."""
    home = home or default_home()
    cat = packaged_catalogue()
    record = read_record(home)
    lines = [f"placement {cat.terms.placement}; {cat.terms.licence}"]
    for found in cat.editions:
        state = "imported" if found.key in record["editions"] else "not imported"
        lines.append(f"{state:<13} {found.designation}@{found.edition}  {found.title}, {found.edition_name}")
    return "\n".join(lines)
