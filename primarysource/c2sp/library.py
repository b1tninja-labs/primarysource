"""Read, outline, search and cite the installed C2SP specifications. Local files only; nothing here fetches.

A ref is `c2sp:static-ct-api@09f3e51§Log Entries¶2`, with the `c2sp:` prefix and the `@<commit prefix>` both
optional (no `@` means the newest import). `§` names a section by its heading text, or by its GitHub-style slug
(`log-entries`) when the heading contains `:`, `#`, `¶` or `§`, or when two headings read alike. `¶n` is the nth
block of that section's span (see `markdown.py`). A ref with no section is the whole document.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from primarysource import budget, cursor
from primarysource.c2sp import markdown
from primarysource.c2sp._fetch import sha256
from primarysource.c2sp.catalogue import DOC_ID
from primarysource.c2sp.catalogue import catalogue as packaged_catalogue
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import span_hash
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = "c2sp:"
IMPORT = "primarysource c2sp import"
_COMMIT_PREFIX = re.compile(r"[0-9a-f]{7,40}")
_UNSAFE_IN_REF = re.compile(r"[:#¶§]")
_HEADING_LINE = re.compile(r"#{1,6}(?: |$)")
_TERM = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_TERMS = 16


def grammar() -> RefGrammar:
    from primarysource.c2sp import C2SP_DOC, C2SP_SECTION

    return RefGrammar(C2SP_DOC, C2SP_SECTION)


@dataclass(frozen=True, slots=True)
class Loaded:
    """One installed specification, parsed."""

    id: str
    commit: str
    title: str
    document: markdown.MarkdownDocument

    @property
    def short(self) -> str:
        return self.commit[:7]


def default_home() -> Path:
    return collection_home("c2sp")


def installs(home: Path) -> list[tuple[str, dict[str, object]]]:
    """Every install under `home` as (commit, record), newest import first. A directory without a readable
    `install.json` is not an install."""
    found: list[tuple[str, dict[str, object]]] = []
    if home.is_dir():
        for child in home.iterdir():
            record = child / "install.json"
            if child.is_dir() and re.fullmatch(r"[0-9a-f]{40}", child.name) and record.is_file():
                try:
                    loaded = json.loads(record.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if isinstance(loaded, dict) and loaded.get("commit") == child.name:
                    found.append((child.name, loaded))
    found.sort(key=lambda item: str(item[1].get("imported", "")), reverse=True)
    return found


def _split_doc(token: str) -> tuple[str, str | None]:
    doc, _, version = token.partition("@")
    if not DOC_ID.fullmatch(doc):
        raise LibError(f"not a C2SP specification id: {doc!r}", "c2sp_docs lists the specification ids")
    if version and not _COMMIT_PREFIX.fullmatch(version):
        raise LibError(f"not a commit prefix: {version!r}", "use at least 7 lowercase hex digits of the commit")
    return doc, version or None


def load(token: str, home: Path | None = None) -> Loaded:
    """Load `doc[@commit-prefix]`, verifying the file against the install record's sha256."""
    home = home or default_home()
    doc_id, version = _split_doc(token)
    available = installs(home)
    if not available:
        raise LibError("no C2SP specifications are imported", "c2sp_docs lists the catalogue", IMPORT)
    for commit, record in available:
        if version and not commit.startswith(version):
            continue
        files = record.get("files")
        pin = files.get(doc_id) if isinstance(files, dict) else None
        if not isinstance(pin, str):
            continue
        data = (home / commit / f"{doc_id}.md").read_bytes() if (home / commit / f"{doc_id}.md").is_file() else None
        if data is None:
            continue
        if sha256(data) != pin:
            raise LibError(f"{doc_id}@{commit[:7]} on disk does not match its recorded sha256", "", IMPORT)
        parsed = markdown.parse(data)
        return Loaded(doc_id, commit, parsed.title or doc_id, parsed)
    have = ", ".join(f"{c[:7]}" for c, _ in available)
    what = f"{doc_id}@{version}" if version else doc_id
    raise LibError(f"{what} is not imported (imported commits: {have})", "c2sp_docs lists what is imported", IMPORT)


def parse_ref(text: str) -> Ref:
    """Parse a c2sp ref, accepting the optional `c2sp:` prefix."""
    body = text.strip()
    if body.lower().startswith(PREFIX):
        body = body[len(PREFIX) :]
    body, doc_para = cursor.split_doc_para(body)
    ref = grammar().parse(body)
    if doc_para is not None:
        ref = Ref(ref.doc, None, doc_para, None, None)
    if ref.lines is not None:
        raise LibError(f"not a c2sp ref: {text!r}", "c2sp refs address headings and blocks, not line ranges")
    if ref.anchor is not None:
        raise LibError(f"not a c2sp ref: {text!r}", "c2sp has no #anchor; name the heading after §")
    if ref.doc is None:
        raise LibError(f"not a c2sp ref: {text!r}", "start with the specification id, e.g. static-ct-api")
    return Ref(ref.doc, ref.section.strip() if ref.section else None, ref.para, None, None)


def find_heading(doc: Loaded, name: str) -> tuple[markdown.Heading, str]:
    """The heading `name` names, and a warning ("" if none). Exact title, then slug, then case-folded title."""
    headings = doc.document.headings
    wanted = name.strip()
    for match in (
        [h for h in headings if h.title == wanted],
        [h for h in headings if h.slug == wanted.lower()],
        [h for h in headings if h.title.casefold() == wanted.casefold()],
    ):
        if match:
            warning = ""
            if len(match) > 1:
                slugs = ", ".join(h.slug for h in match)
                warning = f"{len(match)} headings are titled {wanted!r}; this is the first. Use a slug: {slugs}"
            return match[0], warning
    close = difflib.get_close_matches(wanted, [h.title for h in headings], n=3, cutoff=0.5)
    hint = f"did you mean: {', '.join(close)}" if close else f"c2sp_outline('{doc.id}') lists the headings"
    raise LibError(f"no section {wanted!r} in {doc.id}@{doc.short}", hint)


def section_ref(doc: Loaded, heading: markdown.Heading) -> str:
    """The canonical ref of a heading: its title, or its slug if the title cannot appear in a ref."""
    same = [h for h in doc.document.headings if h.title == heading.title]
    use_slug = _UNSAFE_IN_REF.search(heading.title) is not None or len(same) > 1
    return f"{doc.id}@{doc.short}§{heading.slug if use_slug else heading.title}"


def _cite_text(doc: Loaded, heading: markdown.Heading | None, para: int | str | None) -> str:
    where = f", §{heading.title}" if heading else ""
    if para:
        where += f" ¶{para}"
    return (
        f"C2SP, {doc.id} ({doc.title}), commit {doc.short}{where}. CC BY 4.0. "
        f"https://github.com/C2SP/C2SP/blob/{doc.commit}/{doc.id}.md"
    )


def _doc(ref: Ref) -> str:
    """The document of a parsed ref; `parse_ref` has already refused a ref without one."""
    if ref.doc is None:
        raise LibError("the ref names no document", "start with the document id")
    return ref.doc


def _select(ref: Ref, home: Path | None) -> tuple[Loaded, markdown.Heading | None, tuple[str, ...], str]:
    doc = load(_doc(ref), home)
    if ref.section is None:
        return doc, None, doc.document.units(), ""
    heading, warning = find_heading(doc, ref.section)
    return doc, heading, heading.units, warning


def read(ref_text: str, max_tokens: int = 2000, home: Path | None = None) -> str:
    """The text of a ref, cut at block boundaries within `max_tokens`. A `¶n` ref starts at block n and runs to the
    end of its scope; the `next:` footer is the ref that reads the next page."""
    ref = parse_ref(ref_text)
    doc, heading, units, warning = _select(ref, home)
    if not units:
        raise LibError(f"{ref_text}: that section has no text of its own", "read its subsections, see c2sp_outline")
    first = cursor.first_unit(ref.para, len(units), "blocks", ref_text)
    chosen = budget.page(units, start=first, max_tokens=max_tokens)
    body = "\n\n".join(chosen.units)
    scope = section_ref(doc, heading) if heading else f"{doc.id}@{doc.short}"
    footer = {
        "cite": _cite_text(doc, heading, cursor.para_label(ref.para, chosen)),
        "unit": "block",
        "span": span_hash(body),
        "next": cursor.read_next(scope, chosen),
        "warning": warning,
    }
    return render(body, footer)


def outline(token: str, home: Path | None = None) -> str:
    """The headings of one specification, indented by level, each with the ref that reads it."""
    doc = load(token, home)
    lines = [f"{doc.title}  [{doc.id}@{doc.short}]"]
    for heading in doc.document.headings:
        indent = "  " * (heading.level - 1)
        lines.append(f"{indent}{heading.title}  {section_ref(doc, heading)}  ({len(heading.units)} blocks)")
    return "\n".join(lines)


def _terms(query: str) -> list[str]:
    terms = [t for t in _TERM.findall(query.casefold()) if len(t) <= 64]
    if not terms:
        raise LibError("the query has no searchable words", "use words or identifiers, e.g. 'checkpoint origin'")
    return terms[:MAX_QUERY_TERMS]


def _snippet(text: str, terms: list[str]) -> str:
    flat = " ".join(text.split())
    low = flat.casefold()
    at = min((i for i in (low.find(t) for t in terms) if i >= 0), default=0)
    begin = max(0, at - 60)
    return ("..." if begin else "") + flat[begin : begin + 160] + ("..." if begin + 160 < len(flat) else "")


def search(
    query: str,
    doc: str | None = None,
    limit: int = 10,
    start: int = 0,
    home: Path | None = None,
) -> str:
    """Blocks containing every query word (else at least half of them, flagged `relaxed`), best first: one line
    per hit, `<ref>¶n: <snippet>`. Ranked by term frequency with a bonus for a match in the heading."""
    terms = _terms(query)
    home = home or default_home()
    available = installs(home)
    if not available:
        raise LibError("no C2SP specifications are imported", "c2sp_docs lists the catalogue", IMPORT)
    ids: list[str] = []
    if doc:
        ids = [doc]
    else:
        record_files = available[0][1].get("files")
        ids = sorted(record_files) if isinstance(record_files, dict) else []
    scored: list[tuple[float, int, str, str]] = []
    relaxed = False
    for need_all in (True, False):
        for order, token in enumerate(ids):
            loaded = load(token, home)
            for heading in loaded.document.headings:
                title = heading.title.casefold()
                for index, block in enumerate(heading.units, start=1):
                    if _HEADING_LINE.match(block):
                        break  # what follows belongs to a subsection, which is searched under its own heading
                    words = _TERM.findall(block.casefold())
                    hits = [words.count(t) for t in terms]
                    present = sum(1 for h in hits if h)
                    if present == 0 or (need_all and present < len(terms)) or present * 2 < len(terms):
                        continue
                    score = sum(hits) + 3 * present + sum(2 for t in terms if t in title)
                    ref = f"{section_ref(loaded, heading)}¶{index}"
                    scored.append((-score, order, ref, _snippet(block, terms)))
        if scored:
            relaxed = not need_all
            break
    if not scored:
        return render("no matches", {})
    scored.sort()
    shown, nxt = cursor.window(scored, start, limit)
    body = "\n".join(f"{ref}: {snip}" for _, _, ref, snip in shown)
    return render(body, {"next": nxt, "relaxed": "only some query words matched" if relaxed else ""})


def cite(ref_text: str, home: Path | None = None) -> str:
    """The citation string for a ref, with the span hash of the exact text cited."""
    ref = parse_ref(ref_text)
    doc, heading, units, warning = _select(ref, home)
    if ref.para is not None:
        if ref.para > len(units):
            raise LibError(f"{ref_text}: the span has {len(units)} blocks", f"use ¶1 to ¶{len(units)}")
        units = (units[ref.para - 1],)
    footer = {
        "cite": _cite_text(doc, heading, ref.para),
        "unit": "block",
        "span": span_hash("\n\n".join(units)),
        "warning": warning,
    }
    return render(f"{doc.id}@{doc.short}" + (f"§{heading.title}" if heading else ""), footer)


def docs(home: Path | None = None) -> str:
    """The catalogue with what is imported: one line per specification."""
    home = home or default_home()
    cat = packaged_catalogue()
    present: set[str] = set()
    commits = installs(home)
    for _, record in commits:
        files = record.get("files")
        if isinstance(files, dict):
            present.update(files)
    lines = [f"commit {cat.commit[:7]} ({cat.terms.licence}, placement {cat.terms.placement})"]
    for spec in cat.specs:
        lines.append(f"{'imported' if spec.id in present else 'not imported':<13} {spec.id}  {spec.title}")
    return "\n".join(lines)
