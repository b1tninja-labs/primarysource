"""Read, outline, search and cite imported Broadband Forum documents. Local files only; nothing here fetches.

Two kinds of document share one ref shape, `bbf:<doc>§<section>¶n` (the `bbf:` prefix is optional):

- a data-model file, `bbf:tr-181-2-22-0-ip`: `§` is the full path of an object, parameter, command, event,
  profile or data type, `¶n` the nth paragraph of its description (see `datamodel.py`);
- a Technical Report, `bbf:tr-069-1-6-1`: `§` is a clause number as the PDF's bookmarks give it (`3.5`,
  `A.3.2.3`), `A` for `Annex A.`, `Appendix-I` for `Appendix I.`, or the slug of an unnumbered bookmark
  (`normative-references`); `¶n` is the nth sentence of the clause's span (its own text, then each subsection
  as a `§3.5.1 Title` line and its text).

Every result's `unit:` footer says which unit `¶n` counts.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path

from primarysource import budget, cursor
from primarysource.bbf import datamodel
from primarysource.bbf.catalogue import DOC_ID
from primarysource.bbf.catalogue import catalogue as packaged_catalogue
from primarysource.bbf.importer import read_record
from primarysource.c2sp._fetch import sha256
from primarysource.ecma import _pdf
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = re.compile(r"^bbf:", re.IGNORECASE)
MAX_LISTING = 400


def grammar() -> RefGrammar:
    from primarysource.bbf import BBF_DOC, BBF_SECTION

    return RefGrammar(BBF_DOC, BBF_SECTION)


@dataclass(frozen=True, slots=True)
class LoadedModel:
    id: str
    model: datamodel.DataModel
    commit: str


@dataclass(frozen=True, slots=True)
class LoadedReport:
    id: str
    designation: str
    title: str
    edition: str
    document: _pdf.PdfDocument


def default_home() -> Path:
    return collection_home("bbf")


@functools.lru_cache(maxsize=8)
def _parse_model(digest: str, path: str) -> datamodel.DataModel:
    """Parse an installed file, cached by its verified digest so a search over many files parses each once."""
    return datamodel.parse(Path(path).read_bytes())


def parse_ref(text: str) -> Ref:
    """Parse a bbf ref, accepting the optional `bbf:` prefix and `<doc>¶n` (unit n of a whole-report read)."""
    body, doc_para = cursor.split_doc_para(PREFIX.sub("", text.strip(), count=1))
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not a bbf ref: {text!r}", "bbf refs are <doc>[§<section>][¶n]")
    if ref.doc is None:
        raise LibError(f"not a bbf ref: {text!r}", "start with the document, e.g. tr-069-1-6-1 or tr-181-2-22-0-ip")
    return ref


def _doc(ref: Ref) -> str:
    """The document of a parsed ref; `parse_ref` has already refused a ref without one."""
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the document id")
    return ref.doc


def load(token: str, home: Path | None = None) -> LoadedModel | LoadedReport:
    """Load one installed document by id, verifying the stored file's sha256."""
    home = home or default_home()
    if not DOC_ID.fullmatch(token):
        raise LibError(f"not a Broadband Forum document id: {token!r}", "bbf_docs lists what is catalogued")
    record = read_record(home)
    if token in record["models"]:
        path = home / "models" / f"{token}.xml"
        try:
            digest = sha256(path.read_bytes())
        except OSError as exc:
            raise LibError(
                f"cannot read {path.name}: {exc}", "", f"re-import it: primarysource bbf import-models {token}"
            ) from exc
        if digest != record["models"][token]:
            raise LibError(
                f"{token}.xml does not match its recorded sha256",
                "",
                f"re-import it: primarysource bbf import-models {token}",
            )
        return LoadedModel(token, _parse_model(digest, str(path)), str(record.get("commit", "")))
    if token in record["reports"]:
        pdf = home / "reports" / f"{token}.pdf"
        stored = home / "reports" / f"{token}.json"
        pin = record["reports"][token].get("sha256")
        try:
            if not isinstance(pin, str) or sha256(pdf.read_bytes()) != pin:
                raise LibError(
                    f"{token}.pdf does not match its recorded sha256",
                    "",
                    f"re-import it: primarysource bbf import-report {token}",
                )
            raw = json.loads(stored.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LibError(
                f"cannot read the import of {token}: {exc}",
                "",
                f"re-import it: primarysource bbf import-report {token}",
            ) from exc
        document = _pdf.PdfDocument.from_json(raw)
        return LoadedReport(
            token,
            str(raw.get("designation", token.upper())),
            str(raw.get("title", "")),
            str(raw.get("edition", "")),
            document,
        )
    have = ", ".join(sorted({*record["models"], *record["reports"]})[:12]) or "nothing"
    raise LibError(
        f"{token} is not imported (have: {have})",
        "bbf_docs lists what is catalogued and imported",
        f"primarysource bbf import-models {token}  (a data model) or primarysource bbf import-report {token}",
    )


def _blob_url(model: LoadedModel) -> str:
    return f"https://github.com/BroadbandForum/cwmp-data-models/blob/{model.commit}/{model.id}.xml"


def _cite_model(doc: LoadedModel, node: datamodel.Node | None, para: int | str | None) -> str:
    where = f", {node.kind} {node.id}" if node else ""
    if para:
        where += f" ¶{para}"
    return (
        f"Broadband Forum, {doc.id}.xml ({doc.model.title}), cwmp-data-models commit {doc.commit[:7]}{where}. "
        f"BSD-3-Clause. {_blob_url(doc)}"
    )


def _cite_report(doc: LoadedReport, section: _pdf.PdfSection | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    url = next(
        (r.page_url for r in packaged_catalogue().reports if r.id == doc.id), "https://www.broadband-forum.org/"
    )
    return f"Broadband Forum, {doc.designation} {doc.title}, {doc.edition}{where}. {url}"


def _report_units(doc: LoadedReport, ref: Ref) -> tuple[_pdf.PdfSection | None, tuple[str, ...], str]:
    if ref.section is None:
        units: list[str] = []
        for section in doc.document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.sentences)
        return None, tuple(units), ""
    index, warning = doc.document.find(ref.section)
    return doc.document.sections[index], doc.document.span(index), warning


def _overview(doc: LoadedModel) -> str:
    counts: dict[str, int] = {}
    for node in doc.model.nodes:
        counts[node.kind] = counts.get(node.kind, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    lines = [f"{doc.model.title}", f"spec {doc.model.spec}", f"file {doc.model.file}", f"nodes: {summary or 'none'}"]
    if doc.model.imports:
        lines.append("imports: " + ", ".join(doc.model.imports))
    lines.append(f"bbf_outline('{doc.id}') lists the nodes; read one as '{doc.id}§<path>'")
    return "\n".join(lines)


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at unit boundaries within `max_tokens`. A `¶n` ref starts at unit n and runs to the end
    of its scope; the `next:` footer is the ref that reads the next page."""
    ref = parse_ref(ref_text)
    doc = load(_doc(ref), home)
    if isinstance(doc, LoadedModel):
        if ref.section is None:
            if ref.para is not None:
                raise LibError(f"{ref_text}: ¶ needs a node", "name one after §, e.g. §Device.IP.Interface.{i}")
            return render(_overview(doc), {"cite": _cite_model(doc, None, None), "unit": "paragraph"})
        node, warning = doc.model.find(ref.section)
        paragraphs = node.paragraphs
        first = cursor.first_unit(ref.para, len(paragraphs), "paragraphs", ref_text)
        chosen = budget.page(paragraphs, start=first, max_tokens=max_tokens) if paragraphs else None
        parts = [] if ref.para is not None else [node.header()]
        contents = doc.model.children(node)
        if contents and ref.para is None:
            names = [c.id.rsplit(".", 1)[-1] for c in contents[:80]]
            more = f" (+{len(contents) - 80} more)" if len(contents) > 80 else ""
            parts.append("contains: " + ", ".join(names) + more)
        if chosen is not None:
            parts.extend(chosen.units)
        body = "\n\n".join(parts)
        footer = {
            "cite": _cite_model(doc, node, cursor.para_label(ref.para, chosen) if chosen else None),
            "unit": "paragraph",
            "span": span_hash(body),
            "next": cursor.read_next(f"bbf:{doc.id}§{node.id}", chosen) if chosen else "",
            "warning": warning,
        }
        return render(body, footer)
    section, units, warning = _report_units(doc, ref)
    if not units:
        raise LibError(f"{ref_text}: that clause has no text of its own", "read its subsections, see bbf_outline")
    first = cursor.first_unit(ref.para, len(units), "sentences", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n".join(chosen.units)
    scope = f"bbf:{doc.id}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite_report(doc, section, cursor.para_label(ref.para, chosen)),
        "unit": "sentence",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(token: str, under: str = "", limit: int = 200, start: int = 0, home: Path | None = None) -> str:
    """A document's structure. A report: its bookmarked clauses with refs and pages. A data model: its objects,
    commands, events, profiles and data types, indented by path depth; `under` (a node path) lists everything
    below that node, parameters included. Both are paged by `limit` and the 0-based `start`."""
    doc = load(token, home)
    if isinstance(doc, LoadedReport):
        head = f"{doc.designation} {doc.title}, {doc.edition}  [{doc.id}, {doc.document.pages} pages]"
        clauses = [
            f"{'  ' * section.depth}{section.id} {section.title}  bbf:{doc.id}§{section.id}  (p. {section.page})"
            for section in doc.document.sections
        ]
        shown, nxt = cursor.window(clauses, start, limit)
        return render("\n".join([head, *shown]), {"next": nxt})
    prefix = under.strip().rstrip(".")
    rows = []
    for node in doc.model.nodes:
        if prefix:
            if not (node.id == prefix or node.id.startswith((prefix + ".", prefix + "()"))):
                continue
        elif node.kind == "parameter":
            continue
        depth = len([part for part in node.id.split(".") if part and part != "{i}"]) - 1
        rows.append(f"{'  ' * max(0, min(depth, 12))}{node.kind} {node.id}")
    if not rows:
        raise LibError(f"nothing under {under!r} in {doc.id}", "omit under to list the objects")
    shown, nxt = cursor.window(rows, start, limit)
    header = f"{doc.model.title}  [{doc.id}]  refs: bbf:{doc.id}§<path>"
    return render("\n".join([header, *shown]), {"next": nxt})


def _documents(doc: str | None, home: Path) -> list[str]:
    record = read_record(home)
    if doc:
        return [doc]
    ids = [*sorted(record["reports"]), *sorted(record["models"])]
    if not ids:
        raise LibError(
            "no Broadband Forum documents are imported",
            "bbf_docs lists the catalogue",
            "primarysource bbf import-models",
        )
    return ids


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    """Units containing every query word (else at least half, flagged `relaxed`), best first: one line per hit,
    `<ref>: <snippet>`. A data-model node whose path matches is a hit with no ¶."""
    terms = _pdf.query_terms(query)
    home = home or default_home()
    tokens = _documents(doc, home)
    loaded = [load(token, home) for token in tokens]
    scored: list[tuple[float, int, str, str]] = []
    relaxed = False
    for need_all in (True, False):
        for order, item in enumerate(loaded):
            if isinstance(item, LoadedReport):
                for section in item.document.sections:
                    for score, number in _pdf.score_units(section.sentences, terms, section.title, need_all):
                        ref = f"bbf:{item.id}§{section.id}¶{number}"
                        scored.append((-score, order, ref, _pdf.snippet(section.sentences[number - 1], terms)))
                continue
            for node in item.model.nodes:
                units = (node.header(), *node.paragraphs)
                for score, number in _pdf.score_units(units, terms, node.id, need_all):
                    ref = f"bbf:{item.id}§{node.id}" + (f"¶{number - 1}" if number > 1 else "")
                    scored.append((-score, order, ref, _pdf.snippet(units[number - 1], terms)))
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
    doc = load(_doc(ref), home)
    if isinstance(doc, LoadedModel):
        if ref.section is None:
            return render(
                doc.id, {"cite": _cite_model(doc, None, None), "unit": "paragraph", "span": span_hash(_overview(doc))}
            )
        node, warning = doc.model.find(ref.section)
        text = "\n\n".join(node.paragraphs)
        if ref.para is not None:
            if ref.para > len(node.paragraphs):
                raise LibError(
                    f"{ref_text}: the description has {len(node.paragraphs)} paragraphs", "use a ¶ within range"
                )
            text = node.paragraphs[ref.para - 1]
        footer = {
            "cite": _cite_model(doc, node, ref.para),
            "unit": "paragraph",
            "span": span_hash(text),
            "warning": warning,
        }
        return render(f"{doc.id}§{node.id}", footer)
    section, units, warning = _report_units(doc, ref)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} sentences", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    footer = {
        "cite": _cite_report(doc, section, ref.para),
        "unit": "sentence",
        "span": span_hash("\n".join(units)),
        "warning": warning,
    }
    return render(f"{doc.id}" + (f"§{section.id}" if section else ""), footer)


def docs(filter_text: str = "", home: Path | None = None) -> str:
    """The catalogue and what is imported: reports first, then data-model files (at most `MAX_LISTING` lines)."""
    home = home or default_home()
    cat = packaged_catalogue()
    record = read_record(home)
    needle = filter_text.casefold()
    lines = [
        f"reports: {cat.report_terms.licence}, placement {cat.report_terms.placement}",
    ]
    for report in cat.reports:
        if needle in report.id or needle in report.title.casefold():
            state = "imported" if report.id in record["reports"] else "not imported"
            lines.append(f"{state:<13} {report.id}  {report.designation} {report.title}, {report.issue}")
    lines.append(f"models: {cat.model_terms.licence}, placement {cat.model_terms.placement}, commit {cat.commit[:7]}")
    shown = 0
    for model in cat.models:
        if needle in model.id or needle in model.title.casefold():
            if shown >= MAX_LISTING:
                lines.append("... (narrow with a filter)")
                break
            state = "imported" if model.id in record["models"] else "not imported"
            lines.append(f"{state:<13} {model.id}  {model.title}")
            shown += 1
    return "\n".join(lines)
