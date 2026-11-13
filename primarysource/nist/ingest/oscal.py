"""OSCAL catalogues as a second, structured source: ``python -m primarysource.nist.ingest.oscal``.

NIST publishes machine-readable catalogues in the ``usnistgov/oscal-content`` repository. Each catalogue is
rendered to a plain-text file with one section per control (the control id is the section id, the control
title its heading) and indexed through the same writer as the PDF pipeline, under a doc_id ending in
``-oscal`` so the two versions of a publication cannot collide.

The catalogues to fetch are the ``[[oscal]]`` tables of data/sources.toml, each pinned to a commit and to the
git blob sha of the file. The PDF pipeline ignores those tables. This module touches the network only for those URLs.
"""

from __future__ import annotations

from primarysource.nist.paths import data_dir as default_data_dir, sources_file

import argparse
import hashlib
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from primarysource.nist.ingest.index import read_index, sha256_bytes, write_index
from primarysource.nist.models import Document, Section

NAMESPACE = "http://csrc.nist.gov/ns/oscal/1.0"
USER_AGENT = "nistlib-oscal/0.1 (corpus fetcher; one request per second)"
TIMEOUT_SECONDS = 120
MAX_BYTES = 50 * 1024 * 1024
THROTTLE_SECONDS = 1.0
DOC_ID_SUFFIX = "-oscal"
ALLOWED_HOST_PREFIX = "https://raw.githubusercontent.com/usnistgov/oscal-content/"

_DATE = re.compile(r"^(\d{4}-(?:0[1-9]|1[0-2]))")
_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = ("doc_id", "url", "number", "title", "date", "status", "commit", "blob")
_SKIPPED_CHILDREN = frozenset({"prop", "link", "title", "param", "label"})


class OscalError(RuntimeError):
    """Raised when a catalogue cannot be fetched, verified or parsed."""


def _q(name: str) -> str:
    return f"{{{NAMESPACE}}}{name}"


def _local(element: ET.Element) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    prefix = f"{{{NAMESPACE}}}"
    return tag[len(prefix) :] if tag.startswith(prefix) else tag


def _norm(text: str) -> str:
    return " ".join(text.split())


# -- sources -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OscalSource:
    """One ``[[oscal]]`` table of sources.toml."""

    doc_id: str
    url: str
    number: str
    title: str
    date: str
    status: str
    commit: str
    blob: str


def parse_oscal_sources(text: str) -> tuple[OscalSource, ...]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise OscalError(f"sources.toml is not valid TOML: {error}") from error
    entries = data.get("oscal", [])
    if not isinstance(entries, list):
        raise OscalError("sources.toml: oscal must be an array of tables")
    result: list[OscalSource] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        label = f"oscal #{position}"
        if not isinstance(entry, dict):
            raise OscalError(f"{label}: not a table")
        missing = [
            k
            for k in _REQUIRED
            if not isinstance(entry.get(k), str) or not entry[k].strip()
        ]
        if missing:
            raise OscalError(
                f"{label}: missing or empty field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(entry) - set(_REQUIRED))
        if unknown:
            raise OscalError(f"{label}: unknown field(s): {', '.join(unknown)}")
        doc_id = entry["doc_id"]
        label = f"oscal {doc_id!r}"
        if not _DOC_ID.match(doc_id) or not doc_id.endswith(DOC_ID_SUFFIX):
            raise OscalError(
                f"{label}: doc_id must be a file-safe slug ending in {DOC_ID_SUFFIX}"
            )
        if doc_id in seen:
            raise OscalError(f"{label}: duplicate doc_id")
        seen.add(doc_id)
        if not entry["url"].startswith(ALLOWED_HOST_PREFIX):
            raise OscalError(f"{label}: url must be under {ALLOWED_HOST_PREFIX}")
        if not _DATE.fullmatch(entry["date"]):
            raise OscalError(f"{label}: date must be YYYY-MM")
        for key in ("commit", "blob"):
            if not _HEX40.match(entry[key]):
                raise OscalError(f"{label}: {key} must be 40 lowercase hex digits")
        if entry["commit"] not in entry["url"]:
            raise OscalError(f"{label}: url is not pinned to the recorded commit")
        result.append(OscalSource(**{k: entry[k] for k in _REQUIRED}))
    return tuple(result)


def load_oscal_sources(path: Path) -> tuple[OscalSource, ...]:
    try:
        return parse_oscal_sources(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise OscalError(f"cannot read {path}: {error}") from error


# -- rendering ---------------------------------------------------------------------------------------------


def _inline(element: ET.Element, params: dict[str, str]) -> str:
    """Plain text of a mixed-content element. ``insert`` becomes its parameter's label, ``q`` is quoted."""
    pieces: list[str] = [element.text or ""]
    for child in element:
        name = _local(child)
        if name == "insert":
            ref = child.get("id-ref", "")
            pieces.append(f"[{params.get(ref) or ref}]")
        elif name == "q":
            pieces.append(f'"{_inline(child, params)}"')
        else:
            pieces.append(_inline(child, params))
        pieces.append(child.tail or "")
    return _norm("".join(pieces))


def _part_label(part: ET.Element) -> str:
    for prop in part.findall(_q("prop")):
        if prop.get("name") == "label":
            return _norm(prop.get("value", ""))
    return ""


def _part_lines(part: ET.Element, params: dict[str, str], depth: int) -> list[str]:
    """Lines for one part: its prose, list items and nested parts, indented by nesting depth."""
    indent = "  " * depth
    out: list[str] = []
    pending = _part_label(part)

    def emit(text: str) -> None:
        nonlocal pending
        if not text:
            return
        out.append(f"{indent}{pending + ' ' if pending else ''}{text}")
        pending = ""

    for child in part:
        name = _local(child)
        if name == "p":
            emit(_inline(child, params))
        elif name in ("ul", "ol"):
            for item in child.findall(_q("li")):
                emit("- " + _inline(item, params))
        elif name == "part":
            if pending:
                out.append(f"{indent}{pending}")
                pending = ""
            out.extend(_part_lines(child, params, depth + 1))
        elif name not in _SKIPPED_CHILDREN:
            emit(_inline(child, params))
    if pending:
        out.append(f"{indent}{pending}")
    return out


def _top_part_lines(part: ET.Element, params: dict[str, str]) -> list[str]:
    """A control's top-level part. Everything but the statement gets a heading line naming it."""
    name = part.get("name", "")
    if name == "statement":
        return _part_lines(part, params, 0)
    title = (
        _norm(part.findtext(_q("title")) or "") or name.replace("-", " ").capitalize()
    )
    return [f"{title}:", *_part_lines(part, params, 1)]


def _select_text(param: ET.Element) -> str:
    """A parameter without a label may offer choices: ``one-or-more: a | b``, else ``a | b``."""
    select = param.find(_q("select"))
    if select is None:
        return ""
    choices = " | ".join(
        _norm("".join(c.itertext())) for c in select.findall(_q("choice"))
    )
    how_many = select.get("how-many")
    return f"{how_many}: {choices}" if how_many and choices else choices


def _collect_params(root: ET.Element) -> dict[str, str]:
    """Parameter id -> label, so a prose ``insert`` can name what it stands for."""
    params: dict[str, str] = {}
    for param in root.iter(_q("param")):
        pid = param.get("id")
        if pid:
            params[pid] = _norm(param.findtext(_q("label")) or "") or _select_text(
                param
            )
    return params


def render_catalog(root: ET.Element) -> tuple[str, tuple[Section, ...]]:
    """Render a parsed OSCAL catalogue to (text, sections), one section per control, in document order.

    Groups are walked, nested controls become sections of their own right after their parent, and a blank
    line separates sections. A section's line range covers its heading and its own prose only.
    """
    if root.tag != _q("catalog"):
        raise OscalError(
            f"root element is {root.tag!r}, expected {{{NAMESPACE}}}catalog"
        )
    params = _collect_params(root)
    lines: list[str] = []
    sections: list[Section] = []
    seen: set[str] = set()

    def add_control(control: ET.Element) -> None:
        cid = (control.get("id") or "").strip()
        if not cid:
            raise OscalError("a control has no id")
        if cid in seen:
            raise OscalError(f"duplicate control id {cid!r}")
        seen.add(cid)
        title = _norm(control.findtext(_q("title")) or "") or cid
        body = [f"{cid} {title}"]
        for part in control.findall(_q("part")):
            body.extend(_top_part_lines(part, params))
        start = len(lines) + 1
        lines.extend(body)
        sections.append(Section(cid, title, start, len(lines)))
        lines.append("")
        for nested in control.findall(_q("control")):
            add_control(nested)

    def walk(container: ET.Element) -> None:
        for child in container:
            name = _local(child)
            if name == "group":
                walk(child)
            elif name == "control":
                add_control(child)

    walk(root)
    return "\n".join(lines) + "\n", tuple(sections)


def catalog_metadata(root: ET.Element) -> tuple[str, str, str]:
    """(title, date YYYY-MM, status) as the catalogue itself states them.

    Status is the ``publication-status`` prop, lowercased, or ``unspecified`` when the catalogue has none.
    """
    meta = root.find(_q("metadata"))
    if meta is None:
        raise OscalError("catalogue has no metadata")
    title = _norm(meta.findtext(_q("title")) or "")
    modified = _DATE.match((meta.findtext(_q("last-modified")) or "").strip())
    if not title or modified is None:
        raise OscalError("metadata lacks a title or a last-modified date")
    status = "unspecified"
    for prop in meta.findall(_q("prop")):
        if prop.get("name") == "publication-status" and prop.get("value"):
            status = prop.get("value", "").strip().lower()
    return title, modified.group(1), status


def parse_catalog(data: bytes) -> ET.Element:
    """Parse catalogue bytes with the standard library, refusing DTDs and entity declarations."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise OscalError("catalogue declares a DTD or entities, refusing to parse it")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise OscalError(f"catalogue is not well-formed XML: {error}") from error


# -- fetching and indexing ---------------------------------------------------------------------------------


def git_blob_sha(data: bytes) -> str:
    """The sha1 git assigns to a file's content, which the GitHub contents API reports as ``sha``."""
    return hashlib.sha1(  # noqa: S324 - git object id, not a security digest
        b"blob %d\0" % len(data) + data
    ).hexdigest()


def download(url: str, *, timeout: float = TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body: bytes = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise OscalError(f"download failed for {url}: {error}") from error
    if len(body) > MAX_BYTES:
        raise OscalError(f"{url}: larger than {MAX_BYTES} bytes, refusing")
    return body


def build_document(source: OscalSource, corpus: Path, data: bytes) -> Document:
    """Verify, parse and render ``data`` for ``source``; write ``.xml`` and ``.txt`` and return the entry."""
    if git_blob_sha(data) != source.blob:
        raise OscalError(
            f"{source.doc_id}: blob sha does not match the pinned {source.blob}"
        )
    root = parse_catalog(data)
    title, date, status = catalog_metadata(root)
    for field, actual, recorded in (
        ("title", title, source.title),
        ("date", date, source.date),
        ("status", status, source.status),
    ):
        if actual != recorded:
            raise OscalError(
                f"{source.doc_id}: catalogue {field} is {actual!r}, sources.toml says {recorded!r}"
            )
    text, sections = render_catalog(root)
    if not sections:
        raise OscalError(f"{source.doc_id}: catalogue has no controls")
    (corpus / f"{source.doc_id}.xml").write_bytes(data)
    (corpus / f"{source.doc_id}.txt").write_text(text, encoding="utf-8", newline="")
    return Document(
        doc_id=source.doc_id,
        number=source.number,
        title=source.title,
        date=source.date,
        status=source.status,
        url=source.url,
        sha256=sha256_bytes(data),
        text_file=f"{source.doc_id}.txt",
        sections=sections,
    )


def merge_into_index(index_path: Path, new: list[Document]) -> None:
    """Add or replace ``new`` in the index, leaving every other entry exactly as it is."""
    existing: list[Document] = []
    if index_path.exists():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise OscalError(
                f"{index_path} is unreadable, not overwriting it: {error}"
            ) from error
        if not isinstance(raw, dict) or raw.get("schema") != 1:
            raise OscalError(
                f"{index_path} is not a schema 1 index, not overwriting it"
            )
        existing = read_index(index_path)
        if len(existing) != len(raw.get("documents", [])):
            raise OscalError(
                f"{index_path} has entries that do not parse, not overwriting it"
            )
    replaced = {d.doc_id for d in new}
    by_id = {d.doc_id: d for d in new}
    merged = [by_id.get(d.doc_id, d) for d in existing]
    merged.extend(d for d in new if d.doc_id not in {e.doc_id for e in existing})
    assert {d.doc_id for d in merged} >= replaced
    write_index(index_path, merged)


def run(
    data_dir: Path,
    from_files: dict[str, Path],
    only: Sequence[str],
    *,
    sleep: float = THROTTLE_SECONDS,
) -> int:
    sources = load_oscal_sources(sources_file(data_dir))
    known = {s.doc_id for s in sources}
    unknown = sorted((set(from_files) | set(only)) - known)
    if unknown:
        raise OscalError(
            f"not an [[oscal]] entry in sources.toml: {', '.join(unknown)}"
        )
    corpus = data_dir / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    wanted = set(only) | set(from_files) if (only or from_files) else known
    documents: list[Document] = []
    failures = 0
    requests = 0
    for source in sources:
        if source.doc_id not in wanted:
            continue
        try:
            if source.doc_id in from_files:
                data = from_files[source.doc_id].read_bytes()
            else:
                if requests:
                    time.sleep(sleep)
                requests += 1
                data = download(source.url)
            document = build_document(source, corpus, data)
        except (OscalError, OSError) as error:
            print(f"{source.doc_id}: {error}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"{source.doc_id}: {len(document.sections)} controls, sha256 {document.sha256[:12]}"
        )
        documents.append(document)
    if documents:
        merge_into_index(corpus / "index.json", documents)
        print(
            f"updated {corpus / 'index.json'} with {len(documents)} OSCAL document(s)"
        )
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m primarysource.nist.ingest.oscal", description=__doc__
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="directory holding sources.toml and corpus/ (default: $NISTLIB_DATA, else the collection's home)",
    )
    parser.add_argument(
        "--from-file",
        action="append",
        default=[],
        metavar="DOC_ID=PATH",
        help="use a catalogue file you already have for DOC_ID instead of downloading it (repeatable)",
    )
    parser.add_argument(
        "doc_ids", nargs="*", help="only these documents (default: all)"
    )
    args = parser.parse_args(argv)
    from_files: dict[str, Path] = {}
    for value in args.from_file:
        doc_id, sep, path = value.partition("=")
        if not sep or not doc_id or not path:
            print(f"--from-file expects DOC_ID=PATH, got {value!r}", file=sys.stderr)
            return 2
        from_files[doc_id] = Path(path)
    try:
        return run(args.data_dir, from_files, args.doc_ids)
    except OscalError as error:
        print(f"nistlib-oscal: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
