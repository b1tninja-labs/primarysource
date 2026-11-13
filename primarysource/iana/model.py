"""IANA registry XML as rows with their citations.

The format (checked 2026-11-13 against the files themselves and their RELAX NG, `_support/iana-registry.rng`):
a root `<registry id="<file name>">` in the namespace `http://www.iana.org/assignments` holds a `title`, an
`updated` date, sub-`<registry id=...>` elements (which may nest) and a `<people>` table. A registry holds
`registration_rule`, `expert`, `note`, `range` and `xref` metadata and `<record>` rows. A record's columns are
ordinary child elements whose names differ per registry (`value`, `name`, `description`, `type`, `code`,
`length`, ...), plus `xref` citations; `date` and `updated` attributes mark when it was added or changed.

This module takes a parsed tree and makes it into frozen dataclasses. It never reads a file and never fetches.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - elements come from xmlsafe.parse; nothing is parsed here
from dataclasses import dataclass, field

from primarysource.errors import LibError

NAMESPACE = "http://www.iana.org/assignments"
_NS = "{" + NAMESPACE + "}"
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
_RFC = re.compile(r"(rfc|bcp|std)(\d+)")
_NUMBER = r"(?:0[xX][0-9A-Fa-f]+|\d+)"
_RANGE = re.compile(rf"\s*({_NUMBER})(?:\s*-\s*({_NUMBER}))?\s*")
_SPACE = re.compile(r"\s+")


def _local(element: ET.Element) -> str:
    tag = element.tag
    return tag[len(_NS) :] if tag.startswith(_NS) else tag


def _squash(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class Xref:
    """One `<xref>`: what a registry row or note cites. `kind` is the schema's `type`: rfc, rfc-errata, draft,
    uri, registry, person, note or text. `fragment` is the part cited (`Section 3`, `Appendix A`), or empty;
    `section` is the section number alone, for a ref the `rfc` collection can read."""

    kind: str
    data: str
    fragment: str = ""
    section: str = ""
    text: str = ""

    @property
    def rfc(self) -> str:
        """`RFC4271`, `BCP14` or `STD5` for an rfc xref, else empty."""
        match = _RFC.fullmatch(self.data) if self.kind == "rfc" else None
        return f"{match[1].upper()}{match[2]}" if match else ""

    @property
    def ref(self) -> str:
        """A ref the `rfc` collection reads (`RFC4271§3.1`), or `RFC4271` without a section; empty if not an RFC."""
        if not self.rfc:
            return ""
        return f"{self.rfc}§{self.section}" if self.section else self.rfc

    @property
    def label(self) -> str:
        """How the citation reads in running text: `RFC4271, Section 3`, `draft-ietf-x-00`, `RFC errata 123`."""
        if self.kind == "rfc" and self.rfc:
            base = self.rfc
        elif self.kind == "rfc-errata":
            base = f"RFC errata {self.data}"
        elif self.kind == "note":
            base = f"note {self.data}"
        elif self.kind == "registry":
            base = f"registry {self.data}"
        elif self.kind in ("person", "text"):
            base = self.text or self.data
        else:
            base = self.data
        return f"{base}, {self.fragment}" if self.fragment else base


@dataclass(frozen=True, slots=True)
class Record:
    """A row. `key` is the `<value>` column, else the first column's text. `fields` are the columns in file
    order as (element name, text) with empty ones dropped; `xrefs` every citation under the row."""

    ordinal: int
    key: str
    fields: tuple[tuple[str, str], ...]
    xrefs: tuple[Xref, ...] = ()
    date: str = ""
    updated: str = ""
    id: str = ""

    def field(self, name: str) -> str:
        return next((text for key, text in self.fields if key == name), "")

    def text(self) -> str:
        """One line: `value: 1 | name: OPEN | refs: RFC4271`."""
        parts = [f"{name}: {text}" for name, text in self.fields]
        if self.xrefs:
            parts.append("refs: " + ", ".join(dict.fromkeys(x.label for x in self.xrefs)))
        return " | ".join(parts) if parts else self.key


@dataclass(frozen=True, slots=True)
class Range:
    """A `<range>`: which part of the number space follows which registration rule."""

    value: str
    rule: str
    hex: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class Registry:
    """One `<registry>`: the root's file-level registry and every sub-registry, flattened in file order. `parent`
    is the enclosing registry's id, or empty for the root."""

    id: str
    title: str
    parent: str = ""
    created: str = ""
    updated: str = ""
    rules: tuple[str, ...] = ()
    experts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    ranges: tuple[Range, ...] = ()
    xrefs: tuple[Xref, ...] = ()
    records: tuple[Record, ...] = ()
    footnotes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RegistryFile:
    """One registry file (`dns-parameters.xml`): its registries in file order and the people it names."""

    name: str
    title: str
    updated: str
    registries: tuple[Registry, ...]
    people: dict[str, str] = field(default_factory=dict)

    def registry(self, registry_id: str) -> Registry | None:
        return next((r for r in self.registries if r.id == registry_id), None)

    def children(self, registry_id: str) -> tuple[Registry, ...]:
        return tuple(r for r in self.registries if r.parent == registry_id)


def _xref(element: ET.Element, people: dict[str, str]) -> Xref:
    kind = element.get("type", "")
    data = element.get("data", "")
    fragment = ""
    section = ""
    for attribute in ("section", "appendix", "page", "table", "figure", "anchor"):
        value = element.get(attribute)
        if value:
            fragment = f"anchor {value}" if attribute == "anchor" else f"{attribute.capitalize()} {value}"
            if attribute == "section":
                section = value
            break
    text = _squash("".join(element.itertext()))
    if kind == "person":
        text = people.get(data, "") or data.replace("_", " ")
    return Xref(kind, data, fragment, section, text)


def _inline(element: ET.Element, people: dict[str, str]) -> str:
    """Text with inline xrefs spelled out (`[RFC6762]`), whitespace collapsed."""
    parts = [element.text or ""]
    for child in element:
        if _local(child) == "xref":
            parts.append(f"[{_xref(child, people).label}]")
        else:
            parts.append(_inline(child, people))
        parts.append(child.tail or "")
    return _squash("".join(parts))


def _all_xrefs(element: ET.Element, people: dict[str, str]) -> tuple[Xref, ...]:
    found = [_xref(x, people) for x in element.iter() if _local(x) == "xref"]
    return tuple(dict.fromkeys(found))


def _record(element: ET.Element, ordinal: int, people: dict[str, str]) -> Record:
    columns: list[tuple[str, str]] = []
    for child in element:
        name = _local(child)
        if name == "xref":
            continue
        text = _inline(child, people)
        if text:
            columns.append((name, text))
    key = next((text for name, text in columns if name == "value"), columns[0][1] if columns else "")
    return Record(
        ordinal=ordinal,
        key=key,
        fields=tuple(columns),
        xrefs=_all_xrefs(element, people),
        date=element.get("date", ""),
        updated=element.get("updated", ""),
        id=element.get("id", ""),
    )


def _range(element: ET.Element, people: dict[str, str]) -> Range:
    def column(name: str) -> str:
        child = element.find(_NS + name)
        return _inline(child, people) if child is not None else ""

    return Range(column("value"), column("registration_rule"), column("hex"), column("note"))


def _registry(element: ET.Element, parent: str, people: dict[str, str], out: list[Registry]) -> None:
    registry_id = element.get("id", "")
    if not _ID.fullmatch(registry_id):
        raise LibError(f"a registry has the id {registry_id!r}, which is not an IANA registry id", "")
    slot = len(out)
    out.append(Registry(registry_id, ""))  # keeps file order; replaced below once the children are done
    title = created = updated = ""
    rules: list[str] = []
    experts: list[str] = []
    notes: list[str] = []
    ranges: list[Range] = []
    xrefs: list[Xref] = []
    records: list[Record] = []
    footnotes: list[tuple[str, str]] = []
    for child in element:
        name = _local(child)
        if name == "title":
            title = _inline(child, people)
        elif name == "created":
            created = _squash(child.text or "")
        elif name == "updated":
            updated = _squash(child.text or "")
        elif name == "registration_rule":
            rules.append(_inline(child, people))
        elif name == "expert":
            experts.append(_inline(child, people))
        elif name == "note":
            notes.append(_inline(child, people))
        elif name == "range":
            ranges.append(_range(child, people))
        elif name == "xref":
            xrefs.append(_xref(child, people))
        elif name == "record":
            records.append(_record(child, len(records) + 1, people))
        elif name == "footnote":
            footnotes.append((child.get("anchor", ""), _inline(child, people)))
        elif name == "registry":
            _registry(child, registry_id, people, out)
    out[slot] = Registry(
        registry_id,
        title,
        parent,
        created,
        updated,
        tuple(rules),
        tuple(experts),
        tuple(notes),
        tuple(ranges),
        tuple(dict.fromkeys(xrefs)),
        tuple(records),
        tuple(footnotes),
    )


def from_tree(root: ET.Element, name: str | None = None) -> RegistryFile:
    """Build a `RegistryFile` from a tree parsed by `xmlsafe.parse`. A tree that is not an IANA registry is
    refused; so is a root whose `id` is not `name`, when `name` is given."""
    if root.tag != _NS + "registry":
        raise LibError(
            f"the root element is {root.tag!r}, not an IANA <registry> in {NAMESPACE}",
            "this is not a registry file; check the URL",
        )
    root_id = root.get("id", "")
    if not _ID.fullmatch(root_id):
        raise LibError(f"the root registry has the id {root_id!r}", "this is not a registry file")
    if name is not None and root_id != name:
        raise LibError(f"the file is registry {root_id!r}, not {name!r}", "check the URL against the catalogue")
    people: dict[str, str] = {}
    for person in root.iter(_NS + "person"):
        label = person.find(_NS + "name")
        if person.get("id") and label is not None:
            people[person.get("id", "")] = _squash(label.text or "")
    registries: list[Registry] = []
    _registry(root, "", people, registries)
    top = registries[0]
    return RegistryFile(root_id, top.title, top.updated, tuple(registries), people)


def _int(text: str) -> int:
    """Decimal, or hex with a 0x prefix. Leading zeros are decimal (`010` is ten), unlike `int(text, 0)`."""
    return int(text, 16) if text[:2].lower() == "0x" else int(text, 10)


def numeric_range(text: str) -> tuple[int, int] | None:
    """`6-255` -> (6, 255); `0x0010` -> (16, 16); anything else (a name, `*`, `1.2`) -> None."""
    match = _RANGE.fullmatch(text)
    if match is None:
        return None
    low = _int(match[1])
    high = _int(match[2] or match[1])
    return (low, high) if low <= high else None


def number_of(text: str) -> int | None:
    """A single number (decimal or 0x hex) as an int, else None."""
    span = numeric_range(text)
    return span[0] if span is not None and span[0] == span[1] else None


def matches(record: Record, query: str) -> bool:
    """Does `query` name this row by value? A single number matches a row whose `value` (or `hex`) is that
    number or a range containing it; anything else matches a row whose `value` equals it, ignoring case."""
    wanted = number_of(query)
    if wanted is None:
        return query.strip().casefold() == record.key.casefold()
    for candidate in (record.key, record.field("hex")):
        span = numeric_range(candidate)
        if span is not None and span[0] <= wanted <= span[1]:
            return True
    return False
