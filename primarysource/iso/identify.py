"""How the iso collection recognises an ISO publication in a supplied PDF (`registry.Collection.identify`).

An ISO cover prints `Reference number` and then the designation (`ISO/IEC 7816-3:2006(E)`), and every later page
repeats the designation as a running header, so the cover and the header outweigh whatever the file is called.
The PDF's title metadata is often useless (`Microsoft Word - C038770e.doc`) and is only one piece of evidence.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates, points
from primarysource.iso.designation import _PATTERN, Designation, _from_match

_REFERENCE = re.compile(r"Reference\s+number\s+(?P<designation>ISO\S*(?:\s+\S+){0,3})", re.IGNORECASE)
REFERENCE_POINTS = 3


def _label(match: re.Match[str]) -> str | None:
    return _from_match(match).label


def designation_of(label: str) -> Designation:
    match = _PATTERN.fullmatch(label)
    if match is None:  # every label this module produces parses; a foreign one is a bug
        raise ValueError(label)
    return _from_match(match)


_EDITION = re.compile(r"\bedition\b", re.IGNORECASE)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_STOP = re.compile(r"Reference\s+number|\bPartie\b|[àâçéèêëîïôûùüÿœ]")
_JUNK_TITLE = re.compile(r"^\s*$|^(?:Microsoft Word|untitled)|\.(?:docx?|pdf|indd|fm)\b", re.IGNORECASE)


def cover_title(probe: Probe) -> str:
    """The English title printed on an ISO cover: the lines after the edition line, up to the French title or
    the `Reference number` line. Empty when the cover does not have that shape."""
    if not probe.pages:
        return ""
    lines = [" ".join(line.split()) for line in probe.pages[0].splitlines() if line.strip()]
    start = next((i + 1 for i, line in enumerate(lines) if _EDITION.search(line)), None)
    if start is None:
        return ""
    title: list[str] = []
    for line in lines[start:]:
        if _STOP.search(line):
            break
        if not _DATE.fullmatch(line):
            title.append(line)
    return " ".join(title)


def useful_title(title: str, designation: str) -> bool:
    """False for title metadata that names a file or a word processor (`Microsoft Word - C038770e.doc`) or that is
    only the designation again."""
    return not _JUNK_TITLE.search(title) and title.strip() != designation


def _merge(found: list[Candidate]) -> list[Candidate]:
    """One candidate per document: `ISO 7816-3:2006` from a file name and `ISO/IEC 7816-3:2006` from the cover
    are the same document (`7816-3@2006`), spelled by the surest evidence, with the evidence pooled."""
    by_doc: dict[str, list[Candidate]] = {}
    for candidate in found:
        by_doc.setdefault(designation_of(candidate.designation).doc, []).append(candidate)
    merged: list[Candidate] = []
    for group in by_doc.values():
        best = max(group, key=lambda c: c.score)
        evidence = tuple(dict.fromkeys(e for c in group for e in c.evidence))
        merged.append(Candidate(best.collection, best.designation, points(evidence), evidence, best.command))
    return merged


def identify(probe: Probe) -> list[Candidate]:
    """ISO designations in the probe, the cover's `Reference number` line counting 3 more."""

    def command(label: str) -> str:
        where = f'"{probe.path}"' if probe.path is not None else f'"{probe.name}"'
        return f'primarysource iso import {where} --designation "{label}"'

    found = _merge(candidates(probe, "iso", _PATTERN, _label, command))
    if not probe.pages:
        return found
    referenced = set()
    for match in _REFERENCE.finditer(probe.pages[0]):
        inner = _PATTERN.search(match["designation"])
        if inner is not None:
            referenced.add(_from_match(inner).label)
    out: list[Candidate] = []
    for candidate in found:
        if candidate.designation in referenced:
            candidate = Candidate(
                candidate.collection,
                candidate.designation,
                candidate.score + REFERENCE_POINTS,
                ("cover reference number", *candidate.evidence),
                candidate.command,
            )
        out.append(candidate)
    return out
