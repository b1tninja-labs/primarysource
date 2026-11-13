"""The usbids readers: lookup, search, classify and a summary. Plain text with the core's fixed footer.

Each takes the imported database from `store.load()` and never writes or fetches. A missing database is an
error whose `action` is the import command; a ref that names nothing is a `LibError` too, with a hint, so an empty
result always means a search matched nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from primarysource import budget, cursor
from primarysource.errors import LibError
from primarysource.render import next_start, render
from primarysource.usbids import store
from primarysource.usbids.parse import SECTION_REF, Entry, UsbIds, format_ref, parse_ref

MAX_QUERY = 200
MAX_TERMS = 8
MAX_LIMIT = 200
_WORD = re.compile(r"[a-z0-9]+")
_HEX2 = re.compile(r"[0-9a-fA-F]{1,2}")


def _cite(loaded: store.Loaded, entry: Entry | None = None) -> str:
    ids = loaded.ids
    head = f"USB ID Database usb.ids {ids.version or 'unversioned'}" + (f" ({ids.date})" if ids.date else "")
    return f"{head}, {entry.ref}" if entry else head


def _line(entry: Entry) -> str:
    return f"{entry.ref}  {entry.name}"


def _ancestors(ids: UsbIds, entry: Entry) -> list[Entry]:
    found: list[Entry] = []
    for depth in range(1, len(entry.key)):
        parent = ids.get(entry.section, entry.key[:depth])
        if parent is not None:
            found.append(parent)
    return found


def lookup(ref: str, max_tokens: int = 2000, base: Path | None = None) -> str:
    """One entry by ref, its ancestors and its children, paged by token budget. `<ref>¶n` starts at line n of that
    listing; the `next:` footer is the ref that reads the next page."""
    text, line = cursor.split_para(ref)
    section, key = parse_ref(text)
    loaded = store.load(base)
    ids = loaded.ids
    entry = ids.get(section, key)
    if entry is None:
        parent = ids.get(section, key[:-1]) if len(key) > 1 else None
        if parent is not None:
            raise LibError(
                f"{format_ref(section, key)} is not listed; its {parent.level_name} is {parent.name!r}",
                f"usbids_lookup('{parent.ref}') lists what is under it",
            )
        raise LibError(
            f"{format_ref(section, key)} is not in usb.ids {ids.version}", "usbids_search finds an entry by name"
        )
    units = [f"{_line(entry)}  [{entry.level_name}]"]
    units += [f"within: {_line(a)}  [{a.level_name}]" for a in _ancestors(ids, entry)]
    units += [f"  {_line(kid)}" for kid in ids.kids(entry)]
    if max_tokens < 1:
        raise LibError("max_tokens must be positive", "")
    page = budget.page(units, cursor.first_unit(line, len(units), "lines", ref), max_tokens)
    footer = {
        "cite": _cite(loaded, entry),
        "unit": "line",
        "span": f"{page.first}-{page.last} of {page.total}",
        "next": cursor.read_next(entry.ref, page),
    }
    return render("\n".join(page.units), footer)


def search(
    text: str,
    section: str | None = None,
    limit: int = 20,
    start: int = 0,
    base: Path | None = None,
) -> str:
    """Entries whose name contains every word of `text` (a vendor's name counts for its devices), best first."""
    if section is not None and section not in SECTION_REF:
        raise LibError(f"unknown section {section!r}", "one of " + ", ".join(sorted(SECTION_REF)))
    if len(text) > MAX_QUERY:
        raise LibError(f"query is over {MAX_QUERY} characters", "")
    terms = _WORD.findall(text.lower())[:MAX_TERMS]
    if not terms:
        raise LibError("query has no letters or digits", "give a name or part of one, e.g. 'hub' or 'logitech'")
    if not 1 <= limit <= MAX_LIMIT or start < 0:
        raise LibError(f"limit must be 1 to {MAX_LIMIT} and start (0-based) 0 or more", "")
    loaded = store.load(base)
    ids = loaded.ids
    hits: list[tuple[int, int, Entry, str]] = []
    for order, entry in enumerate(ids.entries.values()):
        if section is not None and entry.section != section:
            continue
        shown = entry.name
        hay = entry.name.lower()
        if entry.section == "vendor" and len(entry.key) > 1:
            owner = ids.get("vendor", entry.key[:1])
            if owner is not None:
                hay = f"{owner.name.lower()} {hay}"
                shown = f"{owner.name} / {entry.name}"
        if not all(t in hay for t in terms):
            continue
        words = _WORD.findall(hay)
        score = sum(3 if t in words else 2 if any(w.startswith(t) for w in words) else 1 for t in terms)
        hits.append((-score, order, entry, shown))
    hits.sort(key=lambda h: (h[0], h[1]))
    window = hits[start : start + limit]
    body = "\n".join(f"{e.ref}  {shown}" for _, _, e, shown in window) if window else f"no entry matches {text!r}"
    footer = {"cite": _cite(loaded), "unit": "line"}
    if window:
        footer["span"] = f"{start + 1}-{start + len(window)} of {len(hits)}"
    footer["next"] = next_start(start + limit if start + limit < len(hits) else None)
    return render(body, footer)


def _two_hex(value: str, what: str) -> str:
    if not _HEX2.fullmatch(value.strip()):
        raise LibError(f"{what} {value!r} is not one or two hex digits", "e.g. 09 or 0xe0")
    return value.strip().lower().zfill(2)


def classify(
    base_class: str, subclass: str | None = None, protocol: str | None = None, base: Path | None = None
) -> str:
    """Name a class code triple as a device or interface descriptor carries it: bDeviceClass, bDeviceSubClass,
    bDeviceProtocol. Digits may be written with or without `0x`."""
    clean = [v.lower().removeprefix("0x") if v is not None else None for v in (base_class, subclass, protocol)]
    if clean[1] is None and clean[2] is not None:
        raise LibError("a protocol needs a subclass", "")
    key: list[str] = []
    for value, what in zip(clean, ("class", "subclass", "protocol"), strict=True):
        if value is not None:
            key.append(_two_hex(value, what))
    loaded = store.load(base)
    ids = loaded.ids
    lines: list[str] = []
    for depth in range(1, len(key) + 1):
        entry = ids.get("class", tuple(key[:depth]))
        if entry is None:
            if depth == 1:
                raise LibError(
                    f"class {key[0]} is not in usb.ids {ids.version}", "usbids_search with section='class'"
                )
            lines.append(f"{format_ref('class', tuple(key[:depth]))}  (not listed in usb.ids)")
            break
        lines.append(f"{_line(entry)}  [{entry.level_name}]")
    return render("\n".join(lines), {"cite": _cite(loaded), "unit": "line"})


def sections(base: Path | None = None) -> str:
    """The imported snapshot: version, date, digest, source, licence and entry counts per section."""
    loaded = store.load(base)
    ids = loaded.ids
    per: dict[str, int] = {}
    for entry in ids.entries.values():
        per[entry.section] = per.get(entry.section, 0) + 1
    man = loaded.manifest
    lines = [
        f"usb.ids {ids.version or 'unversioned'}  date {ids.date or 'unknown'}",
        f"sha256 {loaded.sha256}  ({'pinned snapshot' if man.get('pinned') else 'not the pinned snapshot'})",
        f"source {man.get('url', 'unknown')}  fetched {man.get('fetched', 'unknown')}",
        f"licence {man.get('licence', store.LICENCE)}",
        "entries per section (ref prefix):",
    ]
    lines += [f"  {name}: {count:,}" for name, count in per.items()]
    lines += [f"unparsed lines at import: {ids.problem_count}"]
    return render("\n".join(lines), {"cite": _cite(loaded), "unit": "line"})
