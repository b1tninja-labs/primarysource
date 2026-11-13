"""A full-text index over one edition, on the core's index (`primarysource/index.py`), tagged with its source.

One SQLite file per edition, built by `primarysource.index.rebuild` (a temporary file `os.replace`d over the old
one, so a server sees the old index or the new one, never half of one) and opened for serving with
`primarysource.index.open_read` (`?mode=ro`: nothing is created or migrated, and a read-only volume works).

How a clause sits in the core's schema, chosen so itulib's measured BM25 weights carry over unchanged:

- every clause is a core document of one section, in reading order. `doc_id` is its zero-padded ordinal, so two
  fragments that carry the same number both survive and `fragments` can say so;
- the document title is the clause number. It fills the core's `doc_title` column, weighted 2.0 as itulib's
  `number` column was;
- the section title is the document's own heading, or empty when the clause has none (the label `outline` shows
  is then the first sentence, derived from the body). It is weighted 15.0 as itulib's `head` column was;
- the section's one unit is the clause body, weighted 1.0. ¶n is still the nth sentence of that body.

One more document, `~edition`, has no sections and holds what the index was built from as JSON in its title: the
collection's own schema, the edition key and the PDF's sha256, size and modification time. The index refuses to
serve when the PDF no longer matches. That is the difference between "this clause says X in the edition you
hold" and a stale table that reports the same confident answer after ITU republished something - a gate that
silently skips, in the shape of a search result. The check is by `stat` first: the PDF is hashed only when its
size or modification time differs from the recorded ones, and a hash that matches is remembered for the life of
the process, so serving does not read the whole PDF on every call. The cost, stated: a file rewritten with the
same size and its old modification time restored is not noticed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from primarysource import index as core
from primarysource.errors import LibError
from primarysource.model import Document, Section, Unit

from . import corpus, text
from .sources import Amendment, Edition

SCHEMA = "4"  # this collection's layout on the core schema; the core's own version is its PRAGMA user_version
META_ID = "~edition"
CANDIDATES = 150
DEMOTION = 0.6  # score multiplier for clauses that are rarely the answer; flat optimum between 0.4 and 0.8
_INFORMATIVE = re.compile(r"does not form an integral part", re.IGNORECASE)

# BM25 column weights as itulib measured them: the clause number 2.0, the document's own heading 15.0 (a heading
# match is a much stronger signal than the same word somewhere in a body), the body 1.0.
NUMBER_WEIGHT, HEADING_WEIGHT, BODY_WEIGHT = 2.0, 15.0, 1.0
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Hit:
    number: str
    title: str
    excerpt: str
    score: float  # higher is better: BM25 negated, times the demotion


@dataclass(frozen=True)
class Results:
    """One page of search hits. `relaxed`: no clause held every term, so these hold some. `next_start`: the 0-based
    `start` of the next page, or None at the end. No hits means nothing matched."""

    hits: tuple[Hit, ...]
    relaxed: bool
    next_start: int | None


def _db_path(edition: Edition) -> pathlib.Path:
    return corpus.home() / "index" / f"{edition.key.replace('#', '-')}.sqlite3"


def index_command(edition: Edition) -> str:
    return f"primarysource itu index {edition.key}"


def sync_command(edition: Edition) -> str:
    return f"primarysource itu sync {edition.key}"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _documents(rows: tuple[text.Clause, ...], meta: dict[str, object]) -> Iterator[Document]:
    yield Document(META_ID, json.dumps(meta, sort_keys=True), Unit.SENTENCE)
    for ordinal, row in enumerate(rows):
        section = Section(
            id=row.number,
            title=row.title if row.heading else "",
            units=(row.body,) if row.body else (),
            depth=row.number.count(".") + 1,
        )
        yield Document(f"{ordinal:05d}", row.number, Unit.SENTENCE, (section,))


def build(edition: Edition) -> int:
    """(Re)build the index for one edition and swap it in atomically. Returns the clause count."""
    pdf = corpus.require(edition)
    stat = pdf.stat()
    digest = _sha256(pdf)
    extracted = text.pages(pdf)
    rows = text.clauses(extracted, text.headings(pdf, extracted))
    if not rows:
        raise LibError(
            f"{edition.key}: extracted 0 clauses. The corpus exists but nothing parsed, which is a failure of the "
            "extractor, not an empty document. Refusing to write an empty index.",
            "",
            f"check that {pdf} opens as a PDF, then run: primarysource itu fetch {edition.key} --refresh",
        )
    meta: dict[str, object] = {
        "schema": SCHEMA,
        "edition": edition.key,
        "pdf_sha256": digest,
        "pdf_octets": stat.st_size,
        "pdf_mtime_ns": stat.st_mtime_ns,
        "clauses": len(rows),
    }
    core.rebuild(_db_path(edition), _documents(rows, meta), rebuild_command=index_command(edition))
    _VERIFIED.pop(pdf, None)
    return len(rows)


# PDF path -> (size, mtime_ns, sha256) that this process hashed and found to match its index.
_VERIFIED: dict[pathlib.Path, tuple[int, int, str]] = {}


def _check_source(edition: Edition, meta: dict[str, object]) -> None:
    """Refuse when the PDF on disk is not the one the index was built from. Hashes only when `stat` differs."""
    pdf = corpus.pdf_path(edition)
    try:
        stat = pdf.stat()
    except FileNotFoundError:
        raise LibError(
            f"{edition.key}: the PDF this index was built from is not in {corpus.home()}",
            "itu_info shows which editions are fetched",
            sync_command(edition),
        ) from None
    expected = str(meta.get("pdf_sha256", ""))
    if (stat.st_size, stat.st_mtime_ns) == (meta.get("pdf_octets"), meta.get("pdf_mtime_ns")):
        return
    if _VERIFIED.get(pdf) == (stat.st_size, stat.st_mtime_ns, expected):
        return
    if _sha256(pdf) != expected:
        raise LibError(
            f"{edition.key}: the corpus changed since the index was built",
            "itu_info shows the registered digest of each edition",
            index_command(edition),
        )
    _VERIFIED[pdf] = (stat.st_size, stat.st_mtime_ns, expected)


@contextmanager
def _open(edition: Edition) -> Iterator[sqlite3.Connection]:
    """A read-only connection to an edition's index that matches the PDF on disk, closed on exit."""
    path = _db_path(edition)
    if not path.is_file():
        raise LibError(f"{edition.key}: no index", "itu_info shows which editions are fetched", sync_command(edition))
    try:
        connection = core.open_read(path, rebuild_command=index_command(edition))
    except LibError as error:  # the core names the command in `hint`; here it is a human's to run, so `action`
        raise LibError(error.message, "", index_command(edition)) from None
    try:
        row = connection.execute("SELECT title FROM documents WHERE doc_id = ?", (META_ID,)).fetchone()
        meta = json.loads(row[0]) if row else {}
        if not isinstance(meta, dict) or meta.get("schema") != SCHEMA:
            raise LibError(
                f"{edition.key}: the index was built by an older itulib or primarysource", "", index_command(edition)
            )
        _check_source(edition, meta)
        yield connection
    finally:
        connection.close()


def _display(title: str, body: str) -> str:
    """The label of a clause: its own heading, or the first sentence of its body when it has none."""
    return title or text.first_sentence(body)


def search(edition: Edition, query: str, limit: int = 8, start: int = 0) -> Results:
    """The best clauses for a question, best first, `limit` from the 0-based `start`.

    The core's search (`primarysource.index.search`): every term is required first, and only when no clause holds
    them all will any term do, which the result says with `relaxed`. The terms are the query's words without
    question words and filler (`text.query_words`, measured on itulib's blind retrieval set). BM25 weights the
    heading above the number above the body, and each hit is then adjusted by where the clause sits: definitions
    (clause 3.x) and informative annexes are demoted unless the query asks what a term means, because a
    definition that merely mentions the words is rarely the rule that was asked about.

    Tried and dropped on the blind set because they did not help: pushing a subtree's best score up to its
    heading-only parent, and a bonus for words found in the heading.
    """
    if start < 0:
        raise LibError(f"start={start} is negative", "start is a 0-based offset; pass the value of next:")
    words = " ".join(text.query_words(query))
    wants_definitions = text.asks_for_definition(query)
    with _open(edition) as connection:
        informative = _informative_annexes(connection)

        def adjust(hit: core.Hit, _query: str) -> float:
            number, factor = hit.section_id, 1.0
            if number.startswith("3.") and not wants_definitions:
                factor *= DEMOTION
            if number.split(".")[0] in informative:
                factor *= DEMOTION
            return factor

        ranking = core.Ranking(NUMBER_WEIGHT, HEADING_WEIGHT, BODY_WEIGHT, adjust=adjust, candidates=CANDIDATES)
        found = core.search(connection, words, ranking=ranking, limit=limit, start=start)
        marks = ",".join("?" * len(found.hits))
        bodies: dict[str, str] = dict(
            connection.execute(
                f"SELECT doc_id, body FROM sections WHERE doc_id IN ({marks})",  # noqa: S608 - only '?' marks
                [hit.doc_id for hit in found.hits],
            ).fetchall()
        )
    hits = []
    for hit in found.hits:
        title = _display(hit.title, bodies.get(hit.doc_id, ""))
        hits.append(Hit(hit.section_id, title, hit.snippet or title, hit.score))
    return Results(tuple(hits), found.relaxed, found.next_start)


def _informative_annexes(connection: sqlite3.Connection) -> set[str]:
    """Letters of the annexes that say they do not form an integral part of the recommendation."""
    return {
        number
        for number, body in connection.execute("SELECT section_id, body FROM sections WHERE length(section_id) = 1")
        if _INFORMATIVE.search(body)
    }


def _rows(edition: Edition) -> list[tuple[str, str, str]]:
    """(number, heading or "", body) of every clause, in reading order."""
    with _open(edition) as connection:
        return connection.execute("SELECT section_id, title, body FROM sections ORDER BY id").fetchall()


def read(edition: Edition, number: str) -> text.Clause | None:
    with _open(edition) as connection:
        row = connection.execute(
            "SELECT section_id, title, body FROM sections WHERE section_id = ? ORDER BY id LIMIT 1", (number,)
        ).fetchone()
    if row is None:
        return None
    return text.Clause(number=row[0], title=_display(row[1], row[2]), body=row[2], heading=bool(row[1]))


def outline(edition: Edition) -> tuple[tuple[str, str], ...]:
    return tuple((number, _display(title, body)) for number, title, body in _rows(edition))


# --- paging, citation, references ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """A budgeted slice of one clause. `next` is the ¶ the rest starts at, or None at the end."""

    number: str
    title: str
    first: int
    last: int
    total: int
    text: str
    next: int | None


def citation(edition: Edition | Amendment, number: str, para: int | None = None) -> str:
    """`Rec. ITU-T X.690 (02/2021) §11.6¶2`. Built from the registry, never typed by hand."""
    label = edition.edition if isinstance(edition, Edition) else edition.label
    tail = f"¶{para}" if para else ""
    return f"Rec. ITU-T {edition.rec} ({label}) §{number}{tail}"


def page(edition: Edition, number: str, *, start: int = 1, max_tokens: int = 2000) -> Page | None:
    """Sentences `start`.. of a clause, cut at a sentence boundary within the token budget.

    At least one sentence is always returned, so a single over-long sentence cannot stall a caller that is
    following `next`. Each sentence is prefixed with its `[¶n]` so any of them is citable.
    """
    clause = read(edition, number)
    if clause is None:
        return None
    if not clause.body:
        return Page(clause.number, clause.title, 1, 0, 0, "", None)
    units = text.sentences(clause.body)
    if not 1 <= start <= max(len(units), 1):
        raise LibError(
            f"§{number} has {len(units)} sentences; ¶{start} is outside 1..{len(units)}",
            f"itu_read('{number}') reads the clause from its first sentence",
        )
    budget = max(max_tokens, 1) * CHARS_PER_TOKEN
    used, last = 0, start - 1
    for n in range(start, len(units) + 1):
        cost = len(units[n - 1]) + 8
        if last >= start and used + cost > budget:
            break
        used += cost
        last = n
    body = " ".join(f"[¶{n}] {units[n - 1]}" for n in range(start, last + 1))
    return Page(clause.number, clause.title, start, last, len(units), body, last + 1 if last < len(units) else None)


def fragments(edition: Edition, number: str) -> int:
    """How many extracted fragments carry this clause number. More than one means the splitter could not tell a
    heading from a numbered sub-item or a table cell, and `read` returns the first. Callers should say so."""
    with _open(edition) as connection:
        row = connection.execute("SELECT count(*) FROM sections WHERE section_id = ?", (number,)).fetchone()
    return int(row[0])


def sentence(edition: Edition, number: str, para: int) -> str | None:
    clause = read(edition, number)
    units = text.sentences(clause.body) if clause else ()
    return units[para - 1] if 1 <= para <= len(units) else None


def normative_statements(edition: Edition, number: str) -> tuple[tuple[int, str], ...] | None:
    clause = read(edition, number)
    return None if clause is None else text.normative(clause.body)


@dataclass(frozen=True)
class Links:
    number: str
    clauses: tuple[str, ...]  # same-document clauses this one points at that actually exist
    unresolved: tuple[str, ...]  # pointed at but not found in the index: extraction gap, or a cross-document ref
    recommendations: tuple[str, ...]
    standards: tuple[str, ...]
    cited_by: tuple[str, ...]


def links(edition: Edition, number: str) -> Links | None:
    """Outgoing references of a clause, and the clauses of the same edition that point back at it."""
    rows = [(n, body) for n, _title, body in _rows(edition)]
    known = {row[0] for row in rows}
    body = next((row[1] for row in rows if row[0] == number), None)
    if body is None:
        return None
    found = text.refs(body)
    back = tuple(n for n, b in rows if n != number and _points_at(b, number))
    return Links(
        number=number,
        clauses=tuple(c for c in (*found.clauses, *found.bare) if c in known and c != number),
        unresolved=tuple(c for c in found.clauses if c not in known),
        recommendations=tuple(r for r in found.recommendations if r != edition.rec),
        standards=found.standards,
        cited_by=back,
    )


@dataclass(frozen=True)
class GrepHit:
    number: str
    excerpt: str


def grep(
    edition: Edition, pattern: str, *, start: int = 0, max_tokens: int = 2000, context: int = 120
) -> tuple[tuple[GrepHit, ...], int | None]:
    """Regex over clause bodies in ONE query, with an excerpt around the first match, cut to a token budget.

    Returns (hits, next start): matching clauses from the 0-based `start`, and the `start` of the rest when the
    budget stopped the listing, or None when it is complete. At least one hit is returned when any remain.
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise LibError(f"{pattern!r} is not a regular expression: {error}", "itu_search takes plain words") from None
    if start < 0:
        raise LibError(f"start={start} is negative", "start is a 0-based offset; pass the value of next:")
    budget, used, seen = max(max_tokens, 1) * CHARS_PER_TOKEN, 0, 0
    hits: list[GrepHit] = []
    for number, _title, body in _rows(edition):
        match = compiled.search(body)
        if not match:
            continue
        seen += 1
        if seen <= start:
            continue
        excerpt = body[max(match.start() - context, 0) : match.end() + context]
        cost = len(excerpt) + len(number) + 20
        if hits and used + cost > budget:
            return tuple(hits), start + len(hits)
        used += cost
        hits.append(GrepHit(number, excerpt))
    return tuple(hits), None


def _points_at(body: str, number: str) -> bool:
    found = text.refs(body)
    return number in found.clauses or number in found.bare


def slice_rows(
    rows: tuple[tuple[str, str], ...], start: int, max_tokens: int
) -> tuple[tuple[tuple[str, str], ...], int | None]:
    """(rows[start:...], next start or None), cut to a token budget. Always returns at least one row."""
    if not 0 <= start <= len(rows):
        raise LibError(
            f"start={start} is outside 0..{len(rows)}", "start is a 0-based offset; pass the value of next:"
        )
    budget, used, end = max(max_tokens, 1) * CHARS_PER_TOKEN, 0, start
    while end < len(rows):
        cost = len(rows[end][0]) + len(rows[end][1]) + 12
        if end > start and used + cost > budget:
            break
        used += cost
        end += 1
    return rows[start:end], (end if end < len(rows) else None)


@dataclass(frozen=True)
class Comparison:
    number: str
    in_a: bool
    in_b: bool
    same: bool
    removed: tuple[tuple[int, str], ...]  # (¶ in edition a, sentence) present only in a
    added: tuple[tuple[int, str], ...]  # (¶ in edition b, sentence) present only in b


def _sentence_key(sentence: str) -> str:
    """What two sentences must share to count as the same across editions.

    The extractor splits words differently in different editions ("a ppear"), drops mathematical symbols from some
    ("M ≠ M'" loses its sign) and the editions cite each other in a different order ("ITU-T Rec. X.680" became
    "Rec. ITU-T X.680"). So matching ignores case, whitespace, punctuation and symbols. The cost is stated in the
    docstring of `compare`: a change that consists only of a symbol or punctuation mark is invisible.
    """
    return re.sub(r"[\W_]+", "", sentence.replace("ITU-T Rec.", "Rec. ITU-T")).casefold()


def compare(a: Edition, b: Edition, number: str) -> Comparison:
    """What changed in clause `number` between two editions, by sentence.

    Numbering can differ between editions, so a clause that exists in only one is reported as such rather than
    as a deletion: the rule may simply have moved. Matching is by sentence, so a reworded sentence appears as one
    removed and one added. Matching ignores punctuation and symbols (see `_sentence_key`), so a change consisting
    only of a symbol, such as a sign or a comparison operator, is NOT reported: check the PDF when that matters.
    """
    import difflib

    clause_a, clause_b = read(a, number), read(b, number)
    sa = text.sentences(clause_a.body) if clause_a and clause_a.body else ()
    sb = text.sentences(clause_b.body) if clause_b and clause_b.body else ()
    keys_a, keys_b = [_sentence_key(s) for s in sa], [_sentence_key(s) for s in sb]
    matcher = difflib.SequenceMatcher(a=keys_a, b=keys_b, autojunk=False)
    removed: list[tuple[int, str]] = []
    added: list[tuple[int, str]] = []
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op in {"delete", "replace"}:
            removed += [(n + 1, sa[n]) for n in range(a0, a1)]
        if op in {"insert", "replace"}:
            added += [(n + 1, sb[n]) for n in range(b0, b1)]
    return Comparison(
        number,
        clause_a is not None,
        clause_b is not None,
        clause_a is not None and clause_b is not None and not removed and not added,
        tuple(removed),
        tuple(added),
    )


def children(edition: Edition, number: str) -> tuple[tuple[str, str], ...]:
    """The nearest descendants of a clause that has no body of its own. Heading-only clauses ("8.1.2 Identifier
    octets") are not indexed, so `read` would otherwise say "no clause" about a clause that plainly exists."""
    below = [(n, t) for n, t in outline(edition) if n.startswith(number + ".")]
    if not below:
        return ()
    shallowest = min(n.count(".") for n, _ in below)
    return tuple(row for row in below if row[0].count(".") == shallowest)


def top_level(edition: Edition, depth: int = 2) -> tuple[tuple[str, str], ...]:
    """Clauses whose number has at most `depth` dotted components: the shape of the document, not its detail."""
    return tuple((n, t) for n, t in outline(edition) if n.count(".") + 1 <= depth)
