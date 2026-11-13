"""Load and validate a collection's ``corpus/index.json`` against ``primarysource.pdfcorpus.models``."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from primarysource.pdfcorpus.models import Document, Section

if TYPE_CHECKING:
    from primarysource.pdfcorpus.spec import CorpusSpec

SCHEMA_VERSION = 1

_DOC_FIELDS = tuple(f.name for f in dataclasses.fields(Document))
_SECTION_FIELDS = tuple(f.name for f in dataclasses.fields(Section))


class CorpusError(Exception):
    """The corpus is missing or malformed; the message says how to fix it."""


@dataclasses.dataclass(frozen=True)
class Corpus:
    """A loaded corpus. `defaults` and `alias` resolve a bare publication name to a document (see `CorpusSpec`);
    `fetch_hint` is what a missing text file tells the caller to run."""

    root: Path
    documents: tuple[Document, ...]
    defaults: Mapping[str, str] = dataclasses.field(default_factory=dict)
    alias: Callable[[str], str] | None = None
    fetch_hint: str = "Fetch the corpus again."

    def text_lines(self, doc: Document) -> list[str]:
        """Lines of the document's extracted text (index 0 is line 1)."""
        path = (self.root / doc.text_file).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise CorpusError(f"{doc.doc_id}: text_file {doc.text_file!r} escapes the corpus directory.")
        try:
            # Split on newline only, as the ingest side does. splitlines() also breaks on form feeds,
            # which pdftotext puts at every page break, and that shifts every line number. Read with
            # newline="" for the same reason: universal newlines would also break on a lone "\r" that
            # pdftotext left inside a line (sp800-38g line 449). Only the "\r" of a CRLF is dropped.
            with path.open(encoding="utf-8", newline="") as handle:
                lines = [line.removesuffix("\r") for line in handle.read().split("\n")]
            if lines and lines[-1] == "":
                lines.pop()
            return lines
        except FileNotFoundError:
            raise CorpusError(f"{doc.doc_id}: text file {doc.text_file!r} is missing. {self.fetch_hint}") from None


def _check_fields(where: str, obj: object, expected: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(obj, dict):
        raise CorpusError(f"{where}: expected an object, got {type(obj).__name__}.")
    missing = [f for f in expected if f not in obj]
    extra = [f for f in obj if f not in expected]
    if missing:
        raise CorpusError(f"{where}: missing field(s) {', '.join(missing)}.")
    if extra:
        raise CorpusError(f"{where}: unknown field(s) {', '.join(extra)}.")
    return obj


def _parse_section(where: str, raw: object) -> Section:
    d = _check_fields(where, raw, _SECTION_FIELDS)
    for name in ("id", "heading"):
        if not isinstance(d[name], str) or not d[name]:
            raise CorpusError(f"{where}.{name}: expected a non-empty string.")
    for name in ("start_line", "end_line"):
        v = d[name]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise CorpusError(f"{where}.{name}: expected a positive integer.")
    if d["start_line"] > d["end_line"]:
        raise CorpusError(f"{where}: start_line {d['start_line']} is after end_line {d['end_line']}.")
    return Section(d["id"], d["heading"], d["start_line"], d["end_line"])


def _parse_document(where: str, raw: object) -> Document:
    d = _check_fields(where, raw, _DOC_FIELDS)
    for name in _DOC_FIELDS:
        if name == "sections":
            continue
        if not isinstance(d[name], str) or not d[name]:
            raise CorpusError(f"{where}.{name}: expected a non-empty string.")
    secs = d["sections"]
    if not isinstance(secs, list):
        raise CorpusError(f"{where}.sections: expected a list.")
    sections = tuple(_parse_section(f"{where}.sections[{i}]", s) for i, s in enumerate(secs))
    ids = [s.id for s in sections]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise CorpusError(f"{where}.sections: duplicate section id(s) {', '.join(dup)}.")
    values = {n: d[n] for n in _DOC_FIELDS if n != "sections"}
    return Document(sections=sections, **values)


def load_corpus(spec: CorpusSpec, root: Path | None = None) -> Corpus:
    """Read and validate the index; raise ``CorpusError`` with a fix-it message."""
    root = spec.corpus_dir() if root is None else root
    hint = spec.fetch_hint
    index = root / "index.json"
    if not index.is_file():
        raise CorpusError(f"No corpus index at {index}. The corpus is not fetched yet. {hint}")
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CorpusError(f"{index} is not valid JSON ({e}). Re-run `{spec.fetch_command}`.") from None
    if not isinstance(data, dict):
        raise CorpusError(f"{index}: expected a JSON object at the top level.")
    if data.get("schema") != SCHEMA_VERSION:
        raise CorpusError(
            f"{index}: schema is {data.get('schema')!r}, this server reads schema {SCHEMA_VERSION}. "
            f"Update primarysource or re-run `{spec.fetch_command}`."
        )
    docs = data.get("documents")
    if not isinstance(docs, list):
        raise CorpusError(f"{index}: 'documents' must be a list.")
    documents = tuple(_parse_document(f"documents[{i}]", d) for i, d in enumerate(docs))
    ids = [d.doc_id for d in documents]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise CorpusError(f"{index}: duplicate doc_id(s) {', '.join(dup)}.")
    defaults = spec.read_defaults(root) if spec.read_defaults is not None else {}
    return Corpus(root=root, documents=documents, defaults=defaults, alias=spec.alias, fetch_hint=hint)
