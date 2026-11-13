"""A minimal POD reader for the dpkg manual pages, which are `.pod` files in dpkg's `man/` directory.

`=head1`..`=head4` are sections (level 1 to 4). Blocks, the unit: an ordinary paragraph, a verbatim (indented)
paragraph, and an `=item` with every paragraph up to the next item (so a tag and its description are one block,
the way a man page's `.TP` is). `=over` and `=back` only delimit lists; nesting is flattened. `=begin`/`=end`
regions and `=for` lines are dropped, as are `=encoding`, `=pod`, `=cut` and the `#` licence comment that dpkg's
files carry before the first command.

Formatting codes (`B<>`, `I<>`, `C<>`, `F<>`, `S<>`, `L<>`, `E<>`, `X<>`, `Z<>`) are resolved to their text,
including the `C<< ... >>` form, in a fixed number of passes. A paragraph over `MAX_CODED` characters is left
unresolved and the document carries a warning, so a hostile run of `C<<` costs time linear in the input.
"""

from __future__ import annotations

import re

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import Builder, decode

MAX_CODED = 20_000
_PASSES = 12
_ENTITIES = {"lt": "<", "gt": ">", "verbar": "|", "sol": "/", "amp": "&", "quot": '"', "apos": "'", "nbsp": " "}
_WIDE = re.compile(r"([A-Z])(<{2,}) ([^<>]*?) (>{2,})")
_NARROW = re.compile(r"([A-Z])<([^<>]*)>")
_CMD = re.compile(r"=([a-z]+\d?)(?:[ \t]+(.*))?$", re.DOTALL)


def _entity(name: str) -> str:
    if name in _ENTITIES:
        return _ENTITIES[name]
    if name.isdigit():
        return chr(int(name)) if 0 < int(name) < 0x110000 else ""
    if name.lower().startswith("0x") and re.fullmatch(r"0[xX][0-9a-fA-F]{1,6}", name):
        return chr(int(name, 16)) if int(name, 16) < 0x110000 else ""
    return f"&{name};"


def _code(match: re.Match[str]) -> str:
    kind, inner = match.group(1), match.group(2) if match.re is _NARROW else match.group(3)
    if kind == "E":
        return _entity(inner.strip())
    if kind in ("X", "Z"):
        return ""
    if kind == "L":
        label = inner.split("|", 1)[0] if "|" in inner else inner
        return label
    if kind in ("B", "I", "C", "F", "S", "U"):
        return inner
    return match.group(0)


def resolve_codes(text: str) -> str:
    """Resolve POD formatting codes to their text. Unknown letters are left as written."""
    for _ in range(_PASSES):
        after = _NARROW.sub(_code, _WIDE.sub(_code, text))
        if after == text:
            break
        text = after
    return text


def read_pod(data: bytes, doc_id: str, title: str | None = None) -> Doc:
    """Read one POD file. Raises `LibError` for NUL bytes or invalid UTF-8."""
    text = decode(data, f"POD file {doc_id!r}")
    builder = Builder()
    uncoded = 0
    paragraphs = re.split(r"\n[ \t]*\n+", text.strip("\n"))
    item: list[str] | None = None
    skip_region = False
    doc_title = title or ""
    in_name = False
    started = False  # the first `=` command seen

    def emit(block: str) -> None:
        nonlocal item
        if item is not None:
            item.append(block)
        else:
            builder.unit(block)

    def close_item() -> None:
        nonlocal item
        if item is not None:
            builder.unit("\n\n".join(item))
            item = None

    def coded(block: str) -> str:
        nonlocal uncoded
        if len(block) > MAX_CODED:
            uncoded += 1
            return block
        return resolve_codes(block)

    for paragraph in paragraphs:
        if not started and not paragraph.startswith("="):
            lines = [ln for ln in paragraph.split("\n") if not ln.startswith("#")]
            if not lines:
                continue  # the licence comment block
            paragraph = "\n".join(lines)
        command = _CMD.match(paragraph) if paragraph.startswith("=") else None
        if skip_region:
            skip_region = not (command and command.group(1) == "end")
            continue
        if command:
            started = True
            name, argument = command.group(1), (command.group(2) or "").strip()
            if name.startswith("head") and name[4:].isdigit():
                close_item()
                title_text = coded(argument.replace("\n", " "))
                in_name = title_text.strip().upper() == "NAME"
                builder.heading(int(name[4:]), title_text)
            elif name == "item":
                close_item()
                item = [coded(argument)]
            elif name in ("back",):
                close_item()
            elif name == "begin":
                skip_region = True
            continue
        if paragraph.lstrip().startswith("="):
            continue
        body = coded(paragraph.rstrip()) if paragraph[:1] not in " \t" else paragraph.rstrip()
        if in_name and not doc_title:
            doc_title = " ".join(body.split())
        in_name = False
        emit(body)
    close_item()
    warnings = (f"{uncoded} paragraphs over {MAX_CODED} characters left unresolved",) if uncoded else ()
    builder.set_preamble_title(doc_title or doc_id)
    return builder.doc(doc_id, doc_title or doc_id, unit=Unit.BLOCK, warnings=warnings)
