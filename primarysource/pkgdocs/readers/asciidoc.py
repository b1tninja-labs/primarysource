"""A minimal AsciiDoc reader for git's Documentation: sections, blocks, anchors; nothing is executed or opened.

What it reads:

- the document title (`= Title`, or a line underlined with `=`) is the document's title, not a section;
- sections by `==` ... `======` or by an underline of `-` (level 1), `~` (2), `^` (3), `+` (4) whose length is
  within one of the title's, as asciidoc requires;
- explicit anchors `[[id]]`, `[[id,text]]`, `[#id]` and `[id=...]` before a heading, else the GitHub-style slug;
- blocks (the unit, so `¶n` counts blocks): a run of non-blank lines; a delimited block (`----`, `....`, `====`,
  `****`, `____`, `++++`, a `|===` table) as one block with its delimiters dropped; and every labelled-list term
  (`-a::`) or list marker (`* `, `. `, `1. `) starts a new block even without a blank line before it;
- a block title (`.Title`) leads the block it titles.

What it does not do, by design:

- `include::path[]` is **never read**. It becomes the block `[include] path`, so the text says where the rest is;
  the included file is its own document in the same collection;
- `ifdef::`/`ifndef::`/`ifeval::`/`endif::` lines are dropped and their content kept unconditionally, and the
  document carries a warning with the count, because the condition's result is the build's, not the text's;
- attribute entries (`:name: value`), comments (`//`, `////` blocks), block attribute lines (`[verse]`) and the
  `+` list continuation marker are dropped;
- inline markup (`linkgit:`, backticks, `'emphasis'`) is left as written.
"""

from __future__ import annotations

import re

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import Builder, decode

_UNDERLINE_LEVEL = {"=": 0, "-": 1, "~": 2, "^": 3, "+": 4}
_ATX = re.compile(r"(={1,6}) +(\S.*)")
_DELIM = re.compile(r"(-{4,}|\.{4,}|={4,}|\*{4,}|_{4,}|\+{4,}|/{4,}|[|!,:]={3,})")
_LIST = re.compile(r"\s*(?:\*{1,5}|-|\.{1,5}|\d{1,3}\.|[a-zA-Z]\.)\s+\S")
_TERM = re.compile(r"\S.*?(?:::|;;|:::|::::)(?:\s|$)")
_ATTR_ENTRY = re.compile(r":!?[\w][\w-]*!?:(?:\s.*)?")
_COND_PREFIXES = ("ifdef::", "ifndef::", "ifeval::", "endif::")
_ANCHOR = re.compile(r"\[\[([A-Za-z_][\w.:-]*)(?:,[^\]]*)?\]\]\s*")
_ATTRLINE = re.compile(r"\[(?!\[)[^\]]*\]\s*")
_BLOCKTITLE = re.compile(r"\.[^\s.].*")


def _is_underline(line: str, title: str) -> int | None:
    """The level an underline gives `title`, or None when `line` is not its underline."""
    if len(line) < 2 or line[0] not in _UNDERLINE_LEVEL or line.count(line[0]) != len(line):
        return None
    if abs(len(line) - len(title)) > 1 or not title.strip() or title[0] in " \t[.*-+":
        return None
    return _UNDERLINE_LEVEL[line[0]]


def read_asciidoc(data: bytes, doc_id: str, title: str | None = None) -> Doc:
    """Read one AsciiDoc file. Raises `LibError` for NUL bytes or invalid UTF-8; everything else reads."""
    text = decode(data, f"AsciiDoc file {doc_id!r}")
    lines = text.expandtabs(8).split("\n")
    builder = Builder()
    doc_title = title or ""
    title_set = bool(title)
    pending_anchor = ""
    pending_title = ""
    conditionals = 0
    para: list[str] = []

    def flush() -> None:
        nonlocal pending_title
        if para:
            block = "\n".join(para)
            if pending_title:
                block = pending_title + "\n" + block
                pending_title = ""
            builder.unit(block)
            para.clear()

    def heading(level: int, name: str) -> None:
        nonlocal doc_title, title_set, pending_anchor
        name = name.strip()
        if level == 0 and not title_set and not doc_title:
            doc_title = name
            title_set = True
            builder.set_preamble_title(name)
            pending_anchor = ""
            return
        builder.heading(max(level, 1), name, pending_anchor)
        pending_anchor = ""

    i, count = 0, len(lines)
    while i < count:
        line = lines[i].rstrip()
        i += 1
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        # an underlined title: exactly one paragraph line above, this line is its underline
        if len(para) == 1:
            level = _is_underline(line, para[0])
            if level is not None and not _LIST.match(para[0]):
                name = para.pop()
                heading(level, name)
                continue
        if line.startswith(_COND_PREFIXES) and line.endswith("]") and "[" in line:
            conditionals += 1
            continue
        if line.startswith("//") and not line.startswith("///"):
            continue
        if _ATTR_ENTRY.fullmatch(stripped) and not para:
            continue
        match = _DELIM.fullmatch(line)
        if match and not (len(para) == 1 and _is_underline(line, para[0]) is not None):
            flush()
            body: list[str] = []
            while i < count and lines[i].rstrip() != line:
                body.append(lines[i].rstrip())
                i += 1
            i += 1  # the closing delimiter, or the end of the file for an unclosed block
            if line.startswith("/"):
                continue
            block = "\n".join(body).strip("\n")
            if pending_title:
                block = pending_title + "\n" + block
                pending_title = ""
            builder.unit(block)
            continue
        if line == "--":
            flush()
            continue
        if line == "+":
            continue
        atx = _ATX.fullmatch(line)
        if atx and not para:
            heading(len(atx.group(1)) - 1, atx.group(2))
            continue
        if line.startswith("include::") and line.endswith("]") and "[" in line:
            flush()
            builder.unit("[include] " + line[len("include::") : line.index("[")])
            continue
        anchor = _ANCHOR.fullmatch(line)
        if anchor and not para:
            pending_anchor = anchor.group(1)
            continue
        if _ATTRLINE.fullmatch(line) and not para:
            found = re.search(r"#([A-Za-z_][\w.:-]*)|\bid=([A-Za-z_][\w.:-]*)", line)
            if found:
                pending_anchor = found.group(1) or found.group(2)
            continue
        if not para and _BLOCKTITLE.fullmatch(line):
            pending_title = line
            continue
        if para and (_LIST.match(line) or _TERM.match(line) and not line.startswith(" ")):
            flush()
        para.append(line)
    flush()
    warnings: tuple[str, ...] = ()
    if conditionals:
        warnings = (f"{conditionals} ifdef/ifndef/ifeval/endif lines dropped; their content is kept unconditionally",)
    if not doc_title:
        doc_title = doc_id
    return builder.doc(doc_id, doc_title, unit=Unit.BLOCK, warnings=warnings)
