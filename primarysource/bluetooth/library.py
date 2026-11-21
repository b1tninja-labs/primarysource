"""Read, outline, search and cite imported Bluetooth specifications. Local files only.

A ref is `bluetooth:battery-service§1.1¶2`. The prefix is optional. `§` is a section number (`1.1`, or
`4.E.1` for Core Specification volume 4 part E). `¶n` is the nth block of that section.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from primarysource import budget, cursor, index
from primarysource.bluetooth.catalogue import DOC, SECTION, Spec
from primarysource.bluetooth.sync import EXTRACTED, INDEX, SYNC, read_catalog
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import Document, Section, Unit, span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render
from primarysource.standing import Edition as Standing
from primarysource.standing import join as join_warning
from primarysource.standing import notes as standing_notes
from primarysource.standing import warning as standing_warning

PREFIX = "bluetooth:"
_ADOPTED = {"adopted", "approved"}
REBUILD = "primarysource bluetooth index"
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)


def grammar() -> RefGrammar:
    return RefGrammar(DOC, SECTION)


def default_home() -> Path:
    return collection_home("bluetooth")


def _version_order(version: str) -> int:
    """``1.10`` is later than ``1.9``, and ``1.0.1`` is later than ``1.0``.

    Zero when the version is not dotted numbers.
    """
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            return 0
        parts.append(min(int(digits), 999))
    if not parts or len(parts) > 4:
        return 0
    order = 0
    for part in (parts + [0, 0, 0, 0])[:4]:
        order = order * 1000 + part
    return order


def standing_for(doc: str, specs: list[Spec], imported: set[str]) -> str:
    """A later adopted version of the same catalog title. A draft is not the text that replaces an adopted one."""
    mine = next((spec for spec in specs if spec.doc == doc), None)
    order = _version_order(mine.version) if mine is not None else 0
    if mine is None or not order:
        return ""
    family = []
    for spec in specs:
        if spec.title != mine.title:
            continue
        spec_order = _version_order(spec.version)
        if not spec_order:
            continue
        family.append(
            Standing(
                f"{PREFIX}{spec.doc}",
                spec_order,
                current=spec.status.casefold() in _ADOPTED,
                imported=spec.doc in imported,
            )
        )
    reading = next((item for item in family if item.ref == f"{PREFIX}{doc}"), None)
    if reading is None:
        return ""
    return standing_warning(reading, family)


def _imported(home: Path) -> set[str]:
    folder = home / EXTRACTED
    if not folder.is_dir():
        return set()
    return {path.stem for path in folder.glob("*.json")}


def _catalog(home: Path) -> list[Spec]:
    try:
        return read_catalog(home)
    except LibError:
        return []


def parse_ref(text: str) -> Ref:
    body = text.strip()
    if body.casefold().startswith(PREFIX):
        body = body[len(PREFIX) :]
    ref = grammar().parse(body)
    if ref.lines is not None or ref.anchor is not None:
        raise LibError(f"not a bluetooth ref: {text!r}", "bluetooth refs are <doc>§<section>[¶n]")
    if ref.doc is None:
        raise LibError(f"not a bluetooth ref: {text!r}", "start with the specification, e.g. battery-service")
    return ref


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    home = home or default_home()
    ref = parse_ref(ref_text)
    document, section, units = _select(home, ref)
    if not units:
        raise LibError(f"{ref_text}: that section has no text of its own", "bluetooth_outline lists the sections")
    first = cursor.first_unit(ref.para, len(units), "blocks", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    scope = f"{PREFIX}{document.id}" + (f"§{section.id}" if section else "")
    footer = {
        "cite": _cite(document, section, cursor.para_label(ref.para, chosen)),
        "unit": "block",
        "span": span_hash("\n\n".join(chosen.units)),
        "next": cursor.read_next(scope, chosen),
        "warning": standing_for(document.id, _catalog(home), _imported(home)),
    }
    return render("\n\n".join(chosen.units), footer)


def outline(doc: str, start: int = 0, limit: int = 200, home: Path | None = None) -> str:
    home = home or default_home()
    document = _load(home, parse_ref(doc).doc or doc)
    rows = [
        f"{'  ' * max(section.depth - 1, 0)}{section.id}  {section.title}  {PREFIX}{document.id}§{section.id}"
        for section in document.sections
    ]
    shown, nxt = cursor.window(rows, start, limit)
    return render("\n".join([document.title, *shown]), {"next": nxt})


def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0, home: Path | None = None) -> str:
    home = home or default_home()
    if not any((home / EXTRACTED).glob("*.json")):
        raise LibError("no Bluetooth specifications are imported", "bluetooth_docs lists the catalog", SYNC)
    wanted = parse_ref(doc).doc if doc else None
    conn = index.open_read(home / INDEX, rebuild_command=REBUILD)
    try:
        found = index.search(conn, query, ranking=RANKING, limit=400)
    finally:
        conn.close()
    hits = [hit for hit in found.hits if wanted is None or hit.doc_id == wanted]
    if not hits:
        return render("no matches", {})
    shown, nxt = cursor.window(hits, start, limit)
    specs, imported = _catalog(home), _imported(home)
    lines = [f"{PREFIX}{hit.doc_id}§{hit.section_id}  {hit.title}" for hit in shown]
    footer = {
        "next": nxt,
        "relaxed": "only some query words matched" if found.relaxed else "",
        "warning": join_warning(
            *standing_notes((f"{PREFIX}{hit.doc_id}", standing_for(hit.doc_id, specs, imported)) for hit in shown)
        ),
    }
    return render("\n".join(lines), footer)


def cite(ref_text: str, home: Path | None = None) -> str:
    home = home or default_home()
    ref = parse_ref(ref_text)
    document, section, units = _select(home, ref)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the section has {len(units)} blocks", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    label = f"{PREFIX}{document.id}" + (f"§{section.id}" if section else "") + (f"¶{ref.para}" if ref.para else "")
    return render(
        label,
        {
            "cite": _cite(document, section, ref.para),
            "unit": "block",
            "span": span_hash("\n\n".join(units)),
            "warning": standing_for(document.id, _catalog(home), _imported(home)),
        },
    )


def docs(home: Path | None = None, *, start: int = 0, limit: int = 50) -> str:
    home = home or default_home()
    specs = read_catalog(home)
    rows = []
    for spec in specs:
        stored = (home / EXTRACTED / f"{spec.doc}.json").is_file()
        state = "imported" if stored else "not imported"
        rows.append(f"{PREFIX}{spec.doc}  {spec.version}  {spec.status}  {state}  {spec.title}")
    shown, nxt = cursor.window(rows, start, limit)
    return render("\n".join(shown), {"next": nxt})


def build_index(home: Path | None = None) -> int:
    home = home or default_home()
    return index.rebuild(home / INDEX, _documents(home), rebuild_command=REBUILD)


def _documents(home: Path) -> list[Document]:
    found: list[Document] = []
    folder = home / EXTRACTED
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        loaded = _read_json(path)
        sections = tuple(
            Section(
                str(item["id"]),
                str(item["title"]),
                tuple(str(unit) for unit in item.get("units", [])),
                int(item["depth"]),
            )
            for item in loaded["sections"]
            if isinstance(item, dict)
        )
        found.append(Document(str(loaded["doc"]), str(loaded["title"]), Unit.BLOCK, sections))
    return found


def _select(home: Path, ref: Ref) -> tuple[Document, Section | None, tuple[str, ...]]:
    document = _load(home, ref.doc or "")
    if ref.section is None:
        units: list[str] = []
        for section in document.sections:
            units.append(f"§{section.id} {section.title}")
            units.extend(section.units)
        return document, None, tuple(units)
    for section in document.sections:
        if section.id == ref.section:
            return document, section, section.units
    have = ", ".join(section.id for section in document.sections[:12])
    raise LibError(f"no section {ref.section} in {document.id}", f"sections include: {have}" if have else "")


def _load(home: Path, doc: str) -> Document:
    path = home / EXTRACTED / f"{doc}.json"
    if not path.is_file():
        raise LibError(f"{doc} is not imported", "bluetooth_docs lists the catalog", SYNC)
    loaded = _read_json(path)
    sections = tuple(
        Section(
            str(item["id"]),
            str(item["title"]),
            tuple(str(unit) for unit in item.get("units", [])),
            int(item["depth"]),
        )
        for item in loaded["sections"]
        if isinstance(item, dict)
    )
    return Document(doc, str(loaded.get("title") or doc), Unit.BLOCK, sections)


def _cite(document: Document, section: Section | None, para: int | str | None) -> str:
    where = f", §{section.id} {section.title}" if section else ""
    if para:
        where += f" ¶{para}"
    return f"{document.title}{where}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"cannot read {path.name}: {exc}", "", SYNC) from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("sections"), list):
        raise LibError(f"{path.name} is not an imported specification", "", SYNC)
    return loaded
