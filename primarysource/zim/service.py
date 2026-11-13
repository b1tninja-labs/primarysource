"""What the tools do, as functions returning plain dicts. The CLI prints them and the MCP server serialises
them; neither adds behaviour, so what a test pins here is what both surfaces do.

Budgets are in *estimated* tokens, `len(text) // CHARS_PER_TOKEN`. That is the same crude estimate rfclib and
itulib use: the point is that a response is bounded and says when the bound, not the corpus, ended it.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any

from primarysource import budget
from primarysource.model import span_hash

from . import _libzim, library, manage, snapshot
from .errors import LibraryNotFound, ZimloreError
from .library import Book
from .markdown import MAX_OUTPUT_CHARS, Document, Heading, convert, join_blocks, to_plain
from .refs import Ref, format_ref, parse_ref

CHARS_PER_TOKEN = 4
HTML_TYPES = ("text/html", "application/xhtml+xml")
TEXT_TYPES = ("text/plain", "text/markdown")
MAX_REDIRECTS = 8
DEFAULT_MAX_ENTRY_BYTES = 8 * 1024 * 1024
MAX_ENTRY_ENV = "PRIMARYSOURCE_ZIM_MAX_ENTRY_BYTES"
LEGACY_MAX_ENTRY_ENV = "ZIMLORE_MAX_ENTRY_BYTES"
"""The largest entry `document` will read and convert, by the size libzim reports before any byte is read. A page
this size is not documentation: a 16 MB page of 2,000,000 paragraphs took 47 s to convert, and an entry of
gigabytes was read into memory whole. Set `PRIMARYSOURCE_ZIM_MAX_ENTRY_BYTES`
(legacy: `ZIMLORE_MAX_ENTRY_BYTES`) to a larger number to read one anyway."""
MAX_TOKENS_CAP = 8_000
"""The most one `read`, `search`, `links` or `outline` call may spend. A model that passed `max_tokens=100000` once
received a 52,000-token page; 8,000 is four default reads, and a longer page is reached by paging, which is
cheaper to decide on than to undo. A larger request is cut to this and the result says so in `clamped`."""
MAX_LIMIT = 500
SEARCH_DEPTH = 25
"""How many candidates each library is asked for at least, whatever page of hits is wanted (see `search`)."""
_DOCS: OrderedDict[tuple[str, str], tuple[Any, str, Document]] = OrderedDict()
_DOC_CACHE = 64


def tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _bounded(name: str, value: int, low: int, high: int, clamped: dict[str, int] | None = None) -> int:
    """Validate an agent-supplied number. Below `low` (or not an integer) is an error that says the range, because
    a quiet fix would turn a mistake into a wrong answer (`limit=0` once read as 'no entry matched'). Above `high`
    is cut to it and recorded in `clamped`, which the caller puts in its result."""
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ZimloreError(f"{name} must be an integer of at least {low}, got {value!r}", f"{name} is {low}..{high}")
    if value > high:
        if clamped is not None:
            clamped[name] = high
        return high
    return value


# --- locating things -----------------------------------------------------------------------------------------


def _scan() -> library.Scan:
    scanned = library.scan()
    if not scanned.books:
        error = library.empty_library_error(scanned)
        error.extra.update(
            tool_hint="no ZIM files are installed, so nothing can be read; zim_available lists what could be fetched",
            user_action="ask the user to download a library and put it in the directory named in `searched`",
            user_command=error.cli_hint,
        )
        error.settle()
        raise error
    return scanned


def _select(name: str, scanned: library.Scan) -> library.Selection:
    """`library.select`, and when nothing installed matches, say what the offline snapshot says is obtainable.
    A missing or unreadable snapshot never turns the miss into a different error. A version that is not installed
    is a miss of another kind (the library IS installed) and is left as it is."""
    try:
        return library.select(name, scanned)
    except LibraryNotFound as error:
        if "requested_version" not in error.extra:
            error.extra.update(_obtainable(name, scanned))
        error.extra["tool_hint"] = (
            "call zim_libraries to see what is installed; to install one, call zim_available, then ask the user "
            "to run the `install` command it returns"
        )
        error.settle()
        raise


def _find(name: str, scanned: library.Scan) -> Book:
    return _select(name, scanned).book


def _newest_per_family(books: list[Book]) -> list[Book]:
    """One book for each family: its newest version, in its newest edition. Searching every installed version of
    a package would spend the budget on the same documentation five times."""
    families: dict[str, list[Book]] = {}
    for book in sorted(books, key=lambda b: library.date_key(b.date), reverse=True):  # newest first: the order
        families.setdefault(book.family, []).append(book)  # the interleaved ranking has always used
    return [library.newest_version(members) for members in families.values()]


def _installed(scanned: library.Scan) -> dict[str, str]:
    newest: dict[str, str] = {}
    for book in scanned.books:
        newest[book.name] = max(newest.get(book.name, ""), book.date)
    return newest


def _no_snapshot(error: ZimloreError) -> dict[str, Any]:
    """What a model needs when there is no usable catalogue snapshot: it cannot make one (that needs the network
    and the user's say-so), so the next move is to ask. `user_command` is the CLI text for the human."""
    command = error.cli_hint or snapshot.HINT
    return {
        "user_action": f"ask the user to run `{command}` once; you cannot, the server never touches the network",
        "user_command": command,
    }


def _obtainable(name: str, scanned: library.Scan) -> dict[str, Any]:
    try:
        found = snapshot.available(name, 5, _installed(scanned))
    except ZimloreError as error:
        return {
            "snapshot_hint": f"{error.message}; run `{error.cli_hint or snapshot.HINT}` "
            "to learn what could be installed",
            **_no_snapshot(error),
        }
    return {"obtainable": found["available"], "snapshot_age_days": found["snapshot"]["age_days"]}


def _obtainable_for_query(query: str, scanned: library.Scan) -> dict[str, Any]:
    """`obtainable` for a search that found nothing it is sure of. A snapshot is matched against library names and
    titles, so a sentence rarely matches whole: the query as written first, then each content word, at most 5 rows
    in all. No snapshot, an unusable one or no match is an empty dict: a search never fails for want of one."""
    rows: list[dict[str, Any]] = []
    age: int | None = None
    for text in [query, *_query_words(query)]:
        try:
            found = snapshot.available(text, 5, _installed(scanned))
        except ZimloreError:
            return {}
        age = found["snapshot"]["age_days"]
        names = {row["name"] for row in rows}
        rows += [row for row in found["available"] if row["name"] not in names]
        if len(rows) >= 5:
            break
    if not rows:
        return {}
    return {"obtainable": rows[:5], "snapshot_age_days": age}


def available(query: str, limit: int = 8, start: int = 0) -> dict[str, Any]:
    """What the offline catalogue snapshot says could be installed for `query` (no network), with which of it
    is already installed. Without a usable snapshot it raises, naming the installed libraries (so "not installed"
    is still answerable) and what only the user can do."""
    scanned = library.scan()
    start = _bounded("start", start, 0, 2**62)
    try:
        found = snapshot.available(query, start + limit, _installed(scanned))
    except ZimloreError as error:
        if error.cli_hint != snapshot.HINT:  # an empty query is not a missing snapshot
            raise
        names = sorted(_installed(scanned))
        raise ZimloreError(
            f"{error.message}; the libraries installed are: {', '.join(names) or 'none'}",
            snapshot.HINT,
            installed=names,
            tool_hint="no snapshot, so what could be installed is unknown; if the library you want is not among "
            "the installed ones, it is not installed",
            **_no_snapshot(error),
        ) from error
    found["available"] = found["available"][start:]
    if found["matches"] > start + len(found["available"]):
        found["next"] = start + len(found["available"])
    return found


def _book(name: str, scanned: library.Scan | None = None) -> Book:
    return _find(name, scanned or _scan())


class EntryTooLarge(ZimloreError):
    """An entry over the read budget. A subclass so `search` can keep the hit and say so, where `read` fails."""


def max_entry_bytes() -> int:
    name = MAX_ENTRY_ENV
    raw = os.environ.get(name, "").strip()
    if not raw:
        name = LEGACY_MAX_ENTRY_ENV
        raw = os.environ.get(name, "").strip()
    if not raw:
        return DEFAULT_MAX_ENTRY_BYTES
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ZimloreError(f"{name}={raw!r} is not a positive number of bytes", f"unset {name}")
    return value


def resolve_redirect(entry: Any, label: str) -> Any:
    """Follow redirects from `entry` to the entry they end at, at most `MAX_REDIRECTS` hops. A loop (only a
    hand-edited ZIM has one: libzim's writer refuses them) or a target that cannot be read raises `ZimloreError`;
    callers that are listing things skip the entry, callers that were asked for it report the error."""
    hops = 0
    while entry.is_redirect:
        hops += 1
        if hops > MAX_REDIRECTS:
            raise ZimloreError(f"redirect loop at {label!r}")
        try:
            entry = entry.get_redirect_entry()
        except (RuntimeError, KeyError, OSError) as error:
            raise ZimloreError(f"redirect at {label!r} points at an entry that cannot be read ({error})") from error
    return entry


def _entry(book: Book, path: str) -> tuple[Any, str, str | None]:
    """The entry at `path`, following redirects. Returns (entry, final path, redirected-from or None)."""
    archive = library.open_archive(book.path)
    if not path:
        if not archive.has_main_entry:
            raise ZimloreError(
                f"{book.name} has no main page",
                f"primarysource zim outline {book.name}",
                tool_hint=f"call zim_outline with ref={book.name!r} to list its entries",
            )
        entry = archive.main_entry
        first = None
    else:
        if not archive.has_entry_by_path(path):
            raise _missing(book, path)
        entry = archive.get_entry_by_path(path)
        first = path
    try:
        entry = resolve_redirect(entry, path or "(main page)")
    except ZimloreError as error:
        raise ZimloreError(f"{book.name}: {error.message}") from error
    return entry, str(entry.path), first if first and first != entry.path else None


def _missing(book: Book, path: str) -> ZimloreError:
    near = _suggest(book, path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " "), 5)
    return ZimloreError(
        f"{book.name} has no entry {path!r}",
        f"primarysource zim search {book.name} <words> finds entries; "
        f"primarysource zim outline {book.name} lists them",
        tool_hint=f"call zim_search with library={book.name!r} to find the entry, or zim_outline to list entries",
        **({"did_you_mean": [format_ref(book.name, p) for p, _ in near]} if near else {}),
    )


def document(book: Book, path: str) -> tuple[Document, str, str | None]:
    """The converted article at `path` (cached). Returns (document, final path, redirected-from)."""
    entry, final, via = _entry(book, path)
    key = (book.uuid, final)
    if key in _DOCS:
        _DOCS.move_to_end(key)
        cached = _DOCS[key]
        return cached[2], final, via
    item = entry.get_item()
    mimetype = str(item.mimetype).split(";")[0].strip().lower()
    size, budget = int(item.size), max_entry_bytes()
    if size > budget and mimetype in HTML_TYPES + TEXT_TYPES:
        raise EntryTooLarge(
            f"{book.name}§{final} is {size:,} bytes, over the {budget:,}-byte read limit",
            f"to read it anyway, set {MAX_ENTRY_ENV}={size} (or more) and repeat the call",
            tool_hint="read a different entry; this one is over the server's size limit",
            user_action=f"only the user can raise the limit: {MAX_ENTRY_ENV}={size} in the server's environment",
            size=size,
            limit=budget,
        )
    raw = bytes(item.content).decode("utf-8", errors="replace")
    if mimetype in HTML_TYPES:
        doc = convert(raw, final)
    elif mimetype in TEXT_TYPES:
        blocks = [part.strip("\n") for part in re.split(r"\n\s*\n", raw) if part.strip()]
        doc = Document(entry.title or final, blocks)
    else:
        raise ZimloreError(
            f"{book.name}§{final} is {mimetype}, not text",
            "only HTML and plain-text entries can be read; primarysource zim outline lists the readable ones",
            tool_hint="only HTML and plain-text entries can be read; zim_outline lists the readable ones",
            mimetype=mimetype,
            size=int(item.size),
        )
    _DOCS[key] = (entry.title, final, doc)
    while len(_DOCS) > _DOC_CACHE:
        _DOCS.popitem(last=False)
    return doc, final, via


def _title(book: Book, path: str) -> str:
    archive = library.open_archive(book.path)
    return str(archive.get_entry_by_path(path).title) if archive.has_entry_by_path(path) else path


EMBED_HOSTS = ("disqus.com", "disquscdn.com", "accounts.google.com")
"""Third-party hosts whose frames a web-crawl ZIM stores as HTML entries under `host/path`. Measured in
devhints.io_en_all (2026-08): 690 of its 1,037 HTML entries are `disqus.com/...` (an "unable to load Disqus"
notice, or a JSON API reply labelled text/html) and one is `accounts.google.com/o/oauth2/iframe` (no text at all);
the 346 real cheatsheets are all under `devhints.io/`. A host list is the cheap test: judging by converted length
cannot work, because the real page `devhints.io/nocode` is 10 characters and the Disqus notices are 128-144."""


def _is_embed(path: str) -> bool:
    host = path.split("/", 1)[0].lower()
    return any(host == h or host.endswith("." + h) for h in EMBED_HOSTS)


def _is_article(entry: Any) -> bool:
    if _is_embed(str(entry.path)):
        return False
    if entry.is_redirect:
        return True
    return str(entry.get_item().mimetype).split(";")[0].strip().lower() in HTML_TYPES + TEXT_TYPES


# --- citation ------------------------------------------------------------------------------------------------


def citation(book: Book, path: str, anchor: str = "", para: int | str | None = None) -> str:
    """Built from the ZIM's own metadata, never typed by hand: library, edition date, entry path."""
    where = path + (f"#{anchor}" if anchor else "") + (f" ¶{para}" if para else "")
    text = f"{book.title} [{book.name}], ZIM edition {book.date or 'undated'}, entry {where or '(main page)'}"
    if book.source:
        text += f"; source {book.source}"
    return text


def licence_note(book: Book) -> str:
    if book.license:
        return book.license
    return "not stated in the ZIM; it is the upstream project's licence, so check the project before reusing text"


# --- libraries -----------------------------------------------------------------------------------------------


def _book_row(
    book: Book, scanned: library.Scan | None = None, verbose: bool = False, family: bool = False
) -> dict[str, Any]:
    """One library as a row. The default row is what choosing a library needs (about 40 tokens); `verbose` adds
    what describing one needs (description, creator, tags, licence, the full provenance record)."""
    row: dict[str, Any] = {
        "name": book.name,
        "title": book.title,
        "language": book.language,
        "articles": book.articles,
        "size_bytes": book.size,
        "search": "full-text" if book.has_fulltext else ("titles only" if book.has_titles else "none"),
        "freshness": _fresh(book),
    }
    provenance = manage.provenance_summary(book.path)
    if verbose:
        row.update(
            description=book.description,
            creator=book.creator,
            tags=list(book.tags),
            license=book.license or None,
            provenance=provenance,
        )
    elif provenance["state"] != "recorded":
        row["provenance"] = provenance["state"]  # only the exception is worth a token: `unrecorded` or `unreadable`
    if scanned is not None:
        others = [b.date for b in library.editions(book, scanned.books) if b.path != book.path]
        if others:
            row["other_editions"] = others
        if book.version:
            row["version"] = book.version  # a row of a family is its newest version
        versions = library.versions_of(book, scanned.books)
        if family and len(versions) > 1:
            row["family"] = book.family
            row["versions"] = versions
    return row


def _fresh(book: Book) -> dict[str, Any]:
    fresh = book.freshness()
    fresh.pop("stale_after_days", None)  # a constant, stated once in the server instructions
    return fresh


def libraries(
    query: str = "", limit: int = 50, verbose: bool = False, all_versions: bool = False, start: int = 0
) -> dict[str, Any]:
    """Installed libraries (or those matching `query`, best first), newest edition of each, at most `limit`. The
    versions of one package are ONE row (its newest version, `versions` listing them all) unless `all_versions`
    asks for a row per ZIM `Name`.

    A library with 243 DevDocs ZIMs installed would otherwise cost about 35,000 tokens in one call."""
    clamped: dict[str, int] = {}
    limit = _bounded("limit", limit, 1, 1000, clamped)
    start = _bounded("start", start, 0, 2**62)
    scanned = _scan()
    home = str(library.zim_dirs()[0]) if library.zim_dirs() else ""
    if query:
        ranked = library.rank(query, scanned.books, library.user_aliases())
        rows = []
        for candidate in ranked[start : start + limit]:
            row = _book_row(candidate.book, scanned, verbose, family=True)
            row["match"] = candidate.why
            row["score"] = round(candidate.score, 1)
            rows.append(row)
        result: dict[str, Any] = {"query": query, "total": len(ranked), "libraries": rows}
    else:
        if all_versions:
            newest: dict[str, Book] = {}
            for book in sorted(scanned.books, key=lambda b: library.date_key(b.date), reverse=True):
                newest.setdefault(book.name, book)
            ordered = sorted(newest.values(), key=lambda b: b.name)
        else:
            ordered = sorted(_newest_per_family(scanned.books), key=lambda b: b.family)
        rows = [_book_row(b, scanned, verbose, family=not all_versions) for b in ordered[start : start + limit]]
        result = {"total": len(ordered), "libraries": rows}
    result["truncated"] = result["total"] > start + len(rows)
    if result["truncated"]:
        result["next"] = start + len(rows)
    result["directory"] = home
    if scanned.problems:
        result["problems"] = scanned.problems
    if clamped:
        result["clamped"] = clamped
    return result


def resolve(name: str) -> dict[str, Any]:
    """The one library a name means, with its edition. Raises with the candidates rather than guessing."""
    scanned = _scan()
    chosen = _select(name, scanned)
    book = chosen.book
    row = _book_row(book, scanned, verbose=True)
    row["match"] = chosen.why
    if book.version:
        row["version"] = {
            "upstream": book.version,
            "selected": chosen.kind,
            "pinned_by": "purl tag" if book.package and book.package.version else "version in the Name",
            "edition": book.date or None,
        }
        if chosen.requested:
            row["version"]["requested"] = chosen.requested
        if chosen.other_versions:
            row["other_versions"] = chosen.other_versions
    else:
        row["version"] = {
            "pinned_by": "ZIM edition date",
            "edition": book.date or None,
            "note": "a ZIM records its date, not the upstream release number",
        }
    return row


# --- search --------------------------------------------------------------------------------------------------


@dataclass
class Hit:
    book: Book
    path: str
    title: str
    match: str  # "full-text" (every word) | "some terms" (partial) | "title"
    lang: str = ""  # the language the page's content declares, when the HTML says (MediaWiki does)
    exact: bool = False  # a title that is the query: the one `title` match that is not a guess


_CONTENT_LANG = re.compile(r"""<div\b[^>]*\bid=["']mw-content-text["'][^>]*?\blang=["']([A-Za-z0-9-]+)["']""")


def _content_lang(entry: Any) -> str:
    """The language a page's body declares: MediaWiki writes `lang` on `<div id="mw-content-text">`, and that is
    the one reliable marker in ArchWiki (measured, 2026-10 ZIM: 3,674 of 3,779 pages with a `_(Español)`-style path
    suffix declare a language other than `en`; 2,356 of 2,395 pages without a suffix declare `en`). The `<html>`
    element's own `lang` is `en` on every page, and the path suffix alone is not a language marker (`Foo_(2022)`)."""
    item = entry.get_item()
    if str(item.mimetype).split(";")[0].strip().lower() not in HTML_TYPES:
        return ""
    head = bytes(memoryview(item.content)[:16384])  # not bytes(item.content)[:n]: that copies a whole big entry
    match = _CONTENT_LANG.search(head.decode("utf-8", errors="replace"))
    return match.group(1).lower() if match else ""


def _same_language(lang: str, wanted: str) -> bool:
    """`en` matches `en-GB`; a three-letter ISO 639-3 code (the ZIM's `Language` metadata, `eng`) matches the
    two-letter code it extends by prefix, which holds for eng/en, fra/fr, deu/de and is only a convention."""
    lang, wanted = lang.split("-")[0], wanted.lower().split("-")[0]
    return (
        lang == wanted
        or (len(wanted) == 3 and wanted.startswith(lang))
        or (len(lang) == 3 and lang.startswith(wanted))
    )


def _suggest(book: Book, query: str, limit: int) -> list[tuple[str, str]]:
    if not book.has_titles or not query.strip():
        return []
    suggestion = _libzim.load("suggestion")
    archive = library.open_archive(book.path)
    try:
        result = suggestion.SuggestionSearcher(archive).suggest(query)
        paths = list(result.get_results(0, limit))
    except RuntimeError:
        return []
    return [(str(p), _title(book, str(p))) for p in paths]


TITLE_BOOST = 3.0
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "this",
        "to",
        "use",
        "using",
        "what",
        "when",
        "where",
        "which",
        "with",
        "you",
        "your",
        "can",
    ]
)


def _run_query(book: Book, text: str, want: int) -> list[str]:
    search = _libzim.load("search")
    archive = library.open_archive(book.path)
    try:
        found = search.Searcher(archive).search(search.Query().set_query(text))
        return [str(r.path) if hasattr(r, "path") else str(r) for r in found.get_results(0, want)]
    except RuntimeError:
        return []


def _fulltext(book: Book, query: str, want: int) -> tuple[list[str], list[str]]:
    """Full-text results as (every-term matches, some-term matches).

    libzim's query parser requires every term, so a question whose words do not all occur in one page finds
    nothing ("automated" occurs in none of Flask's pages, so "write automated tests for a flask application"
    matched nothing at all). When strict search leaves fewer than `want`, each content word is searched on its
    own and the lists are fused: a page earns, for each word it matches, a weight of ln(pages / pages matching
    the word) divided by 60 plus its rank in that word's list. A word found on every page therefore weighs
    nothing, and a rare one decides. Those extra results are marked as partial matches.
    """
    cleaned = re.sub(r'[^\w\s"+-]', " ", query)
    strict = _run_query(book, query, want) or _run_query(book, cleaned, want)
    if len(strict) >= want:
        return strict, []
    terms = list(
        dict.fromkeys(w for w in re.findall(r"[\w+-]+", cleaned.lower()) if w not in STOPWORDS and len(w) > 1)
    )
    if len(terms) < 2:
        return strict, []
    search = _libzim.load("search")
    archive = library.open_archive(book.path)
    total = max(book.articles, 2)
    scores: dict[str, float] = {}
    for term in terms:
        try:
            found = search.Searcher(archive).search(search.Query().set_query(term))
            matches = int(found.get_estimated_matches())
            ranked = [str(r.path) if hasattr(r, "path") else str(r) for r in found.get_results(0, 50)]
        except RuntimeError:
            continue
        if not matches:
            continue
        weight = math.log(total / matches) if matches < total else 0.0
        for rank, path in enumerate(ranked):
            scores[path] = scores.get(path, 0.0) + weight / (60 + rank)
        for rank, (path, _) in enumerate(_suggest(book, term, 20)):  # a word in a page's title is a strong signal
            scores[path] = scores.get(path, 0.0) + TITLE_BOOST * max(weight, 0.5) / (60 + rank)
    loose = [p for p, _ in sorted(scores.items(), key=lambda kv: -kv[1]) if p not in strict and scores[p] > 0]
    return strict, loose[: want * 2]


def _book_hits(book: Book, query: str, want: int, language: str = "") -> tuple[list[Hit], str]:
    """Title matches that are exact come first, then full-text relevance, then the remaining title matches.
    Entries that are not articles (stylesheets, scripts) and redirects to the same article are folded.

    `language` decides what a page's declared content language does. Empty: pages in another language than the
    library's are kept but ranked after the pages in its own language (ArchWiki holds a translation of most pages
    and they crowded the base page out of the top 5). `any`: no preference. A code (`ru`): only pages in it."""
    archive = library.open_archive(book.path)
    titled = _suggest(book, query, want)
    mode = "full-text" if book.has_fulltext else "titles only"
    strict, loose = _fulltext(book, query, want * 2) if book.has_fulltext else ([], [])
    wanted = " ".join(query.lower().split())
    exact = [p for p, t in titled if " ".join(t.lower().split()) == wanted]
    ordered: list[tuple[str, str]] = (
        [(p, "exact") for p in exact]
        + [(p, "full-text") for p in strict]
        + [(p, "title") for p, _ in titled if p not in exact]
        + [(p, "some terms") for p in loose]
    )
    hits: list[Hit] = []
    foreign: list[Hit] = []
    seen: set[str] = set()
    folding = language not in {"any"}
    for path, how in ordered:
        if not archive.has_entry_by_path(path):
            continue
        entry = archive.get_entry_by_path(path)
        if not _is_article(entry):
            continue
        try:
            entry = resolve_redirect(entry, path)
        except ZimloreError:
            continue  # a redirect loop or dangling target is one bad hit, not a failed search
        if entry.path in seen:
            continue
        seen.add(entry.path)
        lang = _content_lang(entry) if folding else ""
        hit = Hit(book, entry.path, str(entry.title), "title" if how == "exact" else how, lang, how == "exact")
        if language and folding:
            if lang and _same_language(lang, language):
                hits.append(hit)
        elif lang and not _same_language(lang, book.language or "eng"):
            foreign.append(hit)
        else:
            hits.append(hit)
        if len(hits) >= want:
            break
    return (hits + foreign)[:want], mode


LARGE_ARTICLE_BLOCKS = 60
RARE_WORD_BLOCKS = 3  # a single query word is distinctive on a page if at most this many blocks contain it
"""An article with more blocks than this gets section-level hits. 60 blocks is about one default `read` page
(2000 tokens is roughly 50-100 blocks): past it, an agent that lands on the page pays a whole page to find the
part it wanted, and an agent testing the server did (Go `httptest`, 168 blocks, ~1.1k tokens to reach the example,
when the threshold was 200). Measured 2026-11-07 on a 60-400 page random sample per library, the share of articles
over 60 blocks: PHP 3.5%, Flask 22%, Rust 29%, Python 59%, Go 63%, Node 92% (over 200 it was 0.3%, 7%, 11%, 21%,
27% and 65%). The rarity and two-word rules in `_best_section` still decide whether a hit gets one, so a short page
and a stray word stay article-level."""

_CHROME_LEAD = re.compile(
    r"^(pages that refer to this page|colophon\b|this page is part of|table of contents$"
    r"|this document has been placed in the public domain)",
    re.IGNORECASE,
)
_BARE_URL = re.compile(r"^[\W_]*(?:https?://|www\.)\S+[\W_]*$", re.IGNORECASE)
_FIELD_LABEL = re.compile(r"^\*\*[\w -]+:\*\*$")


def _header_end(blocks: list[str]) -> int:
    """Number of leading blocks that are a metadata header: the PEPs open with a field list (`**Author:**`, a
    value block, `**Discussions-To:**`, `[Discourse thread](...)`, ...) closed by a rule. Measured on
    peps.python_en_all: 735 of 765 PEP pages carry it, and 'Discourse thread' was the search excerpt of PEP 649,
    PEP 669 and PEP 728. Requires at least two labels before a rule within the first 60 blocks."""
    labels = 0
    for index, block in enumerate(blocks[:60]):
        if _FIELD_LABEL.match(block):
            labels += 1
        elif block.strip() == "---":
            return index + 1 if labels >= 2 else 0
    return 0


def _is_chrome(block: str) -> bool:
    """Page furniture that is never the answer: a rule, a back-reference list, or a block that is only a URL."""
    flat = " ".join(to_plain(block).split())
    if not flat or set(flat) <= set("-*_= "):
        return True
    return bool(_CHROME_LEAD.match(flat) or _BARE_URL.match(flat))


def _query_words(query: str) -> list[str]:
    """The distinct content words of a query: longer than two characters and not a stopword (`how`, `use`, `the`
    decide nothing about which block answers). One definition for excerpts and section choice."""
    return list(dict.fromkeys(w for w in re.findall(r"\w+", query.lower()) if len(w) > 2 and w not in STOPWORDS))


def _word_patterns(words: list[str]) -> list[re.Pattern[str]]:
    """A word matches from a word boundary (`rotor` finds `rotors`, `cat` does not find `concatenate`)."""
    return [re.compile(r"\b" + re.escape(w)) for w in words]


def _excerpt(blocks: list[str], query: str, width: int = 240) -> str:
    """The best-matching block of `blocks`, flattened and cut to `width`. Prose is preferred; code, tables and
    preformatted text are used when no prose block mentions a query word (man pages are one fence per section).
    Chrome blocks (see `_is_chrome`) and headings are never chosen unless nothing else is left."""
    words = _query_words(query)
    patterns = _word_patterns(words)
    lead = _header_end(blocks)
    body = [b for b in blocks[lead:] if not b.startswith("#") and not _is_chrome(b) and b != "×"] or blocks
    prose = [b for b in body if not b.startswith(("```", "|"))]
    pick = ""
    for pool in (prose, body):
        scored = [(sum(bool(p.search(b.lower())) for p in patterns), -i, b) for i, b in enumerate(pool)]
        best = max(scored, default=(0, 0, ""))
        if best[0]:
            pick = best[2]
            break
    choice = pick or (prose[0] if prose else (body[0] if body else ""))
    flat = " ".join(to_plain(choice).split())
    if len(flat) <= width:
        return flat
    lowered = flat.lower()
    at = min((m.start() for m in (p.search(lowered) for p in patterns) if m), default=0)
    start = max(0, at - width // 3)
    return ("…" if start else "") + flat[start : start + width].strip() + "…"


def _best_section(doc: Document, query: str) -> tuple[Heading, int, int] | None:
    """The addressable heading or definition of a large article whose own text covers most of the query's words.

    Score = distinct query words found in the section's blocks (sub-sections included) plus 1 for each found in
    the heading text itself; ties go to the shorter section, so a child beats the parent that contains it. A
    section with no query word is never chosen: the caller then keeps the article-level hit as it was.

    A parent always covers at least what its children do, so a query whose words sit in different parts of the
    page is won by the section that holds them all, often the whole article. A winner that spans more than half of
    the article is no better than the article: `None`, and the caller keeps the article-level hit."""
    words = _query_words(query)
    if not words:
        return None
    patterns = _word_patterns(words)
    masks = []
    for block in doc.blocks:
        low = block.lower()
        masks.append(sum(1 << n for n, p in enumerate(patterns) if p.search(low)))
    best: tuple[tuple[float, int], Heading, int, int] | None = None
    for position, head in enumerate(doc.headings):
        if not head.anchor:
            continue
        lo, hi = doc.span(position)
        found = 0
        for mask in masks[lo:hi]:
            found |= mask
        if not found:
            continue
        title = head.text.lower()
        key = (bin(found).count("1") + sum(bool(p.search(title)) for p in patterns), -(hi - lo))
        if best is None or key > best[0]:
            best = (key, head, lo, hi)
    if best is None or (best[3] - best[2]) * 2 > len(doc.blocks):
        return None
    if best[0][0] < 2:
        # Weak evidence: one query word found, none in the heading. For a query of several words that is a stray
        # match in an unrelated section (found live: 'directory' in 'create a directory with missing parents').
        if len(words) > 1:
            return None
        # For a one-word query it is an answer only if the word is distinctive on this page. 'x509' on the x509
        # reference page is in dozens of blocks and attached 'Custom PKCS7 Test Vectors' by luck; 'quibbleframe',
        # in one definition's body, is the answer.
        if sum(1 for mask in masks if mask & 1) > RARE_WORD_BLOCKS:
            return None
    return best[1:]


def search(
    query: str, library_name: str = "", limit: int = 8, max_tokens: int = 1500, language: str = "", start: int = 0
) -> dict[str, Any]:
    """Search one library, or all of them when `library_name` is empty. Hits are refs ready for `read`.

    `language`: empty ranks pages written in another language than the library's after those in its own (a hit
    then carries `language`), `any` keeps the engine's order, a code such as `ru` returns only pages declaring it.

    Across libraries the order is rank-by-rank interleaving: libzim does not expose a relevance score, so scores
    from different ZIMs cannot be compared and pretending otherwise would be invented precision.
    """
    if not query.strip():
        raise ZimloreError(
            "empty query",
            "give a few words, e.g. primarysource zim search flask 'application factory'",
            tool_hint="give a few words, e.g. query='application factory'",
        )
    clamped: dict[str, int] = {}
    limit = _bounded("limit", limit, 1, MAX_LIMIT, clamped)
    start = _bounded("start", start, 0, 2**62)
    max_tokens = _bounded("max_tokens", max_tokens, 1, MAX_TOKENS_CAP, clamped)
    scanned = _scan()
    books = [_find(library_name, scanned)] if library_name else _newest_per_family(scanned.books)
    # The engine has no offset: a later page asks it for everything up to its own end, and the earlier hits are
    # skipped. How many title and full-text candidates the engine is asked for decides the order past the first few
    # (`_book_hits` fills from its tiers), so every page asks for at least SEARCH_DEPTH: pages are then cuts of one
    # list, which is what lets `next: start=<n>` lose nothing. Reading a page's hits, the costly step, is unchanged.
    per_book = max(SEARCH_DEPTH, start + (limit if len(books) == 1 else max(2, min(limit, 5))))
    lists: list[list[Hit]] = []
    modes: dict[str, str] = {}
    for book in books:
        hits, mode = _book_hits(book, query, per_book, language.strip().lower())
        modes[book.name] = mode
        lists.append(hits)
    ordered: list[Hit] = []
    for rank in range(per_book):
        for hits in lists:
            if rank < len(hits):
                ordered.append(hits[rank])
    kept: list[dict[str, Any]] = []
    used, truncated, sure = 0, False, False
    for hit in ordered[start : start + limit]:
        too_large = ""
        try:
            doc, _, _ = document(hit.book, hit.path)
        except EntryTooLarge as error:
            doc, too_large = Document("", []), error.message
        picked = _best_section(doc, query) if len(doc.blocks) > LARGE_ARTICLE_BLOCKS else None
        row: dict[str, Any] = {
            "ref": format_ref(hit.book.name, hit.path),
            "title": hit.title,
            "excerpt": _excerpt(doc.blocks[picked[1] : picked[2]] if picked else doc.blocks, query),
            "match": hit.match,
        }
        if too_large:
            row["note"] = f"no excerpt: {too_large}"
        else:
            row["blocks"] = len(doc.blocks)  # what reading the whole page would cost, before deciding to
        if hit.lang and not _same_language(hit.lang, hit.book.language or "eng"):
            row["language"] = hit.lang
        cost = tokens(row["excerpt"] + hit.title) + 30
        if picked:
            head = picked[0]
            row["section"] = {
                "anchor": head.anchor,
                "heading": head.text,
                "ref": format_ref(hit.book.name, hit.path, head.anchor),
                "blocks": picked[2] - picked[1],
            }
            cost += tokens(head.text) + 30
        if kept and used + cost > max_tokens:
            truncated = True
            break
        used += cost
        kept.append(row)
        sure = sure or hit.match == "full-text" or hit.exact
    result: dict[str, Any] = {
        "query": query,
        "libraries_searched": [b.name for b in books],
        "editions": {b.name: b.date or None for b in books},  # once, not per hit; `zim_cite` builds the citation
        "hits": kept,
        "truncated": truncated or len(ordered) > start + limit,
    }
    if result["truncated"]:
        result["next"] = start + len(kept)
    title_only = [name for name, mode in modes.items() if mode == "titles only"]
    if title_only:
        result["title_only"] = f"no full-text index in: {', '.join(title_only)}; only titles were searched there"
    if len(books) > 1:
        result["ranking"] = "interleaved rank by rank across libraries; ZIM search exposes no comparable score"
    if clamped:
        result["clamped"] = clamped
    if not kept:
        result["note"] = "no entry matched; this is the search, not proof the topic is absent from the library"
    if not sure:
        # Every hit is partial ('some terms') or a title guess: the engine found pages that share a word, not a page
        # that answers. Found live: an uncovered topic returned 8 plausible hits and nothing said to stop.
        result["confidence"] = "low"
        if kept:
            result["note"] = (
                "no hit matched all your words; the topic may not be covered - check zim_available "
                "(`obtainable`, when present, is what the offline catalogue snapshot lists)"
            )
        result.update(_obtainable_for_query(query, scanned))
    return result


# --- reading -------------------------------------------------------------------------------------------------


def _context(ref: str, library_name: str) -> tuple[Book, Ref]:
    parsed = parse_ref(ref, library_name)
    return _book(parsed.book), parsed


def _no_section(book: Book, final: str, doc: Document, anchor: str) -> ZimloreError:
    """A bad anchor. The three closest real anchors by spelling are named as refs ready to read; the first 25 in
    document order (the old answer) said nothing about a typo like `os.scandirr`, whose fix is one letter."""
    lowered = {h.anchor.lower(): h.anchor for h in doc.headings if h.anchor}
    close = [lowered[m] for m in difflib.get_close_matches(anchor.lower(), list(lowered), n=3, cutoff=0.6)]
    return ZimloreError(
        f"{book.name}§{final} has no section #{anchor}",
        f"primarysource zim outline {book.name}§{final} lists the anchors",
        tool_hint=f"call zim_outline with ref={book.name}§{final} to list its anchors",
        **({"did_you_mean": [format_ref(book.name, final, a) for a in close]} if close else {}),
    )


def _scope(book: Book, final: str, doc: Document, parsed: Ref, onward: bool = False) -> tuple[int, int, str]:
    """The blocks a ref names, as (lo, hi, scope) over `doc.blocks`. `¶n` counts inside the scope it is written
    after: the nth block of the section when there is an `#anchor`, of the article otherwise. Counting the page's
    nth block under a section's name would cite a section for text it does not contain.

    `¶n` names that one block (what `cite` checks) unless `onward`: a read of `ref¶n` starts at block n and
    continues to the end of the scope, which is how a cut read's `next:` ref pages (PLAN.md §5.11)."""
    lo, hi, scope = 0, len(doc.blocks), "article"
    if parsed.anchor:
        span = doc.section(parsed.anchor)
        if span is None:
            raise _no_section(book, final, doc, parsed.anchor)
        (lo, hi), scope = span, "section"
    if parsed.para is not None:
        if parsed.para > hi - lo:
            where = f"#{parsed.anchor}" if parsed.anchor else ""
            raise ZimloreError(
                f"{book.name}§{final}{where} has {hi - lo} blocks; no ¶{parsed.para}",
                "¶n counts the blocks of the section when the ref has an #anchor, of the article otherwise",
                blocks=hi - lo,
            )
        lo = lo + parsed.para - 1
        if not onward:
            hi, scope = lo + 1, "block"
    return lo, hi, scope


def _label(first: int, last: int, para: int | None) -> int | str | None:
    """What a read's citation names: nothing for a whole scope read from its first block, `¶n` for one block, `¶a-b`
    for a page that starts inside the scope or holds several blocks of a `¶` read (blocks 1-based in the scope)."""
    if para is None and first <= 1:
        return None
    return first if first == last else f"{first}-{last}"


def read(
    ref: str,
    library_name: str = "",
    max_tokens: int = 2000,
    format: str = "markdown",  # noqa: A002 - the tool parameter is called format
) -> dict[str, Any]:
    """One article, one section (`#anchor`), cut to a token budget, from block `¶n` on when the ref has one. `next`
    is a ref (the same scope with `¶` at the first block not shown) when the budget, not the scope, ended the page."""
    if format not in {"markdown", "text"}:
        raise ZimloreError(f"unknown format {format!r}", "format is 'markdown' or 'text'")
    clamped: dict[str, int] = {}
    max_tokens = _bounded("max_tokens", max_tokens, 1, MAX_TOKENS_CAP, clamped)
    book, parsed = _context(ref, library_name)
    doc, final, via = document(book, parsed.path)
    whole = replace(parsed, para=None)
    scope_lo, hi, scope = _scope(book, final, doc, whole)
    lo, _, _ = _scope(book, final, doc, parsed, onward=True)
    first = lo
    # The core pager: whole blocks until the next would pass the budget, the first always taken (so a cursor
    # following `next` terminates), and `oversize` when that one alone is over.
    page = budget.page(doc.blocks[lo:hi], 1, max_tokens)
    chunk = list(page.units)
    index = lo + len(chunk)
    marks = [doc.tight[i] if i < len(doc.tight) else False for i in range(lo, index)]
    body = join_blocks(chunk, marks)
    if format == "text":
        body = to_plain(body)
    ref_out = format_ref(book.name, final, parsed.anchor)
    label = _label(first - scope_lo + 1, index - scope_lo, parsed.para)
    result: dict[str, Any] = {
        "ref": ref_out,
        "cite": citation(book, final, parsed.anchor, label),
        "title": _title(book, final),
        "scope": scope,
        "freshness": _fresh(book),
        "format": format,
        "blocks": {"from": first - scope_lo + 1, "to": index - scope_lo, "of": hi - scope_lo},
        "content": body,
        "next": None,
    }
    if doc.title and doc.title != result["title"]:
        result["page_title"] = doc.title  # only when it differs: DevDocs entry titles are not always page names
    if via:
        result["redirected_from"] = via
    if index < hi:
        result["next"] = format_ref(book.name, final, parsed.anchor, index - scope_lo + 1)
        # What is left, in the unit a model budgets in: block counts alone made "17 of 76" mean nothing.
        result["remaining_blocks"] = hi - index
        result["remaining_tokens"] = sum(tokens(b) for b in doc.blocks[index:hi])
    if page.oversize:
        result["oversize"] = "one block alone exceeds the budget and is returned whole so paging makes progress"
    if doc.truncated:
        result["converted_truncated"] = (
            f"the page is larger than the converter's {MAX_OUTPUT_CHARS:,}-character ceiling; its end is not shown"
        )
    if clamped:
        result["clamped"] = clamped
    if doc.dropped_images:
        result["images"] = f"{doc.dropped_images} image(s) are not text and appear as [image] placeholders"
    return result


def _within(rows: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], bool]:
    """The leading rows whose estimated cost fits `budget` tokens (always at least one), and whether rows were cut."""
    used = 0
    kept: list[dict[str, Any]] = []
    for row in rows:
        cost = tokens(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        if kept and used + cost > budget:
            return kept, True
        used += cost
        kept.append(row)
    return kept, False


def outline(
    ref: str, library_name: str = "", start: int = 0, limit: int = 100, prefix: str = "", max_tokens: int = 1500
) -> dict[str, Any]:
    """Headings (with anchors) of one article, or a page of a library's articles when `ref` is a library alone."""
    clamped: dict[str, int] = {}
    start = _bounded("start", start, 0, 2**62)
    limit = _bounded("limit", limit, 1, 1000, clamped)
    max_tokens = _bounded("max_tokens", max_tokens, 1, MAX_TOKENS_CAP, clamped)
    book, parsed = _context(ref, library_name)
    if parsed.path:
        doc, final, _ = document(book, parsed.path)
        rows = []
        for h in doc.headings:
            # The page ref is stated once; a row's own ref is that plus `#anchor` (the library and path repeated on
            # every row cost about 60 characters each and told an agent nothing).
            row: dict[str, Any] = {"text": h.text}
            if h.kind == "heading":
                row["level"] = h.level
            else:
                row["kind"] = "definition"
            if h.anchor:
                row["anchor"] = h.anchor
            rows.append(row)
        if start > len(rows):
            raise ZimloreError(f"{book.name}§{final} has {len(rows)} outline rows; start={start} is past the end")
        page, cut = _within(rows[start : start + limit], max_tokens)
        out: dict[str, Any] = {
            "ref": format_ref(book.name, final),
            "title": doc.title,
            "total": len(rows),
            "outline": page,
        }
        if start + len(page) < len(rows):
            out["next"] = start + len(page)
        out["truncated"] = cut or "next" in out  # `next` present means rows are missing, whoever ended the page
        if clamped:
            out["clamped"] = clamped
        return out
    archive = library.open_archive(book.path)
    total = int(archive.entry_count)
    if start > total:
        raise ZimloreError(f"{book.name} has {total} entries; start={start} is past the end")
    first = start
    if prefix and start == 0:
        first = bisect_left(range(total), prefix, key=lambda i: str(archive.get_entry_by_id(i).path))
    entries: list[dict[str, Any]] = []
    positions: list[int] = []  # the entry id to resume from if the listing is cut after entries[n]
    index = first
    scanned_ids = 0
    while index < total and len(entries) < limit and scanned_ids < 20000:
        entry = archive.get_entry_by_id(index)
        index += 1
        scanned_ids += 1
        if prefix and not str(entry.path).startswith(prefix):
            index = total
            break
        if entry.is_redirect or not _is_article(entry):
            continue
        entries.append({"ref": format_ref(book.name, str(entry.path)), "title": str(entry.title)})
        positions.append(index)
    kept, cut = _within(entries, max_tokens)
    resume = positions[len(kept) - 1] if cut else index
    result: dict[str, Any] = {"library": book.name, "entries": kept, "freshness": _fresh(book)}
    if clamped:
        result["clamped"] = clamped
    if cut or index < total:
        result["next"] = resume
    result["truncated"] = cut or "next" in result
    return result


def links(
    ref: str, library_name: str = "", limit: int = 100, max_tokens: int = 1500, start: int = 0
) -> dict[str, Any]:
    """Links out of an article, internal ones resolved to refs, each marked with whether the target exists in
    this ZIM. An internal link whose target is absent is reported, not dropped: it tells the reader the
    article points outside what was archived."""
    clamped: dict[str, int] = {}
    limit = _bounded("limit", limit, 1, 1000, clamped)
    start = _bounded("start", start, 0, 2**62)
    max_tokens = _bounded("max_tokens", max_tokens, 1, MAX_TOKENS_CAP, clamped)
    book, parsed = _context(ref, library_name)
    doc, final, _ = document(book, parsed.path)
    archive = library.open_archive(book.path)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    used, truncated = 0, False
    distinct = []
    for link in doc.links:
        key = (link.path or link.href, link.anchor, link.text)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(link)
    if start > len(distinct):
        raise ZimloreError(f"{book.name}§{final} has {len(distinct)} links; start={start} is past the end")
    for link in distinct[start:]:
        if link.path is None:
            row: dict[str, Any] = {"text": link.text, "url": link.href, "external": True}
        else:
            row = {
                "text": link.text,
                "ref": format_ref(book.name, link.path, link.anchor),
                "external": False,
                "in_zim": bool(archive.has_entry_by_path(link.path)),
            }
        cost = tokens(str(row)) + 4
        if len(rows) >= limit or (rows and used + cost > max_tokens):
            truncated = True
            break
        used += cost
        rows.append(row)
    result: dict[str, Any] = {
        "ref": format_ref(book.name, final),
        "links": rows,
        "total": len(distinct),
        "truncated": truncated,
    }
    if truncated:
        result["next"] = start + len(rows)
    if clamped:
        result["clamped"] = clamped
    return result


JOINER = "\n"


def cite(ref: str, library_name: str = "") -> dict[str, Any]:
    book, parsed = _context(ref, library_name)
    entry, final, _ = _entry(book, parsed.path)
    span = ""
    if parsed.anchor or parsed.para is not None:
        doc, _, _ = document(book, final)
        lo, hi, _ = _scope(book, final, doc, parsed)  # the same check `read` makes: a cite must name something real
        span = span_hash(JOINER.join(doc.blocks[lo:hi]))
    return {
        **({"span": span} if span else {}),
        "ref": format_ref(book.name, final, parsed.anchor, parsed.para),
        "cite": citation(book, final, parsed.anchor, parsed.para),
        "title": str(entry.title),
        "edition": book.date or None,
        "freshness": _fresh(book),
        "license": licence_note(book),
        "provenance": manage.provenance_summary(book.path),
        "creator": book.creator or None,
        "uuid": book.uuid,
    }


def forget() -> None:
    """Drop the converted-article cache (used by tests that rebuild a ZIM at the same path)."""
    _DOCS.clear()
