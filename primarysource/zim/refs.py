"""The one reference grammar every tool and command accepts.

    devdocs_en_flask§blueprints/index                 an article of a library
    devdocs_en_flask§blueprints/index#why-blueprints  one section (or one API definition) of it
    devdocs_en_flask§blueprints/index¶3               the third block of the converted article
    devdocs_en_flask§blueprints/index#why-blueprints¶2   the second block of that section
    flask§blueprints/index                            the library may be written as any alias that resolves
    flask::blueprints/index                           `::` is the ASCII spelling of `§`
    blueprints/index                                  a bare path, when the tool is also given `library`
    std::vector  (with library "cpp")                 `::` is part of the path when `library` is given and
                                                      there is no `§`: it is only a separator between a library
                                                      and a path when the text names the library itself
    Array%23map  (with library "ruby")                `#` always starts the anchor, so a path that contains a
                                                      literal `#` is written `%23` (and a literal `%` as `%25`)
    flask                                             a library on its own means its main page

`¶n` counts *blocks* of the converted markdown (a paragraph, heading, list item, table or code fence is one
block each): the unit paging and citation share. With an `#anchor` it counts inside that section (`os#os.scandir¶2`
is the second block of that section); without one, inside the article. It is an index into our conversion of the
article, not into the ZIM, so a cite carrying it is only stable for the same zimlore conversion of the same ZIM;
the entry path and anchor are the durable part.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ZimloreError

_PARA = re.compile(r"¶(\d+)$")
_ESCAPED = re.compile(r"%(23|25)")


def _unescape(text: str) -> str:
    return _ESCAPED.sub(lambda m: "#" if m.group(1) == "23" else "%", text)


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("#", "%23")


@dataclass(frozen=True)
class Ref:
    book: str  # as written: a library name or alias, "" when the ref was a bare path
    path: str  # ZIM entry path, "" for the library's main page
    anchor: str = ""
    para: int | None = None

    def __str__(self) -> str:
        return format_ref(self.book, self.path, self.anchor, self.para)


def format_ref(book: str, path: str, anchor: str = "", para: int | None = None) -> str:
    text = f"{book}§{_escape(path)}" if path else book
    if anchor:
        text += f"#{anchor}"
    if para is not None:
        text += f"¶{para}"
    return text


def parse_ref(text: str, default_book: str = "") -> Ref:
    raw = text.strip()
    if not raw:
        raise ZimloreError("empty reference", "give a library name or library§path, e.g. flask§blueprints/index")
    para: int | None = None
    match = _PARA.search(raw)
    if match:
        para = int(match.group(1))
        if para < 1:
            raise ZimloreError(f"{text!r}: ¶ numbers start at 1")
        raw = raw[: match.start()]
    if "§" in raw:
        sep = "§"
    elif "::" in raw and not default_book:
        sep = "::"  # with a library given, `::` belongs to the path (C++ `std::vector`, Ruby `Foo::Bar`)
    else:
        sep = ""
    if sep:
        book, _, rest = raw.partition(sep)
    elif default_book:
        book, rest = default_book, raw
    else:
        book, rest = raw, ""
    path, _, anchor = rest.partition("#")
    book = book.strip()
    if not book:
        raise ZimloreError(f"{text!r} names no library", "write library§path, or pass the library separately")
    return Ref(book, _unescape(path.strip()).lstrip("/"), anchor.strip(), para)
