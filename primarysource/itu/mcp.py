# mypy: disable-error-code="untyped-decorator"
# primarysource's mypy config does not follow the MCP SDK's types, so its decorators read as untyped here; in
# itulib's own repository (which followed them) this module was clean under --strict.
"""The MCP surface: eleven `itu_*` tools on the core contract (PLAN.md §5.9-§5.11).

- **Text results.** Every tool returns `render()` text: the answer, then the fixed footer (`cite:`, `unit:`,
  `span:`, `next:`, `relaxed:`, `warning:`). Tools are registered by `scaffold.add_tools`, so none is sent as
  structured content as well.
- **Errors are `isError` results.** A missing corpus, a missing or stale index, an unknown edition or a clause that
  is not there raises `LibError(message, hint, action)`: `hint` names the tool to call next, `action` the command a
  human must run (`primarysource itu sync X.690#2021-02`). A missing corpus is never an empty list:
  `sync_roadmap.graphql()` once swallowed a scope failure into `""`, which its caller rendered as "the board has
  no issues", and a tool that answers "no clauses match" when the corpus is not installed is the same bug.
  **An empty result is not an error**: a search that matches nothing says so in text.
- **`next:` is what to pass back.** A read's is a ref ending `¶n-` (the clause from sentence n on), which
  `itu_read` accepts as its `ref`; a list's (search, outline, browse, grep, catalog) is `start=<n>`, 0-based.

The SDK is imported inside `build()`: `mcp` 2.x renamed `FastMCP` to `MCPServer`, and importing lazily keeps the
collection usable without the `[mcp]` extra.
"""

from __future__ import annotations

import sys
from typing import Any

from primarysource.errors import LibError
from primarysource.model import span_hash
from primarysource.render import next_start, render
from primarysource.scaffold import add_tools
from primarysource.standing import join as join_warning

from . import __version__, corpus, index, sources, text
from .errata import errata_text

INSTRUCTIONS = (
    "ITU-T recommendations (the ASN.1 family X.680-X.697) as clause-precise search and citation. The corpus is "
    "fetched by the user and never shipped with this package. Refs look like X.690§11.6 or X.690§11.6¶2, where "
    "¶n is the nth sentence of the extracted clause; X.690#2008-11§8.1 names an edition. Results are text with "
    "footer lines: cite the `cite:` line (e.g. Rec. ITU-T X.690 (02/2021) §11.6). `next:` is exactly what to pass "
    "back: a ref for itu_read, or start=<n> for the same list tool. No hits means no clause matched; `relaxed:` "
    "means only some search terms matched; `warning:` means the clause number is ambiguous in the extracted text, "
    "so check the PDF before relying on it. A missing corpus or index is an error whose `action:` line is the "
    "command a human must run."
)

READ_ONLY_HINTS = {
    "read_only_hint": True,
    "idempotent_hint": True,
    "destructive_hint": False,
    "open_world_hint": False,
}
REF_SHAPES = "refs look like X.690§11.6, X.690§11.6¶2 or X.690#2008-11§8.1"


# --- shared --------------------------------------------------------------------------------------------------


def _edition(key: str) -> sources.Edition:
    try:
        return sources.resolve(key)
    except KeyError:
        raise LibError(f"unknown edition {key!r}", "itu_info lists the registered editions") from None


def _doc(item: sources.Edition) -> str:
    """The prefix of a ref that names this edition: the bare recommendation when that resolves to it, else its key."""
    try:
        return item.rec if sources.resolve(item.rec) is item else item.key
    except KeyError:
        return item.key


def _target(ref: str, edition: str) -> tuple[sources.Edition, text.Target]:
    try:
        target = text.parse_target(ref)
    except ValueError as error:
        raise LibError(str(error), REF_SHAPES) from None
    return _edition(target.rec or edition), target


def _no_clause(item: sources.Edition, number: str) -> LibError:
    return LibError(
        f"{item.key}: no clause §{number}",
        f"itu_search for its words, or itu_outline('{_doc(item)}') for the numbering",
    )


def _fragments_warning(item: sources.Edition, number: str) -> str:
    extra = index.fragments(item, number) - 1
    fragment = ""
    if extra:
        fragment = (
            f"{extra} other extracted fragment(s) carry the number {number} (a numbered sub-item, table cell or "
            "history row the splitter could not tell from a heading); this is the first. Check the PDF before "
            "relying on it for a normative claim."
        )
    return join_warning(fragment, sources.standing_of(item))


def _budget_lines(entries: list[str], max_tokens: int) -> list[str]:
    """The leading entries that fit `max_tokens`, always at least one."""
    kept: list[str] = []
    used = 0
    for entry in entries:
        cost = len(entry) // index.CHARS_PER_TOKEN + 1
        if kept and used + cost > max_tokens:
            break
        used += cost
        kept.append(entry)
    return kept


def _rows(rows: tuple[tuple[str, str], ...], doc: str) -> list[str]:
    return [f"{doc}§{number}  {title}" for number, title in rows]


# --- tools ---------------------------------------------------------------------------------------------------


def itu_info(rec: str = "") -> str:
    """Registered editions, their status, digests and amendments, and whether each is fetched. No corpus needed."""
    pool = [item for item in (*sources.IN_FORCE, *sources.SUPERSEDED) if not rec or item.rec == rec]
    lines = [
        f"{item.key}  {item.status}  ({item.edition})  {'fetched' if corpus.has(item) else 'not fetched'}  "
        f"{item.octets} octets  sha256 {item.sha256 or 'not registered'}"
        + (f"  note: {item.note}" if item.note else "")
        for item in pool
    ]
    amendments = [item for item in sources.AMENDMENTS if not rec or item.rec == rec]
    if amendments:
        lines += ["", "amendments:"]
        lines += [
            f"{item.key}  {item.status}  {item.label}" + (f"  note: {item.note}" if item.note else "")
            for item in amendments
        ]
    if not pool and not amendments:
        lines.append(f"nothing is registered for {rec!r}")
    lines += ["", f"corpus home: {corpus.home()}"]
    return render("\n".join(lines), {})


def itu_search(query: str, edition: str = "X.690", limit: int = 8, start: int = 0, max_tokens: int = 1500) -> str:
    """Full-text clause search, best first. One hit per entry: '<ref>  <title>  (<citation>)' and an excerpt.
    Every term is required first; 'relaxed:' says no clause held them all and these hold some. A 'next: start=N'
    footer means more hits: call again with start=N (0-based). No hits means nothing matched."""
    if limit < 1:
        raise LibError(f"limit={limit}", "limit is the number of hits per page, at least 1")
    item = _edition(edition)
    doc = _doc(item)
    found = index.search(item, query, limit, start)
    entries = [
        f"{doc}§{hit.number}  {hit.title}  ({index.citation(item, hit.number)})\n    {hit.excerpt}"
        for hit in found.hits
    ]
    kept = _budget_lines(entries, max_tokens)
    more = start + len(kept) if len(kept) < len(entries) else found.next_start
    body = "\n".join(kept) if kept else f"no clause of {item.key} matches {query!r}"
    relaxed = "no clause holds every term; these hold some of them" if found.relaxed and kept else ""
    return render(body, {"next": next_start(more), "relaxed": relaxed})


def itu_read(ref: str, edition: str = "X.690", max_tokens: int = 2000, view: str = "text") -> str:
    """Read a clause by ref: 'X.690§11.6', '11.6' (in `edition`), one sentence 'X.690§11.6¶2', or the clause from
    a sentence on 'X.690§11.6¶5-'. Long clauses are paged: a 'next:' footer is the ref to pass back as `ref`.
    view: text | normative (shall/should/must/may sentences) | refs (what it points at and what points at it).
    ¶n is the nth sentence of the extracted clause."""
    if view not in {"text", "normative", "refs"}:
        raise LibError(f"view={view!r}", "view is text, normative or refs")
    item, target = _target(ref, edition)
    doc, number = _doc(item), target.number
    if view == "refs":
        return itu_links(f"{doc}§{number}", edition)
    if view == "normative":
        found = index.normative_statements(item, number)
        if found is None:
            raise _no_clause(item, number)
        body = "\n".join(f"{doc}§{number}¶{n}  {sentence}" for n, sentence in found)
        return render(
            body or f"§{number} has no sentence with shall, should, must or may",
            {"cite": index.citation(item, number), "unit": "sentence"},
        )
    if target.para is not None and not target.onward:
        one = index.sentence(item, number, target.para)
        if one is None:
            if index.read(item, number) is None:
                raise _no_clause(item, number)
            raise LibError(f"{item.key}: §{number} has no ¶{target.para}", f"itu_read('{doc}§{number}') numbers them")
        footer = {
            "cite": index.citation(item, number, target.para),
            "unit": "sentence",
            "span": span_hash(one),
            "warning": _fragments_warning(item, number),
        }
        return render(one, footer)
    page = index.page(item, number, start=target.para or 1, max_tokens=max_tokens)
    if page is None or page.total == 0:
        kids = index.children(item, number)
        if kids:
            body = f"§{number}: a heading with no text of its own; read a subclause:\n" + "\n".join(_rows(kids, doc))
            return render(body, {"cite": index.citation(item, number)})
        if page is None:
            raise _no_clause(item, number)
        return render(
            f"§{number} {page.title}: a heading with no text of its own and no indexed subclauses",
            {"cite": index.citation(item, number)},
        )
    footer = {
        "cite": index.citation(item, page.number),
        "unit": "sentence",
        "next": f"{doc}§{page.number}¶{page.next}-" if page.next is not None else "",
        "warning": _fragments_warning(item, number),
    }
    head = f"§{page.number} {page.title}  [¶{page.first}-{page.last} of {page.total}]"
    return render(f"{head}\n\n{page.text}", footer)


def itu_cite(ref: str, edition: str = "X.690") -> str:
    """The citation string for a clause or sentence, built from the registry, with the edition's digest. Its
    'span:' line is the sha256 prefix of the exact text cited. Refuses a clause or ¶ that is not there."""
    item, target = _target(ref, edition)
    number, para = target.number, target.para
    clause = index.read(item, number)
    if clause is None:
        error = _no_clause(item, number)
        raise LibError(f"{error.message}; refusing to cite what is not there", error.hint)
    cited = clause.body
    if para is not None:
        one = index.sentence(item, number, para)
        if one is None:
            raise LibError(f"{item.key}: §{number} has no ¶{para}", f"itu_read('{_doc(item)}§{number}') numbers them")
        cited = one
    cite = index.citation(item, number, para)
    body = f"{cite}\nedition sha256: {item.sha256 or 'not registered'}"
    return render(body, {"cite": cite, "unit": "sentence" if para else "", "span": span_hash(cited)})


def itu_links(ref: str, edition: str = "X.690") -> str:
    """References of a clause: same-document clauses it points at, other recommendations, ISO/IEC and RFC
    citations, and which clauses of this edition cite it. 'unresolved' clause numbers were pointed at but are not
    in the index (an extraction gap, or a clause of another document)."""
    item, target = _target(ref, edition)
    number = target.number
    found = index.links(item, number)
    if found is None:
        raise _no_clause(item, number)
    doc = _doc(item)

    def refs(values: tuple[str, ...]) -> str:
        return ", ".join(f"{doc}§{value}" for value in values) or "-"

    lines = [
        f"points at: {refs(found.clauses)}",
        f"unresolved: {', '.join(found.unresolved) or '-'}",
        f"recommendations: {', '.join(found.recommendations) or '-'}",
        f"standards: {', '.join(found.standards) or '-'}",
        f"cited by: {refs(found.cited_by)}",
    ]
    return render("\n".join(lines), {"cite": index.citation(item, number)})


def itu_browse(path: str = "", depth: int = 2, start: int = 0, max_tokens: int = 1500) -> str:
    """Browse the catalog. No argument: the ITU-T series A-Z and which have registered recommendations. A series
    letter ('X'): its registered recommendations. A recommendation ('X.690'): its clauses down to `depth`, as
    refs, paged: a 'next: start=N' footer means call again with start=N."""
    if not path:
        registered = {item.rec.split(".")[0] for item in sources.IN_FORCE}
        lines = [
            f"{letter}  {title}" + ("  [registered]" if letter in registered else "")
            for letter, title in sources.SERIES.items()
        ]
        return render("\n".join(lines), {})
    if len(path) == 1:
        lines = [
            f"{item.rec}  {'fetched' if corpus.has(item) else 'not fetched'}  {item.title}"
            for item in sources.IN_FORCE
            if item.rec.startswith(path.upper() + ".")
        ]
        return render("\n".join(lines) or f"no recommendation of series {path.upper()} is registered", {})
    item = _edition(path)
    shown, more = index.slice_rows(index.top_level(item, depth), start, max_tokens)
    return render("\n".join(_rows(shown, _doc(item))), {"next": next_start(more)})


def itu_catalog(
    series: str = "X", text: str = "", fmt: str = "", free: bool = False, start: int = 0, max_tokens: int = 1500
) -> str:
    """The ITU-T catalogue read from itu.int by `primarysource itu catalog sync`: in-force editions and the
    formats each is offered in (PDF, EPB=EPUB, MSW=Word, TOC-HTM, SUM-HTM; '*' marks not freely available).
    Metadata only. Paged: a 'next: start=N' footer means call again with start=N."""
    from . import catalog

    letter = series.upper()
    recs = catalog.load(letter)
    found = catalog.rows(recs, text=text, fmt=fmt, free_only=free)
    shown, more = index.slice_rows(
        tuple((f"{r.rec} {r.label}", f"{r.summary()} {r.title}") for r in found), start, max_tokens
    )
    detailed = sum(1 for entry in recs.values() if entry.get("components") is not None)
    head = (
        f"series {letter}: {len(found)} matching components; {detailed} of {len(recs)} recommendations have details"
    )
    lines = [
        f"{row.rec}  {row.kind}  {row.label}  [{row.component}]  approved {row.approved or '-'}  "
        f"{row.summary() or '-'}  {row.title}"
        for row in found[start : start + len(shown)]
    ]
    return render("\n".join([head, *lines]), {"next": next_start(more)})


def itu_compare(
    number: str, edition_a: str = "X.690#2008-11", edition_b: str = "X.690#2021-02", max_tokens: int = 2000
) -> str:
    """Compare one clause between two editions, by sentence: '- [¶n]' lines were removed from a, '+ [¶n]' lines
    added in b. Numbering can differ between editions, so a clause missing from one may have moved, not gone.
    Matching ignores case, whitespace, punctuation and symbols: a change of a symbol alone is not reported."""
    first, second = _edition(edition_a), _edition(edition_b)
    try:
        _rec, clause_number, _para = text.parse_ref(number)
    except ValueError as error:
        raise LibError(str(error), REF_SHAPES) from None
    result = index.compare(first, second, clause_number)
    lines = [f"a: {index.citation(first, clause_number)}", f"b: {index.citation(second, clause_number)}"]
    if not (result.in_a and result.in_b):
        missing = " or ".join(e.key for e, present in ((first, result.in_a), (second, result.in_b)) if not present)
        lines.append(f"§{clause_number} is not in {missing}; the rule may have moved rather than gone")
        return render("\n".join(lines), {})
    if result.same:
        lines.append("identical, ignoring case, whitespace, punctuation and symbols")
        return render("\n".join(lines), {})
    budget = max(max_tokens, 1) * index.CHARS_PER_TOKEN
    left: list[str] = []
    for sign, rows in (("-", result.removed), ("+", result.added)):
        used = 0
        for position, (para, sentence) in enumerate(rows):
            if position and used + len(sentence) > budget:
                left.append(f"{len(rows) - position} {'removed' if sign == '-' else 'added'}")
                break
            used += len(sentence)
            lines.append(f"{sign} [¶{para}] {sentence}")
    warning = f"cut at max_tokens: {' and '.join(left)} sentence(s) not shown; raise max_tokens" if left else ""
    return render("\n".join(lines), {"warning": warning})


def itu_outline(
    edition: str = "X.690", prefix: str = "", depth: int = 0, start: int = 0, max_tokens: int = 1500
) -> str:
    """Clause outline of an edition: one ref and title per line, no bodies. `prefix` limits it to one subtree
    ('8.1'); `depth` caps the numbering depth (0 = all). Paged: a 'next: start=N' footer means call again with
    start=N."""
    item = _edition(edition)
    rows = index.outline(item)
    if prefix:
        rows = tuple(r for r in rows if r[0] == prefix or r[0].startswith(prefix + "."))
    if depth:
        rows = tuple(r for r in rows if r[0].count(".") + 1 <= depth)
    if not rows:
        return render(f"no clause of {item.key} is under {prefix!r} at depth {depth or 'any'}", {})
    shown, more = index.slice_rows(rows, start, max_tokens)
    head = f"{item.key}: {len(rows)} clauses"
    return render("\n".join([head, *_rows(shown, _doc(item))]), {"next": next_start(more)})


def itu_grep(pattern: str, edition: str = "X.690", start: int = 0, max_tokens: int = 1500) -> str:
    """Regular expression (case-insensitive) over clause bodies, one pass, an excerpt around the first match of
    each clause, cut to a token budget. A 'next: start=N' footer means more clauses match: call again with start=N."""
    item = _edition(edition)
    hits, more = index.grep(item, pattern, start=start, max_tokens=max_tokens)
    doc = _doc(item)
    body = "\n".join(f"{doc}§{hit.number}\n    {hit.excerpt}" for hit in hits)
    return render(body or f"no clause of {item.key} matches /{pattern}/", {"next": next_start(more)})


def itu_errata(rec: str = "X.690") -> str:
    """Errata, amendments and corrigenda registered against a recommendation, with the text of each fetched one."""
    items = [item for item in sources.AMENDMENTS if item.rec == rec]
    if not items:
        return render(f"nothing is registered against {rec}", {})
    lines: list[str] = []
    for item in items:
        if not item.artifact:
            lines.append(f"{item.key}  {item.status}; no download id  {item.label}")
        elif corpus.has(item):
            lines += [f"{item.key}  {item.status}; fetched  {item.label}", f"    {errata_text(item)}"]
        else:
            lines.append(f"{item.key}  {item.status}; not fetched (primarysource itu fetch {item.key})  {item.label}")
    caveat = next((item.note for item in items if item.note), "")
    if caveat:
        lines.append(f"note: {caveat}")
    return render("\n".join(lines), {})


TOOLS = (
    itu_info,
    itu_search,
    itu_read,
    itu_cite,
    itu_links,
    itu_browse,
    itu_catalog,
    itu_compare,
    itu_outline,
    itu_grep,
    itu_errata,
)


def build() -> Any:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    app = MCPServer(name="itulib", instructions=INSTRUCTIONS, version=__version__)
    add_tools(app, TOOLS, annotations=ToolAnnotations(**READ_ONLY_HINTS))

    @app.resource(
        "itu://{rec}/{number}",
        name="clause",
        description="One clause as text with its citation, e.g. itu://X.690/11.6",
        mime_type="text/plain",
    )
    def clause_resource(rec: str, number: str) -> str:
        item = _edition(rec)
        page = index.page(item, number, max_tokens=4000)
        if page is None:
            raise _no_clause(item, number)
        return f"{index.citation(item, page.number)}\n\n{page.text}"

    @app.prompt(description="Explain a clause in plain language, grounded in and cited to the fetched text.")
    def explain_clause(ref: str) -> str:
        return (
            f"Explain {ref} in plain language. Call itu_read for the clause (and again with its `next:` ref until "
            "there is none), and itu_links to find the clauses it depends on and read those too. Quote nothing you "
            "did not read from a tool result, and cite every statement with the `cite:` line the tools return, "
            "including the ¶ number for sentences. If a tool returns an error or a `warning:` line, say so instead "
            "of filling the gap from memory."
        )

    @app.prompt(description="Check a claim about an encoding rule against the text, with citations.")
    def verify_claim(claim: str, rec: str = "X.690") -> str:
        return (
            f"Verify this claim against {rec}: {claim}\n\n"
            "Use itu_search (and itu_grep for exact wording), read each candidate clause with itu_read, and "
            "use view=normative to separate obligations from notes. Answer SUPPORTED, CONTRADICTED or NOT "
            "FOUND, cite the clause and edition for each, and check itu_errata for a correction to the cited "
            "text. NOT FOUND means no clause says it; it is not evidence the claim is true or false. Do not "
            "answer from memory."
        )

    return app


def require_extra() -> None:
    """Raise ImportError naming the extra if the MCP SDK is not installed. Checked before anything is served, so
    a missing extra is one clear sentence and exit status 2, never a traceback from deep inside the SDK."""
    try:
        import anyio  # noqa: F401
        from mcp.server.mcpserver import MCPServer  # noqa: F401
    except ImportError as error:
        raise ImportError(
            f"primarysource itu mcp needs the MCP extra: pip install 'primarysource[mcp]' ({error})"
        ) from error


def main() -> None:
    require_extra()
    import anyio

    anyio.run(build().run_stdio_async)


if __name__ == "__main__":
    # stderr, never stdout. stdout *is* the protocol: a friendly notice printed there arrives before the
    # handshake and the client fails with "Failed to parse JSONRPC message from server", naming neither the
    # line nor the reason. The stdio test caught this; importing the module never would.
    print("itulib: speaking MCP on stdio; run it from a client, not a terminal", file=sys.stderr)
    main()
