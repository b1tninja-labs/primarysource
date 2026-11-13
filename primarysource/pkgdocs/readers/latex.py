r"""A minimal LaTeX reader for the Gentoo Package Manager Specification, whose source is a set of `.tex` files.

This is not a TeX engine. It reads the structure the specification uses and nothing else:

- `\chapter`, `\section`, `\subsection`, `\subsubsection` (and the starred, unnumbered forms) are sections; the
  numbers are LaTeX's own (chapters 1, 2, ...; after `\appendix`, chapters A, B, ...; then `8.2.4`), and a
  `\label{...}` after a heading becomes the anchor, so `\ref{sec:slot-names}` in the text is replaced by the
  number it names (`section~\ref{...}` reads `section 8.2.4`);
- `\include{name}` and `\input{name}` are expanded **only from the mapping of files the caller passes in**
  (a file of the same archive), to a depth of four, never twice in one chain and never from disk. A missing name
  becomes the block `[include] name`;
- blocks (the unit): a paragraph; each `\item` of `description`, `compactdesc`, `itemize`, `compactitem`,
  `enumerate` and `compactenum` (a description item reads `TERM: text`); and each `verbatim`, `listing`,
  `algorithm`, `tabular`, `centertable`, `longtable` environment as one block written as `[environment]` and the
  raw text;
- text between the preamble and the first heading (the title page's copyright and licence notice) is section `0`.

Markup is reduced to its text: `\t{x}`, `\emph{x}`, `\textbf{x}` become `x`; `\cite{k}` becomes `[k]`; `~` is a
space; `---` and `--` become dashes; escapes (`\_`, `\&`, `\%`, `\$`, `\#`) are resolved. Any other command with
one argument keeps the argument, any other bare command is dropped, and the document carries one warning naming
the commands that were dropped, so a reader knows the text was reduced. Math, floats and macros defined in the
class file are not interpreted. Braces are scanned with a depth counter and a fixed number of passes, so
unbalanced or deeply nested input costs time linear in its size.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc, Sec
from primarysource.pkgdocs.readers._common import decode, slugify

MAX_DEPTH = 4
MAX_LINES = 200_000
_PASSES = 8
_LEVELS = {"chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3}
_LIST_ENVS = frozenset({"description", "compactdesc", "itemize", "compactitem", "enumerate", "compactenum"})
_RAW_ENVS = frozenset({"verbatim", "listing", "algorithm", "tabular", "centertable", "longtable"})
_COMMENT = re.compile(r"(?<!\\)%.*$")
_INCLUDE = re.compile(r"\s*\\(?:include|input)\{([^{}]*)\}\s*")
_HEADING = re.compile(r"\s*\\(chapter|section|subsection|subsubsection)(\*?)\s*(?:\[[^\]]*\])?\s*\{")
_BEGIN = re.compile(r"\s*\\begin\{([A-Za-z*]+)\}")
_END = re.compile(r"\s*\\end\{([A-Za-z*]+)\}")
_ITEM = re.compile(r"\s*\\item\b\s*(?:\[([^\]]*)\])?\s*(.*)")
_LABEL = re.compile(r"\s*\\label\{([^{}]*)\}\s*")
_ONE_ARG = re.compile(r"\\([A-Za-z]+)\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
_BARE = re.compile(r"\\([A-Za-z]+)\*?")
_REF = re.compile(r"\\(?:ref|autoref|pageref)\{([^{}]*)\}")
_LAYOUT = re.compile(
    r"\s*\\(?:thispagestyle|vspace|tableofcontents|listof\w+|maketitle|bibliography|nobreakpar|clearpage|newpage"
    r"|noindent|small|centering|vfill|hfill)\b.*"
)
_SPACE = re.compile(r"[ \t]+")
_SYMBOLS = (
    ("\\textasciicircum", "^"),
    ("\\textbackslash", "\x01"),
    ("\\textasciitilde", "~"),
    ("\\slash", "/"),
    ("\\allowbreak", ""),
    ("\\dots", "..."),
)
_DROP_ARG = frozenset({"featurelabel", "ChangeWhenAddingAnEAPI", "hspace", "vspace", "index"})
_KEEP_ARG = frozenset(
    {"t", "emph", "textbf", "textit", "texttt", "path", "url", "code", "textsc", "textsf", "underline", "mbox"}
)


@dataclass(slots=True)
class _Section:
    id: str
    title: str
    depth: int
    anchor: str
    units: list[tuple[str, bool]] = field(default_factory=list)  # (text, already clean)


def _braced(text: str, start: int) -> tuple[str, int]:
    """The brace-balanced group whose `{` is just before `start`, and the index after its `}`."""
    depth = 1
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return text[start:], len(text)


def _expand(
    files: Mapping[str, bytes], name: str, chain: tuple[str, ...], out: list[str], missing: list[str]
) -> None:
    key = name if name in files else name + ".tex"
    if key not in files or key in chain or len(chain) >= MAX_DEPTH:
        missing.append(name)
        out.append(f"[include] {name}")
        return
    for line in decode(files[key], key).split("\n"):
        if len(out) >= MAX_LINES:
            return
        line = _COMMENT.sub("", line).rstrip()
        found = _INCLUDE.fullmatch(line)
        if found:
            _expand(files, found.group(1).strip(), (*chain, key), out, missing)
        else:
            out.append(line)


def _letter(n: int) -> str:
    return chr(ord("A") + (n - 1) % 26)


def read_latex(files: Mapping[str, bytes], root: str, doc_id: str, title: str) -> Doc:
    """Read `root` (a key of `files`) with its includes into one document. Raises `LibError` for a NUL byte or
    invalid UTF-8 in any file it reads; a `root` that is not in `files` is an empty document with a warning."""
    lines: list[str] = []
    missing: list[str] = []
    _expand(files, root, (), lines, missing)
    started = False
    appendix = False
    counters = [0, 0, 0, 0]
    unnumbered = 0
    sections: list[_Section] = [_Section("0", title, 1, slugify(title) or "preamble")]
    labels: dict[str, str] = {}
    para: list[str] = []
    item: list[str] | None = None
    list_depth = 0
    i, count = 0, len(lines)

    def emit(text: str, clean: bool = False) -> None:
        if text.strip():
            sections[-1].units.append((text, clean))

    def flush() -> None:
        if para:
            emit(" ".join(para))
            para.clear()

    def flush_item() -> None:
        nonlocal item
        if item is not None:
            emit(" ".join(item))
            item = None

    while i < count:
        line = lines[i]
        i += 1
        if not started:
            if line.strip().startswith("\\begin{document}"):
                started = True
            continue
        if not line.strip():
            flush()
            continue
        if line.strip().startswith("\\end{document}"):
            break
        heading = _HEADING.match(line)
        if heading:
            flush()
            flush_item()
            joined, extra = line, 0
            while joined.count("{") > joined.count("}") and i < count and extra < 3:
                joined += " " + lines[i].strip()
                i += 1
                extra += 1
            start = _HEADING.match(joined)
            if start is None:
                continue
            kind, star = start.group(1), start.group(2)
            text, _ = _braced(joined, start.end())
            level = _LEVELS[kind]
            if star:
                unnumbered += 1
                section_id = f"u{unnumbered}"
            else:
                counters[level] += 1
                for deeper in range(level + 1, 4):
                    counters[deeper] = 0
                first = _letter(counters[0]) if appendix else str(counters[0])
                section_id = ".".join([first, *(str(n) for n in counters[1 : level + 1])])
            sections.append(_Section(section_id, _plain(text, labels), level + 1, ""))
            while i < count and not lines[i].strip():
                i += 1
            key = _LABEL.fullmatch(lines[i]) if i < count else None
            if key:
                sections[-1].anchor = key.group(1)
                labels[key.group(1)] = section_id
                i += 1
            continue
        if line.strip() == "\\appendix":
            flush()
            appendix = True
            counters = [0, 0, 0, 0]
            continue
        begin = _BEGIN.match(line)
        if begin and begin.group(1) in _RAW_ENVS:
            flush()
            flush_item()
            env = begin.group(1)
            raw = [line.strip()]
            depth = 1
            while i < count and depth:
                nxt = lines[i]
                i += 1
                raw.append(nxt)
                inner = _BEGIN.match(nxt)
                if inner and inner.group(1) == env:
                    depth += 1
                closing = _END.match(nxt)
                if closing and closing.group(1) == env:
                    depth -= 1
            emit(f"[{env}]\n" + "\n".join(raw), clean=True)
            continue
        if begin and begin.group(1) in _LIST_ENVS:
            flush()
            flush_item()
            list_depth += 1
            continue
        end = _END.match(line)
        if end and end.group(1) in _LIST_ENVS:
            flush()
            flush_item()
            list_depth = max(0, list_depth - 1)
            continue
        entry = _ITEM.match(line) if list_depth else None
        if entry:
            flush()
            flush_item()
            item = ([f"{entry.group(1)}:"] if entry.group(1) is not None else []) + (
                [entry.group(2)] if entry.group(2) else []
            )
            continue
        if _LAYOUT.fullmatch(line):
            continue
        (item if item is not None else para).append(line.strip())
    flush()
    flush_item()
    unknown: dict[str, int] = {}
    built: list[Sec] = []
    for section in sections:
        units = tuple(t if clean else _plain(t, labels, unknown) for t, clean in section.units)
        units = tuple(u for u in units if u.strip())
        if section.id == "0" and not units:
            continue
        anchor = section.anchor or slugify(section.title) or section.id
        built.append(Sec(section.id, section.title, section.depth, anchor, units))
    warnings: list[str] = []
    if unknown:
        names = ", ".join(sorted(unknown, key=lambda k: (-unknown[k], k))[:12])
        warnings.append(f"LaTeX commands dropped (their arguments kept): {names}")
    if missing:
        warnings.append(f"not in the archive selection: {', '.join(sorted(set(missing)))}")
    return Doc(doc_id, title, Unit.BLOCK, _unique(built), {}, tuple(warnings))


def _unique(sections: list[Sec]) -> tuple[Sec, ...]:
    seen: set[str] = set()
    out: list[Sec] = []
    for section in sections:
        anchor, n = section.anchor, 0
        while anchor in seen:
            n += 1
            anchor = f"{section.anchor}-{n}"
        seen.add(anchor)
        out.append(Sec(section.id, section.title, section.depth, anchor, section.units))
    return tuple(out)


def _plain(text: str, labels: Mapping[str, str], unknown: dict[str, int] | None = None) -> str:
    """Reduce LaTeX markup in `text` to its words (see the module docstring)."""
    text = _REF.sub(lambda m: labels.get(m.group(1), m.group(1)), text)
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\cite\{([^{}]*)\}", r"[\1]", text)
    text = text.replace("\\\\", " ").replace("\\@", "").replace("\\,", " ").replace("\\ ", " ").replace("~", " ")
    for command, plain in _SYMBOLS:
        text = text.replace(command, plain)
    for _ in range(_PASSES):

        def one(match: re.Match[str]) -> str:
            name, arg = match.group(1), match.group(2)
            if name == "note":
                return "Note: " + arg
            if name in _DROP_ARG:
                return ""
            if name not in _KEEP_ARG and unknown is not None:
                unknown[name] = unknown.get(name, 0) + 1
            return arg

        after = _ONE_ARG.sub(one, text)
        if after == text:
            break
        text = after

    def bare(match: re.Match[str]) -> str:
        if unknown is not None:
            unknown[match.group(1)] = unknown.get(match.group(1), 0) + 1
        return ""

    text = _BARE.sub(bare, text)
    for escape in ("_", "&", "%", "$", "#"):
        text = text.replace("\\" + escape, escape)
    text = text.replace("\\{", "\x02").replace("\\}", "\x03").replace("{", "").replace("}", "")
    text = text.replace("\x02", "{").replace("\x03", "}").replace("\x01", "\\")
    text = text.replace("---", "\u2014").replace("--", "\u2013")
    text = text.replace("``", '"').replace("''", '"')
    return _SPACE.sub(" ", text).strip()
