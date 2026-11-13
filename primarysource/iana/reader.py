"""Read, look up and search imported IANA registries. Every function returns text with the fixed footer and raises
a `LibError` that names its remedy; nothing here writes or fetches.

Refs (grammar in `docs/iana.md`):

    dns-parameters                          the file: its registries, each with the ref that reads it
    dns-parameters§dns-parameters-4         one registry: header, then its records
    dns-parameters#dns-parameters-4         the same, in IANA's own URL-fragment spelling
    bgp-parameters§bgp-parameters-2#3       the record(s) whose value is 3 (a range containing 3 counts)
    bgp-parameters§bgp-parameters-2¶4       from the 4th record of the registry, in file order
    bgp-parameters§bgp-parameters-2#3¶2     from the 2nd record whose value is 3
    dns-parameters¶5                        the file's registry listing, from its 5th registry

A read's `next:` footer is the ref that reads the next page; a `¶n` read starts at record n and runs on.
    iana:bgp-parameters§bgp-parameters-2¶4  an `iana:` prefix is accepted and dropped
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from primarysource import cursor
from primarysource.budget import page as budget_page
from primarysource.errors import LibError
from primarysource.iana import catalogue, store
from primarysource.iana.catalogue import BASE, NAME
from primarysource.iana.model import Record, Registry, RegistryFile, matches
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

DOC = r"[a-z0-9][a-z0-9._-]*"
REGISTRY = r"[A-Za-z_][A-Za-z0-9_.\-]*"
_GRAMMAR = RefGrammar(DOC, REGISTRY)
UNIT = "record (¶n is the nth record of the registry, in file order)"
MAX_QUERY = 200
_SNIPPET = 200


@dataclass(frozen=True, slots=True)
class Target:
    """A parsed ref: the file, the registry (None for the file itself), a value to look up and a record ordinal."""

    file: str
    registry: str | None = None
    value: str | None = None
    para: int | None = None


def parse_ref(text: str) -> Target:
    """Parse a ref or raise LibError. With a `§`, the anchor is a value; with no `§`, it names a registry."""
    body = text.strip()
    if body[:5].lower() == "iana:":
        body = body[5:]
    body, listing_para = cursor.split_doc_para(body)
    parsed = _GRAMMAR.parse(body)
    if parsed.lines is not None:
        raise LibError(f"not an iana ref: {text!r}", "registries have no line ranges; use ¶n for the nth record")
    if parsed.doc is None:
        raise LibError(
            f"not an iana ref: {text!r}", "start with the registry file's name, e.g. dns-parameters§dns-parameters-4"
        )
    if parsed.section is not None:
        return Target(parsed.doc, parsed.section, parsed.anchor, parsed.para)
    if parsed.anchor is not None:
        return Target(parsed.doc, parsed.anchor, None, parsed.para)
    if parsed.para is not None:
        raise LibError(f"not an iana ref: {text!r}", "¶n needs a registry: dns-parameters§dns-parameters-4¶2")
    return Target(parsed.doc, None, None, listing_para)


def format_ref(file: str, registry: str | None = None, value: str | None = None, para: int | None = None) -> str:
    out = file
    if registry is not None:
        out += f"§{registry}"
    if value is not None:
        out += f"#{value}"
    if para is not None:
        out += f"¶{para}"
    return out


class IanaRefs:
    """The collection's `RefParser`: `parse_ref` and `format_ref`, with the core's `Ref` carrying the file as `doc`,
    the registry as `section`, a value as `anchor` and the record ordinal as `para`."""

    def parse(self, text: str) -> Ref:
        target = parse_ref(text)
        return Ref(target.file, target.registry, target.para, target.value)

    def format(self, ref: Ref) -> str:
        if ref.doc is None or ref.lines is not None:
            raise LibError(f"not an iana ref: {ref!r}", "an iana ref starts with the registry file's name")
        return format_ref(ref.doc, ref.section, ref.anchor, ref.para)


GRAMMAR = IanaRefs()


def _url(file: str, registry: str | None = None) -> str:
    return f"{BASE}{file}" + (f"#{registry}" if registry and registry != file else "")


def _registry(loaded: store.Loaded, target: Target) -> Registry:
    found = loaded.file.registry(target.registry or "")
    if found is None:
        ids = ", ".join(r.id for r in loaded.file.registries[:6])
        raise LibError(
            f"{target.file} has no registry {target.registry!r} (its registries start: {ids}, ...)",
            f"read {target.file} to list them with their refs",
        )
    return found


def _warning(loaded: store.Loaded) -> str:
    if loaded.digest_ok is False:
        return "the file differs from the sha256 recorded when it was imported; import it again to trust it"
    if loaded.digest_ok is None:
        return "the file has no manifest entry, so its provenance is not recorded"
    return ""


def _header(file: RegistryFile, registry: Registry) -> str:
    lines = [f"{registry.title}  [{registry.id}]  (file updated {file.updated or 'unknown'}"]
    if registry.updated and registry.updated != file.updated:
        lines[0] += f", registry updated {registry.updated}"
    lines[0] += ")"
    lines.append(f"source: {_url(file.name, registry.id)}")
    for rule in registry.rules:
        lines.append(f"registration procedure: {rule}")
    for span in registry.ranges:
        extra = f" (hex {span.hex})" if span.hex else ""
        note = f"; {span.note}" if span.note else ""
        lines.append(f"range {span.value}{extra}: {span.rule}{note}")
    if registry.experts:
        lines.append("expert: " + "; ".join(registry.experts))
    for note in registry.notes:
        lines.append(f"note: {note}")
    for anchor, text in registry.footnotes:
        lines.append(f"footnote {anchor}: {text}")
    if registry.xrefs:
        lines.append("references: " + ", ".join(dict.fromkeys(x.label for x in registry.xrefs)))
    children = [r for r in file.registries if r.parent == registry.id]
    for child in children:
        lines.append(f"sub-registry: {format_ref(file.name, child.id)}  {child.title}")
    return "\n".join(lines)


def _row(record: Record) -> str:
    return f"¶{record.ordinal} {record.text()}"


def _cite(file: RegistryFile, registry: Registry | None = None, record: Record | None = None) -> str:
    title = registry.title if registry else file.title
    out = f'IANA, "{title}"'
    if record is not None:
        out += f", value {record.key}"
    out += f", {_url(file.name, registry.id if registry else None)}, file updated {file.updated or 'unknown'}"
    return out


def read(ref: str, max_tokens: int = 2000, base: Path | None = None) -> str:
    """Read by ref (see the module docstring). Pages are whole records; the `next:` footer is the ref that reads the
    next page."""
    target = parse_ref(ref)
    loaded = store.load(target.file, base)
    file = loaded.file
    if target.registry is None:
        units = tuple(
            f"{'  ' * _depth(file, r)}{format_ref(file.name, r.id)}  {r.title}  ({len(r.records)} records)"
            for r in file.registries
        )
        result = budget_page(units, cursor.first_unit(target.para, len(units), "registries", ref), max_tokens)
        body = f"{file.title}  (file updated {file.updated or 'unknown'})\nsource: {_url(file.name)}\n\n"
        body += "\n".join(result.units)
        footer = {
            "cite": _cite(file),
            "unit": "registry (the listing is in file order)",
            "next": cursor.read_next(file.name, result),
            "warning": _warning(loaded),
        }
        return render(body, footer)
    registry = _registry(loaded, target)
    records: tuple[Record, ...] = registry.records
    if target.value is not None:
        records = tuple(r for r in records if matches(r, target.value or ""))
        if not records:
            return render(
                f"no record in {registry.id} has value {target.value!r}",
                {"cite": _cite(file, registry), "unit": UNIT, "warning": _warning(loaded)},
            )
    if target.para is not None and target.para > len(records):
        where = f"{len(records)} records" + (f" with value {target.value!r}" if target.value is not None else "")
        raise LibError(f"{ref!r}: {registry.id} has {where}", f"read {format_ref(file.name, registry.id)}")
    units = tuple(_row(r) for r in records)
    result = budget_page(units, target.para or 1, max_tokens)
    body = "\n".join(result.units)
    if target.para is None and target.value is None:
        body = _header(file, registry) + "\n\n" + body
    elif target.value is not None:
        body = f"{registry.title}  [{registry.id}]\n\n" + body
    one = records[result.first - 1] if len(result.units) == 1 and (target.para or target.value) else None
    footer = {
        "cite": _cite(file, registry, one),
        "unit": UNIT,
        "span": span_hash(body),
        "next": cursor.read_next(format_ref(file.name, registry.id, target.value), result),
        "warning": _warning(loaded),
    }
    return render(body, footer)


def _depth(file: RegistryFile, registry: Registry) -> int:
    depth = 0
    parent = registry.parent
    while parent:
        depth += 1
        found = file.registry(parent)
        parent = found.parent if found else ""
    return depth


def lookup(where: str, value: str, base: Path | None = None) -> str:
    """The record(s) with this value in a registry, or in every registry of a file if `where` is a file name.

    A single number matches a record whose value is that number or a range containing it (decimal or 0x hex). Any
    other text matches a value equal to it, ignoring case; failing that, a column equal to it (`A` is an RR type)."""
    if not value.strip() or len(value) > MAX_QUERY:
        raise LibError(f"not a value to look up: {value!r}", f"give 1 to {MAX_QUERY} characters")
    target = parse_ref(where)
    loaded = store.load(target.file, base)
    file = loaded.file
    scope = [_registry(loaded, target)] if target.registry else list(file.registries)
    lines: list[str] = []
    pool: list[tuple[Registry, Record]] = []
    for registry in scope:
        hits = [r for r in registry.records if matches(r, value)]
        if not hits:
            wanted = value.strip().casefold()
            hits = [r for r in registry.records if any(text.casefold() == wanted for _, text in r.fields)]
        for record in hits:
            pool.append((registry, record))
    for registry, record in pool:
        lines.append(f"{format_ref(file.name, registry.id, para=record.ordinal)}  {registry.title}: {record.text()}")
    if not lines:
        return render(
            f"no record has value {value!r} in {where}",
            {"cite": _cite(file, scope[0] if len(scope) == 1 else None), "unit": UNIT, "warning": _warning(loaded)},
        )
    only = pool[0][0] if len({r.id for r, _ in pool}) == 1 else None
    footer = {
        "cite": _cite(file, only, pool[0][1] if len(pool) == 1 else None),
        "unit": UNIT,
        "span": span_hash("\n".join(lines)),
        "warning": _warning(loaded),
    }
    return render("\n".join(lines), footer)


def search(text: str, file: str | None = None, limit: int = 20, start: int = 0, base: Path | None = None) -> str:
    """Records whose registry title and columns contain every word of `text` (case-insensitive, literal, at most
    200 characters), across every imported file or one. One line per hit: `<ref>  <registry>: <record>`."""
    words = text.casefold().split()
    if not words or len(text) > MAX_QUERY:
        raise LibError(f"not a search: {text!r}", f"give 1 to {MAX_QUERY} characters")
    names = (file,) if file else store.imported(base)
    if not names:
        raise LibError(
            "no registry is imported",
            "iana_list shows the catalogue",
            "primarysource iana import --all  (or name one, e.g. dns-parameters)",
        )
    hits: list[str] = []
    warnings: list[str] = []
    for name in names:
        if not NAME.fullmatch(name):
            raise LibError(f"{name!r} is not a registry file name", "")
        loaded = store.load(name, base)
        if loaded.digest_ok is False:
            warnings.append(name)
        for registry in loaded.file.registries:
            title = registry.title.casefold()
            for record in registry.records:
                row = record.text()
                if all(w in title or w in row.casefold() for w in words):
                    snippet = row if len(row) <= _SNIPPET else row[: _SNIPPET - 1] + "…"
                    hits.append(f"{format_ref(name, registry.id, para=record.ordinal)}  {registry.title}: {snippet}")
    shown, nxt = cursor.window(hits, start, limit)
    body = "\n".join(shown) if shown else f"no record matches {text!r}"
    footer = {
        "unit": UNIT,
        "next": nxt,
        "warning": ("files differ from their recorded sha256: " + ", ".join(warnings)) if warnings else "",
    }
    return render(body, footer)


def listing(base: Path | None = None) -> str:
    """The catalogue, each registry marked with whether it is imported, its `updated` date and sha256 prefix."""
    root = base or store.home()
    manifest = store.read_manifest(root)
    present = set(store.imported(root))
    lines = []
    for entry in catalogue.ENTRIES:
        recorded = manifest.get(entry.name, {})
        state = (
            f"imported, updated {recorded.get('updated') or '?'}, sha256 {str(recorded.get('sha256', ''))[:12]}"
            if entry.name in present
            else "not imported"
        )
        lines.append(f"{entry.name}  {entry.title}  [{state}]")
    for name in sorted(present - {e.name for e in catalogue.ENTRIES}):
        lines.append(f"{name}  (not in the catalogue)  [imported]")
    return render("\n".join(lines), {})
