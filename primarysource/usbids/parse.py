"""A bounded parser for the `usb.ids` format, and the ref spelling of its entries.

The file is line-oriented. A `#` line is a comment (the first ones carry `# Version:` and `# Date:`), a blank line
is nothing, and every other line is `<id>  <name>` (two spaces) indented by zero to two tabs. At column zero a
line is either a vendor (`1d6b  Linux Foundation`) or a section record led by an upper-case tag (`C 09  Hub`). One
tab is a child of the last column-zero entry (a device of a vendor, a subclass of a class, a usage of a usage
page, a dialect of a language), two tabs a child of the last one-tab entry (an interface of a device, a protocol
of a subclass). The sections the file has today, from its own `# Syntax:` comments:

    (none)  vendor > device > interface     C     class > subclass > protocol
    AT      audio terminal type             HID   HID descriptor type
    R       HID item type                   BIAS  physical descriptor bias
    PHY     physical descriptor item type   HUT   usage page > usage
    L       language > dialect              HCC   HID country code (decimal)
    VT      video terminal type

Nothing here reads a file or the network. `parse` takes bytes and `Limits`, never trusts a line, and reports a
line it cannot place as a `Problem` instead of guessing: the real file parses with none. Ids are lower-cased,
names are kept as written, less surrounding space (a line that is not valid UTF-8 is read as Latin-1
and counted), and a repeated id keeps its first entry and is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from primarysource.errors import LibError

SECTION_REF = {
    "vendor": "vendor",
    "class": "class",
    "at": "at",
    "hid": "hid",
    "item": "item",
    "bias": "bias",
    "phy": "phy",
    "hut": "hut",
    "lang": "lang",
    "hcc": "hcc",
    "vt": "vt",
}
"""The first path part of a non-vendor ref, by section name. A vendor ref has no section part: `usbids:1d6b`."""

TAGS = {
    "C": "class",
    "AT": "at",
    "HID": "hid",
    "R": "item",
    "BIAS": "bias",
    "PHY": "phy",
    "HUT": "hut",
    "L": "lang",
    "HCC": "hcc",
    "VT": "vt",
}
"""The file's tag for each section."""

LEVELS = {
    "vendor": ("vendor", "device", "interface"),
    "class": ("class", "subclass", "protocol"),
    "at": ("terminal type",),
    "hid": ("descriptor type",),
    "item": ("item type",),
    "bias": ("bias",),
    "phy": ("item type",),
    "hut": ("usage page", "usage"),
    "lang": ("language", "dialect"),
    "hcc": ("country code",),
    "vt": ("terminal type",),
}
"""What each indentation level of a section is called, for `usbids_lookup` output."""

_HEX2 = r"[0-9a-f]{2}"
_HEX4 = r"[0-9a-f]{4}"
ID_PATTERNS: dict[str, tuple[str, ...]] = {
    "vendor": (_HEX4, _HEX4, r"[0-9a-f]{2,4}"),
    "class": (_HEX2, _HEX2, _HEX2),
    "at": (_HEX4,),
    "hid": (_HEX2,),
    "item": (_HEX2,),
    "bias": (r"[0-9a-f]{1,2}",),
    "phy": (_HEX2,),
    "hut": (_HEX2, r"[0-9a-f]{3,4}"),
    "lang": (_HEX4, _HEX2),
    "hcc": (r"[0-9]{2}",),
    "vt": (_HEX4,),
}
"""The shape of the id at each level. `hcc` is decimal (the file says HID country codes are 00 to 35)."""

_ID = {section: tuple(re.compile(p) for p in patterns) for section, patterns in ID_PATTERNS.items()}
_LINE = re.compile(r"(?P<tabs>\t{0,3})(?:(?P<tag>[A-Z]{1,4}) )?(?P<id>[0-9A-Za-z]{1,8})  +(?P<name>\S.*)")
_VERSION = re.compile(r"#\s*Version:\s*(\S+)")
_DATE = re.compile(r"#\s*Date:\s*(.+?)\s*$")
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class Limits:
    """Ceilings on what a parse accepts. The real file measures 730,605 bytes, 25,705 lines, the longest line
    160 characters."""

    data_bytes: int = 8_000_000
    lines: int = 200_000
    line_chars: int = 512
    entries: int = 200_000
    problems: int = 1_000
    """Problems are counted without limit but only this many are kept."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One record: `section`, the ids from the top down (`("1d6b", "0002")`), the name and its 1-based line."""

    section: str
    key: tuple[str, ...]
    name: str
    line: int

    @property
    def ref(self) -> str:
        return format_ref(self.section, self.key)

    @property
    def level_name(self) -> str:
        return LEVELS[self.section][len(self.key) - 1]


@dataclass(frozen=True, slots=True)
class Problem:
    line: int
    reason: str


@dataclass(slots=True)
class UsbIds:
    """A parsed file: entries in file order, the children of each, and what was wrong."""

    entries: dict[tuple[str, tuple[str, ...]], Entry] = field(default_factory=dict)
    children: dict[tuple[str, tuple[str, ...]], list[Entry]] = field(default_factory=dict)
    version: str = ""
    date: str = ""
    problems: list[Problem] = field(default_factory=list)
    problem_count: int = 0
    latin1_lines: int = 0
    """Lines that were not valid UTF-8 and were read as Latin-1."""

    def get(self, section: str, key: tuple[str, ...]) -> Entry | None:
        return self.entries.get((section, key))

    def kids(self, entry: Entry) -> list[Entry]:
        return self.children.get((entry.section, entry.key), [])

    def counts(self) -> dict[str, int]:
        """Entries per kind in first-seen order: `vendor`, `device`, `class`, `subclass`, `protocol`, `usage page`,
        `usage`, `language`, `dialect`, and one count under the section's own name (`at`, `hid`, `item`, `bias`,
        `phy`, `hcc`, `vt`) for the single-level tables."""
        out: dict[str, int] = {}
        for entry in self.entries.values():
            label = entry.level_name if entry.section in ("vendor", "class", "hut", "lang") else entry.section
            out[label] = out.get(label, 0) + 1
        return out


def parse(data: bytes, limits: Limits | None = None) -> UsbIds:
    """Parse `usb.ids` bytes. Raises `LibError` for input that is not this format at all (too large,
    NUL bytes, too many lines or entries); a bad line inside an otherwise sound file is a `Problem`."""
    limits = limits or Limits()
    if len(data) > limits.data_bytes:
        raise LibError(f"usb.ids input is {len(data):,} bytes, over the {limits.data_bytes:,} limit", "")
    if b"\x00" in data:
        raise LibError("usb.ids input contains NUL bytes: this is not the text file", "")
    raw_lines = data.removeprefix(b"\xef\xbb\xbf").split(b"\n")
    if len(raw_lines) > limits.lines:
        raise LibError(f"usb.ids input has over {limits.lines:,} lines", "")
    ids = UsbIds()

    def problem(number: int, reason: str) -> None:
        ids.problem_count += 1
        if len(ids.problems) < limits.problems:
            ids.problems.append(Problem(number, reason))

    parents: list[Entry | None] = [None, None, None]
    for number, raw_bytes in enumerate(raw_lines, 1):
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # The published file is UTF-8 with a few Latin-1 bytes (an acute accent written as 0xB4)
            raw = raw_bytes.decode("latin-1")
            ids.latin1_lines += 1
        line = raw.rstrip(" \t\r")
        if not line:
            continue
        if line.startswith("#"):
            if not ids.version and (m := _VERSION.match(line)):
                ids.version = m[1]
            elif not ids.date and (m := _DATE.match(line)):
                ids.date = m[1]
            continue
        if len(line) > limits.line_chars:
            problem(number, f"line over {limits.line_chars} characters")
            continue
        if _CONTROL.search(line):
            problem(number, "control character")
            continue
        match = _LINE.fullmatch(line)
        if match is None:
            problem(number, "not '<id>  <name>'")
            continue
        level = len(match["tabs"])
        tag = match["tag"]
        if level > 2 or (level > 0 and tag):
            problem(number, "indentation or tag not allowed here")
            continue
        if level == 0:
            if tag is None:
                section = "vendor"
            elif tag in TAGS:
                section = TAGS[tag]
            else:
                problem(number, f"unknown section tag {tag!r}")
                parents[:] = [None, None, None]
                continue
            parent_key: tuple[str, ...] = ()
        else:
            parent = parents[level - 1]
            if parent is None:
                problem(number, "indented line with no parent")
                continue
            section, parent_key = parent.section, parent.key
        patterns = _ID[section]
        if level >= len(patterns):
            problem(number, f"a {section} section has no level {level}")
            continue
        entry_id = match["id"].lower()
        if patterns[level].fullmatch(entry_id) is None:
            problem(number, f"{entry_id!r} is not a valid {LEVELS[section][level]} id")
            continue
        entry = Entry(section, (*parent_key, entry_id), match["name"], number)
        index = (entry.section, entry.key)
        if index in ids.entries:
            problem(number, f"duplicate {entry.ref}")
            parents[level:] = [None] * (3 - level)
            continue
        if len(ids.entries) >= limits.entries:
            raise LibError(f"usb.ids input has over {limits.entries:,} entries", "")
        ids.entries[index] = entry
        if level > 0:
            ids.children.setdefault((section, parent_key), []).append(entry)
        parents[level:] = [entry] + [None] * (2 - level)
    return ids


_VENDOR_REF = re.compile(r"(?P<v>[0-9a-f]{4})(?::(?P<d>[0-9a-f]{4})(?::(?P<i>[0-9a-f]{2,4}))?)?")
_SECTION_REF = re.compile(r"(?P<s>[a-z]+)(?P<path>(?:/[0-9a-f]{1,4}){1,3})")


def format_ref(section: str, key: tuple[str, ...]) -> str:
    """`usbids:1d6b:0002` for the vendor section, `usbids:class/09/00` for the others."""
    if section == "vendor":
        return "usbids:" + ":".join(key)
    return f"usbids:{section}/" + "/".join(key)


def parse_ref(text: str) -> tuple[str, tuple[str, ...]]:
    """`usbids:1d6b:0002`, `1d6b:0002`, `usbids:class/09/00/02` -> (section, ids). Raises `LibError` on anything
    else: a string that names nothing is refused, never guessed at."""
    cleaned = text.strip().lower()
    if len(cleaned) > 64:
        raise LibError("not a usbids ref: too long", "")
    cleaned = cleaned.removeprefix("usbids:")
    if (m := _VENDOR_REF.fullmatch(cleaned)) is not None:
        return "vendor", tuple(g for g in (m["v"], m["d"], m["i"]) if g)
    if (m := _SECTION_REF.fullmatch(cleaned)) is not None and m["s"] in SECTION_REF and m["s"] != "vendor":
        key = tuple(m["path"].split("/")[1:])
        patterns = _ID[m["s"]]
        if len(key) <= len(patterns) and all(p.fullmatch(k) for p, k in zip(patterns, key, strict=False)):
            return m["s"], key
    names = ", ".join(sorted(set(SECTION_REF) - {"vendor"}))
    raise LibError(
        f"not a usbids ref: {text!r}",
        f"expected usbids:<vid>[:<pid>] (hex) or usbids:<section>/<id>[/<id>...] with section one of {names}",
    )
