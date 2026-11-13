"""What a pkgdocs collection does: import a pinned edition, then docs, outline, read, search, cite, status.

A collection is a `Spec`: its trees (each a pinned source repository, with the files to take from it and a
`build` that turns them into documents), its licence and placement, and the spelling of its document ids. This
module holds the behaviour every one of them shares, so a collection directory is data plus a `build`.

Refs: `[<collection>:]<doc>[@<commit>][§<section>][#<anchor>][¶<n>]`. `§` takes a section id (`5.6.1`), an anchor
(`s-f-Source`), a heading, or a unique part of one; `@<commit>` (four or more hex digits, or a pin's label) picks
an imported edition other than the newest; `¶n` is the nth block of the section.

A read of `§s¶n` starts at block n and runs on through the subsections of `s`, so a count past the section's own
blocks goes on into them, one unit per subsection heading and per block, in reading order. That is what makes a
read's `next:` footer a ref: `§s¶<n>` where the next page starts. Lists (`docs`, `outline`, `search`) take a
0-based `start` and print `next: start=<n>`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path

from primarysource import cursor
from primarysource.budget import page
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.model import Unit, span_hash
from primarysource.pkgdocs import fetch, index, store
from primarysource.pkgdocs.model import Doc, Sec
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection
from primarysource.render import next_start, render

DOC_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._/+-]*(?:@[0-9A-Za-z][0-9A-Za-z._-]{1,39})?"
SECTION_PATTERN = r"[^#¶\n]+?"
_HASH_ESCAPE = "%23"
_BARE = re.compile(r"(?P<section>\d+(?:\.\d+)+)(?:@(?P<commit>[0-9A-Za-z][\w.-]{1,39}))?(?P<para>¶\d+)?")


@dataclass(frozen=True, slots=True)
class Licence:
    """The licence of a collection's text and where it may be placed. `redistribute` is `layer` (may be baked
    into an image), `volume` (user-supplied, never in an image) or `none`. `evidence` names the file in the
    source repository the licence was read from. `attribution` is the credit shown by `status`; `credit` is the
    shorter form a licence that requires attribution (CC-BY-SA) needs in every citation."""

    spdx: str
    redistribute: str
    attribution: str = ""
    evidence: str = ""
    credit: str = ""


@dataclass(frozen=True, slots=True)
class Pin:
    """One edition of a tree: a full commit, a human label (a tag), its date, the `fetch.manifest_digest` of the
    files taken from it, and where to fetch it (the sources are mirrors of each other and must give that digest)."""

    commit: str
    label: str
    date: str
    files_sha256: str | None
    sources: tuple[fetch.Source, ...]


@dataclass(frozen=True, slots=True)
class Build:
    """What a tree's `build` returns: the documents, chapter aliases (`5` -> `ch-controlfields`) and counts of the
    files it left out, by reason."""

    docs: tuple[Doc, ...]
    aliases: Mapping[str, str] = field(default_factory=dict)
    skipped: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TreeSpec:
    """One pinned repository (or one subtree of it). `pins[0]` is the current edition."""

    name: str
    title: str
    pins: tuple[Pin, ...]
    include: Callable[[str], bool]
    build: Callable[[Mapping[str, bytes], Pin], Build]


@dataclass(frozen=True, slots=True)
class Spec:
    """Everything that is particular to one collection."""

    name: str
    title: str
    licence: Licence
    trees: tuple[TreeSpec, ...]
    instructions: str
    example_refs: tuple[str, ...] = ()

    @property
    def prefix(self) -> str:
        return f"{self.name}_"

    @property
    def grammar(self) -> RefGrammar:
        return RefGrammar(DOC_PATTERN, SECTION_PATTERN)


@dataclass(frozen=True, slots=True)
class Report:
    """What one tree's import did."""

    tree: str
    commit: str
    label: str
    path: Path
    docs: int
    sections: int
    units: int
    files_sha256: str
    pinned: bool
    skipped: dict[str, int]
    warnings: int


def _norm(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(":.;,")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Library:
    """A collection's installed editions, read through a `Spec`. `home` replaces `$PRIMARYSOURCE_HOME` (tests)."""

    def __init__(self, spec: Spec, home: Path | None = None) -> None:
        self.spec = spec
        self._home = home

    # -- locations -------------------------------------------------------------------------------------------

    def base(self, tree: str) -> Path:
        root = self._home / self.spec.name if self._home is not None else collection_home(self.spec.name)
        return root / tree

    def _import(self) -> str:
        return f"primarysource {self.spec.name} import"

    def _editions(self) -> list[tuple[TreeSpec, store.Edition]]:
        """The newest installed edition of each tree that has one."""
        found: list[tuple[TreeSpec, store.Edition]] = []
        for tree in self.spec.trees:
            editions = store.installed(self.base(tree.name))
            if editions:
                found.append((tree, editions[0]))
        if not found:
            raise LibError(
                f"{self.spec.title} is not imported (nothing under {self.base('')})",
                f"{self.spec.prefix}status says what is pinned",
                self._import(),
            )
        return found

    def _by_commit(self, token: str) -> list[tuple[TreeSpec, store.Edition]]:
        want = token.lower()
        matches: list[tuple[TreeSpec, store.Edition]] = []
        for tree in self.spec.trees:
            labels = {p.label.lower(): p.commit for p in tree.pins}
            for edition in store.installed(self.base(tree.name)):
                if edition.commit.startswith(want) or labels.get(want) == edition.commit:
                    matches.append((tree, edition))
        return matches

    # -- import ----------------------------------------------------------------------------------------------

    def import_edition(
        self,
        tree: str | None = None,
        commit: str | None = None,
        archive: str | None = None,
        *,
        opener: fetch.Opener | None = None,
        throttle: fetch.Throttle | None = None,
        limits: fetch.Limits | None = None,
        allow_unpinned: bool = False,
    ) -> list[Report]:
        """Fetch (or read `archive`, a downloaded copy of) each selected tree at its pinned commit and install it."""
        chosen = [t for t in self.spec.trees if tree in (None, t.name)]
        if not chosen:
            names = ", ".join(t.name for t in self.spec.trees)
            raise LibError(f"no tree named {tree!r} in {self.spec.name} (trees: {names})", "")
        if archive is not None and len(chosen) != 1:
            names = ", ".join(t.name for t in self.spec.trees)
            raise LibError("--archive needs --tree, because each tree has its own archive", f"trees: {names}")
        return [self._import_tree(t, commit, archive, opener, throttle, limits, allow_unpinned) for t in chosen]

    def _import_tree(
        self,
        tree: TreeSpec,
        commit: str | None,
        archive: str | None,
        opener: fetch.Opener | None,
        throttle: fetch.Throttle | None,
        limits: fetch.Limits | None,
        allow_unpinned: bool,
    ) -> Report:
        pin = tree.pins[0]
        if commit is not None:
            matches = [p for p in tree.pins if p.commit.startswith(commit.lower()) or p.label == commit]
            if len(matches) != 1:
                have = ", ".join(f"{p.label} ({p.commit[:12]})" for p in tree.pins)
                raise LibError(f"{commit!r} is not one pinned edition of {tree.name} (pinned: {have})", "")
            pin = matches[0]
        expect = pin.files_sha256
        if expect is None and not allow_unpinned:
            raise LibError(
                f"{tree.name} {pin.label} has no recorded digest",
                "record the digest in the catalogue, or pass --allow-unpinned to trust this one fetch",
            )
        if allow_unpinned:
            expect = None
        if archive is not None:
            first = pin.sources[0]
            source = fetch.Source(archive, first.strip, subdir=first.subdir)
            fetched = fetch.read_local(archive, source, include=tree.include, expect=expect, limits=limits)
        else:
            fetched = fetch.fetch_tree(
                pin.sources, include=tree.include, expect=expect, limits=limits, opener=opener, throttle=throttle
            )
        built = tree.build(fetched.files, pin)
        ids = [d.id for d in built.docs]
        if not ids:
            raise LibError(f"nothing in the {tree.name} archive was selected", "the source layout may have changed")
        if len(set(ids)) != len(ids):
            repeated = sorted({i for i in ids if ids.count(i) > 1})[:5]
            raise LibError(
                f"the build produced duplicate document ids: {', '.join(repeated)}", "report the collection"
            )
        record = {
            "collection": self.spec.name,
            "tree": tree.name,
            "label": pin.label,
            "date": pin.date,
            "url": fetched.url,
            "files_sha256": fetched.files_sha256,
            "tar_sha256": fetched.tar_sha256,
            "gz_sha256": fetched.gz_sha256,
            "pinned": fetched.pinned,
            "archive_members": fetched.members,
            "selected_files": len(fetched.files),
            "selected_bytes": fetched.kept_bytes,
            "skipped": {**fetched.skipped, **dict(built.skipped)},
            "licence": {
                "spdx": self.spec.licence.spdx,
                "redistribute": self.spec.licence.redistribute,
                "attribution": self.spec.licence.attribution,
                "evidence": self.spec.licence.evidence,
            },
            "imported": _now(),
        }
        path = store.write_edition(self.base(tree.name), pin.commit, record, built.docs, built.aliases)
        sections = sum(len(d.sections) for d in built.docs)
        return Report(
            tree.name,
            pin.commit,
            pin.label,
            path,
            len(built.docs),
            sections,
            sum(len(s.units) for d in built.docs for s in d.sections),
            fetched.files_sha256,
            fetched.pinned,
            {**fetched.skipped, **dict(built.skipped)},
            sum(len(d.warnings) for d in built.docs),
        )

    # -- ref resolution --------------------------------------------------------------------------------------

    def _parse(self, text: str) -> tuple[Ref, str | None]:
        """(parsed ref, commit token or None). A leading `<collection>:` is accepted and ignored."""
        cleaned = text.strip()
        head = f"{self.spec.name}:"
        if cleaned.lower().startswith(head):
            cleaned = cleaned[len(head) :]
        bare = _BARE.fullmatch(cleaned)
        if bare:  # `5.6.1`, `5.6.1@aceb1daf`, `5.6.1¶2`: a section number with no document
            ref = self.spec.grammar.parse(f"§{bare['section']}{bare['para'] or ''}")
            return ref, bare["commit"]
        ref = self.spec.grammar.parse(cleaned)
        doc, commit = ref.doc, None
        if doc is not None and "@" in doc:
            doc, _, commit = doc.partition("@")
        section = ref.section.replace(_HASH_ESCAPE, "#") if ref.section else ref.section
        return Ref(doc or None, section, ref.para, ref.anchor, ref.lines), commit

    def _find_doc(self, token: str, commit: str | None) -> tuple[TreeSpec, store.Edition, str]:
        pool = self._by_commit(commit) if commit else self._editions()
        if commit and not pool:
            raise LibError(f"no imported edition matches {commit!r}", f"{self.spec.prefix}status lists them")
        for tree, edition in pool:
            if token in edition.entries:
                return tree, edition, token
            if token in edition.aliases:
                return tree, edition, edition.aliases[token]
        lowered = {k.lower(): k for _, e in pool for k in e.entries}
        if token.lower() in lowered:
            for tree, edition in pool:
                if lowered[token.lower()] in edition.entries:
                    return tree, edition, lowered[token.lower()]
        known = sorted({k for _, e in pool for k in e.entries})
        close = get_close_matches(token, known, n=5, cutoff=0.6)
        hint = f"did you mean: {', '.join(close)}" if close else f"{self.spec.prefix}docs lists them"
        raise LibError(f"no document {token!r} in {self.spec.title}", hint)

    def _section(self, doc: Doc, token: str | None, anchor: str | None) -> tuple[Sec, str]:
        """The section a ref names and a warning for the footer (empty when there is none)."""
        if token is None and anchor is None:
            if not doc.sections:
                raise LibError(f"{doc.id} has no sections", "")
            return doc.sections[0], ""
        for key in (token, anchor):
            if not key:
                continue
            found = [s for s in doc.sections if s.id == key] or [s for s in doc.sections if s.anchor == key]
            if not found:
                found = [s for s in doc.sections if s.anchor.lower() == key.lower()]
            if found:
                return found[0], ""
        want = _norm(token or anchor or "")
        exact = [s for s in doc.sections if _norm(s.title) == want]
        if exact:
            return exact[0], (
                f"{len(exact)} sections are titled {token!r}; the first was read" if len(exact) > 1 else ""
            )
        partial = [s for s in doc.sections if want and want in _norm(s.title)]
        if len(partial) > 1:
            starts = [s for s in partial if _norm(s.title).startswith(want)]
            partial = starts if len(starts) == 1 else partial
        if len(partial) == 1:
            return partial[0], ""
        if partial:
            listing = "; ".join(f"{s.id} {s.title}" for s in partial[:8])
            raise LibError(f"{token!r} matches {len(partial)} sections of {doc.id}", f"name one by id: {listing}")
        titles = [s.title for s in doc.sections]
        close = get_close_matches(token or "", titles, n=3, cutoff=0.5)
        hint = f"did you mean: {'; '.join(close)}" if close else f"{self.spec.prefix}outline('{doc.id}') lists them"
        raise LibError(f"no section {token or anchor!r} in {doc.id}", hint)

    def _target(self, text: str, *, subtree: bool = False) -> tuple[store.Edition, Doc, Sec, str, int | None]:
        """The edition, document, section, warning and `¶n` a ref names. `subtree` lets `¶n` count on past the
        section's own blocks into its subsections, as a read does."""
        ref, commit = self._parse(text)
        if ref.lines is not None:
            raise LibError("a line range is not a ref in this collection", "name a section: <doc>§<section>")
        doc_token, section = ref.doc, ref.section
        if doc_token is None:
            if section is None:
                raise LibError(f"not a ref: {text!r}", "expected <doc>§<section>[¶n]")
            # a bare section number: its first component names a chapter alias, as in `5.6.1`
            doc_token = section.split(".")[0]
        elif section is None and ref.anchor is None and doc_token not in self._known_ids(commit) and "." in doc_token:
            doc_token, section = doc_token.split(".")[0], doc_token
        _, edition, doc_id = self._find_doc(doc_token, commit)
        doc = edition.load(doc_id)
        sec, warning = self._section(doc, section, ref.anchor)
        count = len(self._ordered(doc, sec)) - 1 if subtree else len(sec.units)
        if ref.para is not None and not 1 <= ref.para <= count:
            what = "blocks" if count == len(sec.units) else "blocks and headings with its subsections"
            raise LibError(
                f"{doc.id}§{sec.id} has {count} {what}; there is no ¶{ref.para}",
                f"{self.spec.prefix}read('{self._ref(edition, doc, sec)}')",
            )
        return edition, doc, sec, warning, ref.para

    def _known_ids(self, commit: str | None) -> set[str]:
        pool = self._by_commit(commit) if commit else self._editions()
        return {k for _, e in pool for k in (*e.entries, *e.aliases)}

    def _ref(self, edition: store.Edition, doc: Doc, sec: Sec, para: int | None = None) -> str:
        text = f"{self.spec.name}:{doc.id}@{edition.commit[:12]}§{sec.id}"
        return text + (f"¶{para}" if para else "")

    def _citation(self, edition: store.Edition, doc: Doc, sec: Sec, para: int | None) -> str:
        source = doc.meta.get("path", "")
        label = f" {edition.label}" if edition.label else ""
        tree = str(edition.record.get("tree", ""))
        lic = self.spec.licence
        parts = [
            f'{doc.title}, "{sec.title}" §{sec.id}' + (f" ¶{para}" if para else ""),
            f"{self.spec.title} ({tree}{label}, commit {edition.commit[:12]})",
        ]
        if source:
            parts.append(source)
        parts.append(f"licence {lic.spdx}" + (f" ({lic.credit})" if lic.credit else ""))
        return self._ref(edition, doc, sec, para) + " -- " + "; ".join(parts)

    # -- the tools -------------------------------------------------------------------------------------------

    @staticmethod
    def _ordered(doc: Doc, sec: Sec) -> list[str]:
        """The units a read of `sec` pages through: its heading, its blocks, then each subsection's heading and
        blocks. `¶n` is `ordered[n]`, so the section's own `¶n` keeps its meaning."""
        ordered: list[str] = []
        inside = False
        for candidate in doc.sections:
            if candidate is sec:
                inside = True
            elif inside and candidate.depth <= sec.depth:
                break
            if inside:
                ordered.append("#" * min(candidate.depth, 6) + f" {candidate.id} {candidate.title}")
                ordered.extend(candidate.units)
        return ordered

    def docs(self, prefix: str = "", limit: int = 200, start: int = 0) -> str:
        """One line per document: `<id>  <title>`, optionally those whose id starts with `prefix`."""
        rows: list[str] = []
        for _, edition in self._editions():
            rows.extend(f"{e.id}  {e.title}" for e in edition.entries.values() if e.id.startswith(prefix))
        if not rows:
            return f"no documents with an id starting {prefix!r}\n" if prefix else "no documents\n"
        chosen, nxt = cursor.window(rows, start, limit)
        return render("\n".join(chosen), {"unit": f"{len(rows)} documents", "next": nxt})

    def outline(self, ref: str, start: int = 0, max_tokens: int = 4000) -> str:
        """A document's sections, each with the ref that reads it. `ref` names a document (`gitformat-pack`)."""
        parsed, commit = self._parse(ref)
        token = parsed.doc or (parsed.section or "").split(".")[0]
        if not token:
            raise LibError(f"not a document: {ref!r}", f"primarysource {self.spec.name} docs")
        _, edition, doc_id = self._find_doc(token, commit)
        doc = edition.load(doc_id)
        lines = [
            f"{'  ' * (s.depth - 1)}{s.id}  {s.title}  [{len(s.units)}]  {self._ref(edition, doc, s)}"
            for s in doc.sections
        ]
        if start < 0:
            raise LibError(f"start is a 0-based offset, not {start}", "pass the start= value of the last next: line")
        taken = page(lines, start + 1, max_tokens)
        footer: dict[str, str] = {"cite": self._citation(edition, doc, doc.sections[0], None)} if doc.sections else {}
        footer["unit"] = "block (the [n] after a title counts them)"
        footer["next"] = next_start(None if taken.next_start is None else taken.next_start - 1)
        if doc.warnings:
            footer["warning"] = "; ".join(doc.warnings)
        return render(f"{doc.title}\n" + "\n".join(taken.units), footer)

    def read(self, ref: str, max_tokens: int = 2000) -> str:
        """The text of a section, its subsections included, cut at block boundaries: from its heading, or from block
        n with `¶n`. The `next:` footer is the ref that reads the next page."""
        edition, doc, sec, warning, para = self._target(ref, subtree=True)
        if max_tokens < 1:
            raise LibError("max_tokens must be positive", "")
        taken = page(self._ordered(doc, sec), (para or 0) + 1, max_tokens)
        body = "\n\n".join(taken.units)
        one = para if para is not None and len(taken.units) == 1 and para <= len(sec.units) else None
        footer = {
            "cite": self._citation(edition, doc, sec, one),
            "unit": "block (¶n counts the blocks of one section, then on through its subsections)",
            "span": span_hash(body),
            "next": "" if taken.next_start is None else self._ref(edition, doc, sec, taken.next_start - 1),
        }
        notes = [w for w in (warning, *doc.warnings) if w]
        if notes:
            footer["warning"] = "; ".join(notes)
        return render(body, footer)

    def cite(self, ref: str) -> str:
        """The citation for a ref, with the hash of the exact text cited, and nothing else."""
        edition, doc, sec, _, para = self._target(ref)
        text = sec.units[para - 1] if para else "\n\n".join(sec.units)
        return render(self._citation(edition, doc, sec, para), {"span": span_hash(text)})

    def search(self, query: str, limit: int = 10, start: int = 0, doc_prefix: str = "") -> str:
        """Sections matching the words of `query`, best first, one line each with the ref that reads it."""
        if start < 0 or limit < 1:
            raise LibError(f"start is a 0-based offset and limit positive (got {start}, {limit})", "")
        scored: list[tuple[float, str]] = []
        relaxed = False
        for _, edition in self._editions():
            hits, was_relaxed = index.search(
                edition.index_path, query, limit=start + limit + 1, doc_prefix=doc_prefix
            )
            relaxed = relaxed or was_relaxed
            for hit in hits:
                doc = edition.entries[hit.doc]
                ref = f"{self.spec.name}:{hit.doc}@{edition.commit[:12]}§{hit.section}"
                scored.append((hit.score, f"{ref}: {doc.title} / {hit.title} -- {hit.snippet}"))
        scored.sort(key=lambda row: row[0])
        window, nxt = cursor.window([line for _, line in scored], start, limit)
        if not window:
            return render("no sections matched", {})
        footer: dict[str, str] = {"next": nxt}
        if relaxed:
            footer["relaxed"] = "no section had every word; these have some of them"
        return render("\n".join(window), footer)

    def status(self) -> str:
        """What is pinned, what is imported, and the licence."""
        lic = self.spec.licence
        lines = [
            f"{self.spec.title}",
            f"licence: {lic.spdx} ({lic.redistribute}){'; ' + lic.attribution if lic.attribution else ''}",
        ]
        for tree in self.spec.trees:
            have = {e.commit: e for e in store.installed(self.base(tree.name))}
            lines.append(f"tree {tree.name}: {tree.title}")
            for pin in tree.pins:
                got = have.get(pin.commit)
                state = (
                    f"imported {got.record.get('imported', '')} ({got.record.get('docs', '?')} documents)"
                    if got
                    else "not imported"
                )
                lines.append(f"  {pin.label} {pin.commit[:12]} {pin.date}: {state}")
            others = [c[:12] for c in have if c not in {p.commit for p in tree.pins}]
            if others:
                lines.append(f"  other imported commits: {', '.join(others)}")
        return "\n".join(lines) + "\n"


def pin_files(*names: str) -> Callable[[str], bool]:
    """An `include` that accepts exactly these paths."""
    wanted = frozenset(names)
    return lambda path: path in wanted


def matching(pattern: str) -> Callable[[str], bool]:
    """An `include` that accepts paths matching the regular expression `pattern` (fully)."""
    compiled = re.compile(pattern)
    return lambda path: compiled.fullmatch(path) is not None


def parse_docs(
    files: Mapping[str, bytes], reader: Callable[[bytes, str], Doc], ids: Sequence[tuple[str, str]]
) -> list[Doc]:
    """Read `(path, doc id)` pairs with `reader`, recording the source path in each document's meta."""
    return [reader(files[path], doc_id).with_meta(path=path) for path, doc_id in ids if path in files]


def make_collection(spec: Spec, package: str) -> Collection:
    """The registry entry for `spec`, whose `server` and `cli` targets live in `package` (`server.py`, `cli.py`)."""
    return Collection(
        name=spec.name,
        title=spec.title,
        prefix=spec.prefix,
        unit=Unit.BLOCK,
        grammar=spec.grammar,
        server=f"{package}.server:server",
        cli=f"{package}.cli:main",
    )
