"""What a supplied document is: which collection knows it, and as which designation (`primarysource identify`).

People keep vendor and standards PDFs under whatever name the download gave them, so an import cannot rely on the
file name. A `Probe` reads the file name, the PDF's title metadata and the text of its first pages once; each
collection that declares an `identify` hook (`registry.Collection.identify`, a "module:function" taking a `Probe`
and returning `Candidate`s) looks for its own designations in it. `score` is the common rule every hook uses,
so candidates from different collections compare:

- the designation on the first page (the cover): 3;
- on two or more of the later probed pages (a running header): 2;
- in the PDF's title metadata: 2;
- in the file name: 1.

A hook may add evidence of its own (ISO's `Reference number` line on the cover). Nothing here imports anything;
it says what the document is and the command that imports it.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from primarysource.errors import LibError

PROBE_PAGES = 3
MAX_PROBE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Probe:
    """What identification reads: the file's name and path, its title metadata, and its first pages' text."""

    name: str
    title: str = ""
    pages: tuple[str, ...] = ()
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One answer: `collection` knows this document as `designation`. Higher `score` is surer."""

    collection: str
    designation: str
    score: int
    evidence: tuple[str, ...] = field(default=())
    command: str = ""


def probe_pdf(path: Path, pages: int = PROBE_PAGES) -> Probe:
    """Read a PDF's title metadata and its first `pages` pages of text. Needs `pypdf` (any PDF extra)."""
    from primarysource.readers.pdf import _pypdf

    pypdf = _pypdf()
    try:
        if path.stat().st_size > MAX_PROBE_BYTES:
            raise LibError(f"{path.name} is over {MAX_PROBE_BYTES} bytes", "")
        reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()), strict=False)
        meta = reader.metadata
        title = str(meta.title) if meta is not None and meta.title else ""
        texts = tuple(str(reader.pages[i].extract_text() or "") for i in range(min(pages, len(reader.pages))))
    except LibError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on hostile input
        raise LibError(f"could not read {path.name}: {type(exc).__name__}: {exc}", "is it a PDF?") from exc
    return Probe(path.name, title, texts, path)


def score[K](probe: Probe, pattern: re.Pattern[str], key: Callable[[re.Match[str]], K | None]) -> dict[K, list[str]]:
    """Every designation `pattern` finds in the probe, keyed by `key(match)` (None skips a match), with the
    evidence for it; `points` turns the evidence into a score."""
    found: dict[K, list[str]] = {}

    def note(text: str, label: str) -> set[K]:
        keys: set[K] = set()
        for match in pattern.finditer(text):
            value = key(match)
            if value is not None:
                keys.add(value)
        for value in keys:
            found.setdefault(value, []).append(label)
        return keys

    if probe.pages:
        note(probe.pages[0], "cover")
    later: dict[K, int] = {}
    for text in probe.pages[1:]:
        for value in note(text, "page"):
            later[value] = later.get(value, 0) + 1
    for value, count in later.items():
        evidence = [e for e in found[value] if e != "page"]
        found[value] = [*evidence, *(["running header"] if count >= 2 else ["one later page"])]
    note(probe.title, "title metadata")
    note(probe.name, "file name")
    return found


POINTS = {"cover": 3, "running header": 2, "title metadata": 2, "file name": 1, "one later page": 0}


def points(evidence: Iterable[str]) -> int:
    """The score of a designation's evidence under the common rule (unknown evidence counts as the hook says)."""
    return sum(POINTS.get(e, 0) for e in set(evidence))


def identify(probe: Probe, hooks: Sequence[tuple[str, Callable[[Probe], list[Candidate]]]]) -> list[Candidate]:
    """Every collection's candidates, surest first; a hook that fails is skipped, never fatal."""
    out: list[Candidate] = []
    for _name, hook in hooks:
        try:
            out.extend(hook(probe))
        except LibError:
            continue
    return sorted((c for c in out if c.score > 0), key=lambda c: (-c.score, c.collection, c.designation))


def registered_hooks() -> list[tuple[str, Callable[[Probe], list[Candidate]]]]:
    """The `identify` hooks of every registered collection that has one and whose code loads."""
    from primarysource import registry

    hooks: list[tuple[str, Callable[[Probe], list[Candidate]]]] = []
    for name in registry.available():
        try:
            collection = registry.load(name)
            if collection.identify:
                hooks.append((name, registry.attribute(collection, collection.identify, "identify hook")))
        except LibError:
            continue
    return hooks


def identify_path(path: Path) -> list[Candidate]:
    """Probe one PDF and ask every registered collection what it is."""
    return identify(probe_pdf(path), registered_hooks())


def describe(path: Path, found: Sequence[Candidate]) -> str:
    """One report block for `primarysource identify`."""
    if not found:
        return f"{path.name}: not recognised as any collection's document"
    best = found[0]
    lines = [f"{path.name}: {best.designation} ({best.collection}; {', '.join(best.evidence)})"]
    if best.command:
        lines.append(f"  import: {best.command}")
    lines += [f"  also: {c.designation} ({c.collection}, score {c.score})" for c in found[1:4]]
    return "\n".join(lines)


_PDF = re.compile(r"\.pdf$", re.IGNORECASE)


def pdfs(paths: Sequence[Path]) -> list[Path]:
    """The PDFs named, with directories expanded to the PDFs directly inside them."""
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(p for p in path.iterdir() if p.is_file() and _PDF.search(p.name)))
        else:
            out.append(path)
    return out


def candidates(
    probe: Probe,
    collection: str,
    pattern: re.Pattern[str],
    designation: Callable[[re.Match[str]], str | None],
    command: Callable[[str], str],
    *,
    file_pattern: re.Pattern[str] | None = None,
) -> list[Candidate]:
    """A hook in one call: every designation `pattern` finds (as `designation(match)` spells it), scored by the
    common rule, each with the command that imports it. `file_pattern` also reads the file name (a publisher's
    download name such as `T-REC-X.690-202102`), worth what a file-name match is worth."""
    found = score(probe, pattern, designation)
    if file_pattern is not None:
        for value in {designation(m) for m in file_pattern.finditer(probe.name)} - {None}:
            if value is not None and "file name" not in found.setdefault(value, []):
                found[value].append("file name")
    return [
        Candidate(collection, value, points(evidence), tuple(dict.fromkeys(evidence)), command(value))
        for value, evidence in found.items()
    ]
