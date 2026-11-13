"""The text of every tool and command: read, outline, search, cite, info, list. Local files only, no network.

Every result about a draft says three things the other collections need not, because a draft is not a fixed
document: which revision it read (a ref without one resolves to the latest stored revision, and says so), whether
that draft is still alive (RFC 2026 §2.2: no formal status, subject to change or removal at any time), and when
that was last checked. A dead or superseded draft starts with a banner line as well as ending in `warning:`, so
nobody has to reach the footer to learn it.
"""

from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from primarysource import budget, cursor
from primarysource.draft import catalogue, datatracker, licence, names
from primarysource.draft.segment import Block, DSection, Segmented, normalise
from primarysource.draft.status import STALE_DAYS, Lifecycle, Status, lifecycle, staleness
from primarysource.draft.store import RevMeta, Store
from primarysource.errors import LibError
from primarysource.model import span_hash
from primarysource.refs import Ref
from primarysource.render import render

_WORD = re.compile(r"[a-z0-9][a-z0-9_]*")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")  # fmt: skip
MAX_QUERY = 300


@dataclass(frozen=True, slots=True)
class Target:
    """A ref resolved against the library: the draft, the revision actually read, and whether it was chosen."""

    name: str
    rev: str
    chosen: bool
    ref: Ref

    @property
    def doc(self) -> str:
        return f"{self.name}-{self.rev}"


def resolve(store: Store, text: str, need_rev: bool = True) -> Target:
    """Parse `text` as a ref and pick the revision. A ref with no document part is refused."""
    if len(text) > 400:
        raise LibError("not a ref: too long", "")
    ref = names.GRAMMAR.parse(text)
    if not ref.doc:
        raise LibError(f"not a draft ref: {text[:60]!r}", "expected draft-<words>[-NN][§<section>[¶n]]")
    name, rev = names.split_doc(ref.doc)
    if rev is None and not need_rev:
        return Target(name, "", False, ref)
    chosen_rev, chosen = store.resolve(name, rev)
    return Target(name, chosen_rev, chosen, ref)


def _day(published: str) -> str:
    try:
        y, m, d = (int(x) for x in published[:10].split("-"))
        date(y, m, d)
        return f"{d} {_MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return ""


def _initials(author: str) -> str:
    parts = author.split()
    if len(parts) < 2:
        return author
    return " ".join(f"{p[0]}." for p in parts[:-1] if p) + " " + parts[-1]


def _authors(meta: RevMeta) -> str:
    listed = [_initials(a) for a in meta.authors]
    if not listed:
        return ""
    if len(listed) > 3:
        return f"{listed[0]} et al."
    if len(listed) == 3:
        return f"{listed[0]}, {listed[1]}, and {listed[2]}"
    return " and ".join(listed)


def section_anchor(section: DSection) -> str:
    """The datatracker HTML's anchor for a numbered section (`section-5.1`, `section-appendix.a`, `section-a.1`),
    or '' for an unnumbered one, which has no stable anchor."""
    if not section.num:
        return ""
    if section.num.startswith("Appendix "):
        return "section-appendix." + section.num.split(" ", 1)[1].lower()
    return "section-" + section.num.lower()


def cite_string(meta: RevMeta, section: DSection | None = None, para: int | str | None = None) -> str:
    """`Authors, "Title", Work in Progress, Internet-Draft, name-NN, date, <url#anchor>, Section 5.1, paragraph 2.`
    "Work in Progress" is the only way RFC 2026 §2.2 and the drafts' own status text allow one to be cited."""
    anchor = section_anchor(section) if section else ""
    url = datatracker.html_url(meta.name, meta.rev) + (f"#{anchor}" if anchor else "")
    parts = [p for p in (_authors(meta), f'"{meta.title}"', "Work in Progress", "Internet-Draft",
                         f"{meta.name}-{meta.rev}", _day(meta.published), f"<{url}>") if p]  # fmt: skip
    text = ", ".join(parts)
    if section is not None:
        where = f"Section {section.num.removeprefix('Appendix ')}" if section.num else f'"{section.title}"'
        if section.num.startswith("Appendix "):
            where = f"Appendix {section.num.split(' ', 1)[1]}"
        text += f", {where}" + (f", paragraph{'s' if isinstance(para, str) else ''} {para}" if para else "")
    return text + "."


def standing(store: Store, name: str, rev: str, chosen: bool = False) -> tuple[list[str], str]:
    """(warnings, banner) for reading `name`-`rev`: what a reader must know before relying on it. The banner is
    '' when the draft is alive and `rev` is its latest revision."""
    notes: list[str] = []
    banner = ""
    if chosen:
        notes.append(f"no revision in the ref: read the latest stored revision -{rev}")
    status = store.status(name)
    if status is None:
        notes.append(
            f"no datatracker status stored, so expiry and replacement are unknown: primarysource draft refresh {name}"
        )
        return notes, banner
    cycle = lifecycle(status)
    if not cycle.alive:
        banner = f"[{cycle.level.upper()}: {cycle.text}]"
        notes.append(f"{cycle.level.upper()}: {cycle.text}")
    if status.rev != rev:
        newer = f"-{rev} is not the latest revision: the datatracker listed -{status.rev}"
        banner = banner or f"[{newer}]"
        notes.append(newer)
    age = staleness(status)
    if age > STALE_DAYS:
        notes.append(f"status was checked {age} days ago: primarysource draft refresh {name}")
    return notes, banner


def _footer(cite: str, notes: list[str], span: str = "", nxt: str = "") -> dict[str, str]:
    return {"cite": cite, "unit": "paragraph", "span": span, "next": nxt, "warning": "; ".join(notes)}


def _section_not_found(seg: Segmented, section: str, doc: str) -> LibError:
    close = difflib.get_close_matches(section, [s.id for s in seg.sections], n=3)
    hint = f"did you mean {', '.join(close)}?" if close else f"draft_outline lists the sections of {doc}"
    return LibError(f"{doc} has no section {section!r}", hint)


def _block_text(block: Block) -> str:
    return block.text


def read(store: Store, text: str, max_tokens: int = 2000) -> str:
    """Read by ref: `name[-rev]` (abstract and outline), `§section` (its paragraphs, paged), `§section¶n` (from
    paragraph n, paged) or `:first-last` (those lines of the stored text). The `next:` footer is the ref that reads
    the next page."""
    target = resolve(store, text)
    meta = store.meta(target.name, target.rev)
    notes, banner = standing(store, target.name, target.rev, target.chosen)
    ref = target.ref
    if ref.lines is not None:
        return _read_lines(store, target, meta, ref.lines, banner, notes)
    seg = store.segmented(target.name, target.rev)
    if ref.section is None:
        return _overview(seg, target, meta, banner, notes)
    section = seg.section(ref.section)
    if section is None:
        raise _section_not_found(seg, ref.section, target.doc)
    head = f"{target.doc}§{section.id} {section.title}".rstrip()
    if ref.para is not None and ref.para > len(section.blocks):
        raise LibError(f"{head} has {len(section.blocks)} paragraphs, not {ref.para}", "")
    units = tuple(_block_text(b) for b in section.blocks)
    if not units:
        body = "(no text under this heading; see its subsections in the outline)"
        return render("\n".join(x for x in (banner, head, body) if x), _footer(cite_string(meta, section), notes))
    if max_tokens < 1:
        raise LibError("max_tokens must be positive", "")
    page = budget.page(units, ref.para or 1, max_tokens)
    body = "\n\n".join(page.units)
    nxt = cursor.read_next(f"{target.doc}§{section.id}", page)
    cite = cite_string(meta, section, cursor.para_label(ref.para, page))
    if ref.para is not None:  # a ¶ read is the paragraphs themselves, as a search hit's ref promises
        return render("\n".join(x for x in (banner, body) if x), _footer(cite, notes, span_hash(body), nxt))
    top = [banner, f"{head}  (paragraphs {page.first}-{page.last} of {page.total})"]
    return render("\n".join(x for x in top if x) + "\n\n" + body, _footer(cite, notes, span_hash(body), nxt))


def _read_lines(
    store: Store, target: Target, meta: RevMeta, span: tuple[int, int], banner: str, notes: list[str]
) -> str:
    lines = normalise(store.raw_text(target.name, target.rev).decode("utf-8", errors="replace"))
    first, last = span
    if first > len(lines):
        raise LibError(f"{target.doc} has {len(lines)} lines; {first}-{last} is past the end", "")
    body = "\n".join(lines[first - 1 : last])
    cite = cite_string(meta)[:-1] + f", lines {first}-{min(last, len(lines))}."
    return render("\n".join(x for x in (banner, body) if x), _footer(cite, notes, span_hash(body)))


def _overview(seg: Segmented, target: Target, meta: RevMeta, banner: str, notes: list[str]) -> str:
    abstract = seg.section("abstract")
    head = f"{target.doc}  {meta.title}"
    parts = [banner] if banner else []
    parts += [head, f"{len(seg.sections)} sections; segmented from the text by {seg.method}"]
    if abstract is not None and abstract.blocks:
        parts += ["", "Abstract", *(b.text for b in abstract.blocks)]
    parts += ["", "Sections (read one with draft_read('<ref>')):", *_outline_lines(seg, target.doc)]
    return render("\n".join(p for p in parts if p is not None), _footer(cite_string(meta), notes))


def _outline_lines(seg: Segmented, doc: str) -> list[str]:
    out = []
    for s in seg.sections:
        label = f"{s.num} " if s.num else ""
        out.append(f"{'  ' * (s.depth - 1)}{doc}§{s.id}  {label}{s.title}  ({len(s.blocks)})")
    return out


def outline(store: Store, text: str) -> str:
    """The sections of a stored revision, each with the ref that reads it and its paragraph count."""
    target = resolve(store, text)
    meta = store.meta(target.name, target.rev)
    notes, banner = standing(store, target.name, target.rev, target.chosen)
    seg = store.segmented(target.name, target.rev)
    body = "\n".join([x for x in (banner, f"{target.doc}  {meta.title}") if x] + _outline_lines(seg, target.doc))
    return render(body, _footer(cite_string(meta), notes))


def cite(store: Store, text: str) -> str:
    """The citation for a ref, with the span hash of the cited text when it is a paragraph or a section."""
    target = resolve(store, text)
    meta = store.meta(target.name, target.rev)
    notes, banner = standing(store, target.name, target.rev, target.chosen)
    ref = target.ref
    section: DSection | None = None
    span = ""
    if ref.section is not None:
        seg = store.segmented(target.name, target.rev)
        section = seg.section(ref.section)
        if section is None:
            raise _section_not_found(seg, ref.section, target.doc)
        if ref.para is not None:
            if ref.para > len(section.blocks):
                raise LibError(f"{target.doc}§{section.id} has {len(section.blocks)} paragraphs, not {ref.para}", "")
            span = span_hash(section.blocks[ref.para - 1].text)
        else:
            span = span_hash("\n\n".join(b.text for b in section.blocks))
    cite_text = cite_string(meta, section, ref.para)
    resolved = Ref(doc=target.doc, section=ref.section, para=ref.para)
    said = f"citation for {names.GRAMMAR.format(resolved)}; the cite: line is the string to use"
    return render("\n".join(x for x in (banner, said) if x), _footer(cite_text, notes, span))


def _lifecycle_line(status: Status) -> str:
    cycle: Lifecycle = lifecycle(status)
    return f"{cycle.level.upper()}: {cycle.text}"


def info(store: Store, text: str) -> str:
    """Everything known about a draft: standing, revisions stored and upstream, licence legend, pins."""
    ref = names.GRAMMAR.parse(text)
    if not ref.doc:
        raise LibError(f"not a draft name: {text[:60]!r}", "")
    name, _rev = names.split_doc(ref.doc)
    stored = store.revisions(name)
    status = store.status(name)
    tracked = catalogue.TRACKED.get(name)
    if not stored and status is None and tracked is None:
        raise LibError(
            f"{name} is neither stored nor tracked",
            "draft_list lists what is tracked",
            f"primarysource draft import {name}",
        )
    lines = [name]
    if status is not None:
        lines += [
            f"title: {status.title}",
            f"datatracker state: {status.state}",
            f"standing: {_lifecycle_line(status)}",
        ]
        lines.append(
            f"latest revision on the datatracker: -{status.rev}"
            + (f" (posted {status.published(status.rev)})" if status.published(status.rev) else "")
        )
        lines.append(f"expires: {status.expires[:10] or 'unknown'}")
        if status.replaced_by:
            lines.append(f"replaced by: {', '.join(status.replaced_by)}")
        if status.became_rfc:
            lines.append(f"became: {status.became_rfc} (rfclib reads it)")
        lines.append(f"revisions on the datatracker: {', '.join(r for r, _ in status.revisions) or 'none listed'}")
        if status.group or status.stream:
            lines.append(f"group: {status.group or '-'}  stream: {status.stream or '-'}")
        lines.append(f"status checked: {status.checked[:10]} ({staleness(status)} days ago)")
    elif tracked is not None:
        lines += [
            "no datatracker status stored here; the catalogue's snapshot:",
            f"catalogue snapshot, checked {tracked.checked or 'never'}: state {tracked.state or 'unknown'}, "
            f"revision read -{tracked.rev_read or '?'}"
            + (f", replaced by {', '.join(tracked.replaced_by)}" if tracked.replaced_by else "")
            + (f", became {tracked.became_rfc}" if tracked.became_rfc else ""),
            f"refresh it: primarysource draft refresh {name}",
        ]
    lines.append(f"revisions stored: {', '.join('-' + r for r in stored) or 'none'}")
    if stored:
        meta = store.meta(name, stored[-1])
        lines.append(
            f"text of -{meta.rev}: {meta.txt_bytes:,} bytes, sha256 {meta.txt_sha256}, imported {meta.imported[:10]}"
        )
        lines.append(
            f"author's xml of -{meta.rev}: {meta.xml_state}"
            + (f", sha256 {meta.xml_sha256}" if meta.xml_sha256 else "")
        )
        lines.append("licence: " + licence.Licence(meta.restriction, meta.copyright_year, meta.ipr).summary())
        pin = catalogue.pin_for(name, meta.rev)
        lines.append(f"pinned in the catalogue: {'yes' if pin else 'no (trusted on first use)'}")
    if tracked is not None:
        lines.append(f"tracked for: {', '.join(tracked.consumers)}. {tracked.why}")
    lines.append(
        "a draft has no formal status and may change or disappear at any time (RFC 2026 §2.2): "
        "cite it only as work in progress"
    )
    notes = []
    if status is not None and not lifecycle(status).alive:
        notes.append(_lifecycle_line(status))
    return render("\n".join(lines), {"warning": "; ".join(notes)})


def list_tracked(store: Store) -> str:
    """One line per tracked or stored draft: stored revisions, the state last seen, who replaced it."""
    rows = []
    for name in sorted(set(catalogue.TRACKED) | set(store.names())):
        stored = store.revisions(name)
        status = store.status(name)
        tracked = catalogue.TRACKED.get(name)
        state = (
            status.state if status else (f"{tracked.state} (catalogue)" if tracked and tracked.state else "unknown")
        )
        later = f"-{status.rev}" if status else (f"-{tracked.rev_read}" if tracked and tracked.rev_read else "-")
        extra = ""
        if status and status.replaced_by:
            extra = f"  replaced by {', '.join(status.replaced_by)}"
        elif tracked and tracked.replaced_by:
            extra = f"  replaced by {', '.join(tracked.replaced_by)}"
        rows.append(
            f"{name}  stored: {', '.join('-' + r for r in stored) or 'none'}  latest: {later}  state: {state}{extra}"
        )
    return render("\n".join(rows) or "no drafts stored or tracked", {})


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _snippet(blocks: tuple[Block, ...], words: set[str], width: int = 160) -> str:
    for b in blocks:
        flat = " ".join(b.text.split())
        low = flat.lower()
        hits = [low.find(w) for w in words if low.find(w) >= 0]
        if hits:
            at = max(0, min(hits) - 40)
            return ("..." if at else "") + flat[at : at + width]
    return ""


def search(store: Store, query: str, limit: int = 10, name: str | None = None) -> str:
    """BM25 over the sections of each draft's latest stored revision (or of one named draft or revision). All
    words must match; if none of the sections has them all, any section with some does, and `relaxed:` says so."""
    if not query.strip() or len(query) > MAX_QUERY:
        raise LibError(f"a query is 1 to {MAX_QUERY} characters", "")
    if not 1 <= limit <= 50:
        raise LibError("limit is 1 to 50", "")
    words = _tokens(query)
    if not words:
        raise LibError("the query has no searchable words", "use letters and digits")
    chosen: list[tuple[str, str]] = []
    if name:
        n, rev = names.split_doc(name)
        chosen.append((n, store.resolve(n, rev)[0]))
    else:
        chosen = [(n, store.revisions(n)[-1]) for n in store.names()]
    if not chosen:
        raise LibError(
            "no draft is stored", "draft_list lists the drafts to import", "primarysource draft import <name>"
        )
    rows: list[tuple[str, str, DSection, Counter[str], int, Status | None]] = []
    for n, rev in chosen:
        seg = store.segmented(n, rev)
        meta = store.meta(n, rev)
        status = store.status(n)
        for s in seg.sections:
            tf = Counter(_tokens(s.title) * 3 + _tokens(" ".join(b.text for b in s.blocks)))
            rows.append((n, rev, s, tf, sum(tf.values()), status))
        _ = meta
    avg = sum(r[4] for r in rows) / max(1, len(rows))
    df = {w: sum(1 for r in rows if r[3][w]) for w in set(words)}

    def score(row: tuple[str, str, DSection, Counter[str], int, Status | None]) -> float:
        total = 0.0
        for w in set(words):
            f = row[3][w]
            if f:
                idf = math.log(1 + (len(rows) - df[w] + 0.5) / (df[w] + 0.5))
                total += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * row[4] / max(avg, 1.0)))
        return total

    everything = [r for r in rows if all(r[3][w] for w in set(words))]
    relaxed = ""
    if not everything:
        everything = [r for r in rows if any(r[3][w] for w in set(words))]
        relaxed = "not every word matched in any one section; these match some of them" if everything else ""
    everything.sort(key=lambda r: (-score(r), r[0], r[1], r[2].head_line))
    lines = []
    dead = 0
    for n, rev, s, _tf, _len, status in everything[:limit]:
        mark = ""
        if status is not None and not lifecycle(status).alive:
            mark = f" [{lifecycle(status).level}]"
            dead += 1
        label = f"{s.num} " if s.num else ""
        lines.append(f"{n}-{rev}§{s.id}  {label}{s.title}{mark}: {_snippet(s.blocks, set(words))}")
    if not lines:
        return render("no section matched", {})
    notes = (
        [f"{dead} hit(s) are in drafts that are not alive (marked); check draft_info before citing"] if dead else []
    )
    return render("\n".join(lines), {"relaxed": relaxed, "warning": "; ".join(notes)})
