"""FastMCP server exposing the local RFC library over the MCP protocol.

Nine tools, one job each, all answering in compact plain text and all
addressed by the same refs (see rfclib.views): search -> read -> cite is the
core loop; outline/grep/links/info/browse/errata support it. Tool names are
what a deferred-tool client sees first, so each one says what it does. The
heavy lifting lives in rfclib.views; this module only maps errors to
isError results and declares annotations, prompts and resources.
"""

from __future__ import annotations

import json
import sqlite3

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import (Completion, PromptReference, ResourceTemplateReference,
                       ToolAnnotations)

from .. import __version__, library
from .. import query as q
from .. import views
from ..config import NetworkDisabled, Paths, read_only
from ..sync.state import open_db

INSTRUCTIONS = (
    "RFC library: the full RFC/BCP/STD/FYI corpus from the RFC Editor, "
    "searchable by section, with status (obsolete/superseded), errata, "
    "citations and the RFC Editor subject tree. Use it for any question "
    "about an IETF protocol or standard (HTTP, TLS, QUIC, DNS, TCP, IP, "
    "SMTP, URI, BGP...): search('<question>') -> read('<ref>') -> follow "
    "the 'next:' ref -> cite('<ref>'). Refs are citations: 'RFC9000' "
    "(overview), 'RFC9000§9.6' (section), 'RFC9000§9.6¶2' (paragraph), "
    "'RFC9000:2964-2979' (lines); BCP/STD aliases resolve. NEVER open the "
    "mirror's .txt files directly: they are long and get truncated. "
    "Before quoting a document check that it is current (read/info show "
    "OBSOLETE + successor). read(view='normative') lists MUST/SHOULD "
    "statements; view='code' the ABNF/YANG/figures. If the library is "
    "empty or partly synced, tools say so and what to run."
)

# Everything is read-only over local state; tools that may fetch a missing
# file or errata from rfc-editor.org are open-world.
RO = ToolAnnotations(read_only_hint=True, idempotent_hint=True,
                     destructive_hint=False, open_world_hint=False)
RO_NET = ToolAnnotations(read_only_hint=True, idempotent_hint=True,
                         destructive_hint=False, open_world_hint=True)
# Claude Code defers MCP tools behind tool search, and a model that calls a
# deferred tool without loading its schema guesses argument names (the
# agent eval caught errata(query=...) 5 times in 22 tasks). The core loop
# (search, read) and errata, which read headers send agents to, load up
# front.
ALWAYS = {"anthropic/alwaysLoad": True}

mcp = MCPServer("rfclib", version=__version__, instructions=INSTRUCTIONS)

_REF_HELP = ("ref forms: 'RFC9000' | 'RFC9000§9.6' | 'RFC9000§9.6¶2' | "
             "'RFC9000#table-2' | 'RFC9000:2964-2979'.")


def _conn():
    if read_only():                     # never create or migrate anything
        paths = Paths.default()
        try:
            return open_db(paths.db, read_only=True), paths
        except sqlite3.OperationalError as e:
            raise ToolError(str(e)) from None
    paths = Paths.default().ensure()
    conn = open_db(paths.db)
    library.maybe_bootstrap(conn)       # no-op unless RFCLIB_AUTO_INIT=1
    return conn, paths


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request):
    """Liveness for the HTTP transport (Docker HEALTHCHECK, monitors): the
    process is up and can open its library. Not part of MCP."""
    from starlette.responses import JSONResponse
    try:
        conn, _paths = _conn()
        docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        conn.close()
    except Exception as e:  # noqa: BLE001 - report, never raise
        return JSONResponse({"status": "error", "error": str(e)[:300]},
                            status_code=503)
    return JSONResponse({"status": "ok", "version": __version__,
                         "documents": docs, "read_only": read_only()})


def _run(fn, *a, **k) -> str:
    """Call a view; anticipated failures become isError results whose text
    says how to fix the call."""
    try:
        return fn(*a, **k)
    except views.RefError as e:
        msg = str(e)
        if not msg.startswith("The RFC library"):   # ref problems get help
            msg = f"{msg} {_REF_HELP}"
        raise ToolError(msg) from None
    except q.NotFound as e:
        raise ToolError(f"{e} is not in the local index (rfclib manifest "
                        "--refresh updates it).") from None
    except NetworkDisabled as e:
        raise ToolError(str(e)) from None
    except sqlite3.OperationalError as e:
        if "readonly" not in str(e) or not read_only():
            raise
        raise ToolError(
            "this server is read-only (RFCLIB_READONLY) and the library "
            "needs a write first, most likely a schema update: open it once "
            "with the shared rfclib server or `rfclib status`.") from None


@mcp.tool(annotations=RO, structured_output=False, meta=ALWAYS)
def search(query: str, scope: str = "sections", mode: str = "hybrid",
           limit: int = 8, subject: str | None = None,
           status: str | None = None, include_obsolete: bool = False,
           detail: str = "concise") -> str:
    """Find where RFCs answer a question. Hits are refs (paragraph-precise
    when possible) with a snippet, ready for read() and cite().

    scope: sections (default: which passage says X) | documents (which RFC
      is about X; matches titles/abstracts/keywords).
    mode (sections): hybrid (default, keyword+semantic) | exact (FTS5:
      "quoted phrase", AND/OR, prefix*, NEAR(a b, 40)) | semantic
      (paraphrase/concept).
    subject/status: restrict documents to an RFC-Editor subject slug
      ('quic', 'http') or status ('INTERNET STANDARD', 'BCP').
    Obsolete documents are excluded unless include_obsolete=True.
    detail: concise | detailed (adds line ranges and which index matched).
    """
    conn, _ = _conn()
    return _run(views.search_text, conn, query, scope=scope, mode=mode,
                limit=limit, subject=subject, status=status,
                include_obsolete=include_obsolete, detail=detail)


@mcp.tool(annotations=RO_NET, structured_output=False, meta=ALWAYS)
def read(ref: str, max_tokens: int = 2000, view: str = "text",
         lang: str | None = None, format: str = "txt") -> str:
    """Read RFC text by ref. Pages are cut at paragraph boundaries within
    max_tokens and end with 'next: <ref>' (call read with it to continue)
    plus up/after neighbours. Paragraphs are marked [§9.6¶2] so any of them
    is citable.

    ref: 'RFC9000' (abstract + outline) | 'RFC9000§9.6' | 'RFC9000§9.6¶2'
      | 'RFC9000#table-2' | 'RFC9000:2964-2979' | 'BCP14' (alias -> RFC).
    view: text | normative (only MUST/SHOULD/MAY statements) | code
      (sourcecode/figures; lang='abnf'|'yang'|'asn.1'|...) | refs (what
      this scope cites).
    format: txt (default) | html | xml | json: raw slice of another
      rendering by line range (e.g. read('RFC9000:1-200', format='xml')).
    """
    conn, paths = _conn()
    fmt = (format or "txt").lower().strip(". ")
    if fmt != "txt":
        if fmt not in ("html", "xml", "json", "pdf"):
            raise ToolError("format must be txt | html | xml | json")
        ref_ = _run(views.parse_ref, conn, ref, need_text=False)
        try:
            return q.read_document(conn, ref_.served, mirror_root=paths.mirror,
                                   fmt=fmt, start_line=ref_.start or 1,
                                   count=((ref_.end or (ref_.start or 1) + 199)
                                          - (ref_.start or 1) + 1),
                                   max_chars=max(400, max_tokens * 4))
        except q.NotFound as e:
            raise ToolError(str(e)) from None
    return _run(views.read, conn, ref, mirror_root=paths.mirror,
                max_tokens=max_tokens, view=view, lang=lang)


@mcp.tool(annotations=RO, structured_output=False)
def outline(ref: str, depth: int | None = 2,
            contains: str | None = None) -> str:
    """Section outline of one document (ref='RFC9112'): one line per section
    with its line range (depth 2 by default, all levels when contains=
    filters by number/title, e.g. contains='security'). Then
    read('RFC9112§<num>')."""
    conn, _ = _conn()
    return _run(views.outline, conn, ref.split("§")[0].split(":")[0],
                depth=depth, contains=contains)


@mcp.tool(annotations=RO_NET, structured_output=False)
def grep(ref: str, pattern: str, max_hits: int = 25,
         ignore_case: bool = True) -> str:
    """Regex search inside ONE document or section (ref='RFC9110' or
    'RFC9110§15'); each hit carries its paragraph ref and line. The cheap
    way to find a field name, ABNF rule or error code in a known RFC.
    Invalid regexes fall back to a literal search."""
    conn, paths = _conn()
    return _run(views.grep, conn, ref, pattern, mirror_root=paths.mirror,
                max_hits=max_hits, ignore_case=ignore_case)


@mcp.tool(annotations=RO, structured_output=False)
def cite(ref: str, style: str = "verbose") -> str:
    """Checkable citation for a ref: label, title, date, status (warns when
    obsolete), anchor URL, errata status and a hash of the cited span.
    style: verbose | short | markdown | comment | bibtex. Cite rather than
    paraphrase normative text."""
    conn, paths = _conn()
    return _run(views.cite, conn, ref, mirror_root=paths.mirror, style=style)


@mcp.tool(annotations=RO, structured_output=False)
def links(ref: str, direction: str = "out", limit: int = 30) -> str:
    """Citation links of a document or section, section-precise where the
    text says so ('RFC9000§8.1 cites RFC9002 §6.2 [normative]').
    direction: out (what it cites) | in (who cites it) | related (other
    documents in the same RFC-Editor subjects)."""
    conn, _ = _conn()
    return _run(views.links, conn, ref, direction=direction, limit=limit)


@mcp.tool(annotations=RO, structured_output=False)
def info(ref: str, detail: str = "concise") -> str:
    """Bibliographic record and status of one document: title, status,
    current/OBSOLETE with successor, obsoletes/updates graph, BCP/STD
    alias members (BCP14 -> RFC2119 + RFC8174), authors, subjects, errata
    summary, abstract. ref is a document id ('RFC2616', 'BCP14'); a section
    part is ignored. detail='full' returns the complete JSON record."""
    conn, _ = _conn()
    doc = ref.split("§")[0].split(":")[0].split("#")[0]
    if (detail or "").lower() == "full":
        try:
            return json.dumps(q.get_metadata(conn, q.normalize_doc_id(doc)),
                              ensure_ascii=False, indent=1)
        except (ValueError, q.NotFound) as e:
            raise ToolError(f"unknown document {doc!r}: {e}") from None
    return _run(views.info_text, conn, doc)


@mcp.tool(annotations=RO, structured_output=False)
def browse(subject: str | None = None, parent: str | None = None,
           contains: str | None = None, recent: bool = False,
           offset: int = 0, limit: int = 30,
           include_obsolete: bool = False) -> str:
    """Browse without a query: the RFC Editor subject tree and what is new.

    no args: the top-level subjects (slug, doc count, subtopics);
    parent='web': one level down; contains='http': find subjects by name;
    subject='quic': the documents in that subject (newest first, paged with
    offset); recent=True: most recently published RFCs."""
    conn, _ = _conn()
    if recent:
        return views.recent_text(conn, limit=limit)
    if subject:
        return _run(views.subject_docs, conn, subject, offset=offset,
                    limit=limit, include_obsolete=include_obsolete)
    return _run(views.subjects_tree, conn, parent=parent, contains=contains)


@mcp.tool(annotations=RO_NET, structured_output=False, meta=ALWAYS)
def errata(ref: str, status: str = "verified",
           section: str | None = None, max_tokens: int = 2000) -> str:
    """Errata for a document or one section, with the corrected text:
    ref='RFC791' or 'RFC791§3.1' (or section='3.1'). status: verified
    (default; the authoritative corrections) | open (reported/held) | all.
    Check before implementing."""
    conn, _ = _conn()
    try:
        return _run(views.errata_text, conn, ref, status=status,
                    section=section, max_tokens=max_tokens)
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001 - upstream/network
        raise ToolError(f"errata unavailable: {e}") from None


# --------------------------------------------------------------------------
# resources: '@rfclib:rfc://RFC9000§9.6' attaches a section to a prompt

@mcp.resource("rfc://{ref}", name="rfc", mime_type="text/plain",
              description="RFC text by ref, e.g. rfc://RFC9000§9.6 or "
                          "rfc://RFC9112§6.3¶2 (first page; the footer gives "
                          "the next ref).")
def rfc_resource(ref: str) -> str:
    conn, paths = _conn()
    try:
        return views.read(conn, ref, mirror_root=paths.mirror,
                          max_tokens=4000)
    except (views.RefError, q.NotFound) as e:
        raise ResourceError(str(e)) from None


# --------------------------------------------------------------------------
# prompts: user-invoked workflows (/rfclib:explain, /rfclib:checklist, ...)

@mcp.prompt(name="explain", title="Explain an RFC section")
def explain_prompt(ref: str) -> str:
    """Explain what a section requires, grounded in its text and status."""
    return (f"Explain {ref} for an implementer. First call "
            f"mcp__rfclib__read('{ref}') (follow 'next:' until the section "
            "ends) and mcp__rfclib__info on its document; if the document "
            "is obsolete, say so and find the successor's matching section. "
            f"Check mcp__rfclib__errata for that section. Summarise the "
            "behaviour in plain language, quote the MUST/SHOULD sentences "
            "verbatim, and finish with mcp__rfclib__cite for each passage "
            "you relied on.")


@mcp.prompt(name="checklist", title="Compliance checklist for a section")
def checklist_prompt(ref: str) -> str:
    """Turn a section's normative statements into a checklist."""
    return (f"Build an implementation checklist for {ref}. Call "
            f"mcp__rfclib__read('{ref}', view='normative') and page with "
            "'next:'. One checklist item per requirement: the keyword "
            "(MUST/SHOULD/MAY), a short imperative, and the paragraph ref "
            "it comes from. Group by subsection. Add verified errata from "
            f"mcp__rfclib__errata that touch these sections. Do not "
            "paraphrase away conditions: keep every 'if/when/unless'.")


@mcp.prompt(name="current", title="Find the current spec for a topic")
def current_prompt(topic: str) -> str:
    """Which RFCs currently define a topic, and what they replaced."""
    return (f"Which RFCs currently specify {topic}? Use "
            f"mcp__rfclib__search('{topic}', scope='documents') and "
            "mcp__rfclib__browse(contains=...) for the subject. For each "
            "candidate call mcp__rfclib__info: report only current "
            "documents, each with its status and what it obsoletes/updates. "
            "Mention obsolete predecessors people still cite and what "
            "replaced them.")


# --------------------------------------------------------------------------
# completions: document ids and section numbers for prompts and rfc://

@mcp.completion()
async def complete(ref, argument, context):
    if not isinstance(ref, (PromptReference, ResourceTemplateReference)):
        return None
    if argument.name not in ("ref", "doc"):
        return None
    conn, _ = _conn()
    val = (argument.value or "").strip()
    if "§" in val:                      # doc chosen: complete its sections
        doc, part = val.split("§", 1)
        try:
            did = q.resolve(conn, q.normalize_doc_id(doc))
        except ValueError:
            return Completion(values=[])
        rows = conn.execute(
            "SELECT DISTINCT sec_num FROM chunks WHERE doc_id=? AND "
            "sec_num LIKE ? ORDER BY start_line LIMIT 50",
            (did, part + "%")).fetchall()
        vals = [f"{doc}§{r['sec_num']}" for r in rows if r["sec_num"]]
        return Completion(values=vals[:100], has_more=len(vals) >= 100)
    digits = "".join(ch for ch in val if ch.isdigit())
    series = "".join(ch for ch in val if ch.isalpha()).upper() or "RFC"
    rows = conn.execute(
        "SELECT doc_id FROM docs WHERE doc_id LIKE ? ORDER BY is_current "
        "DESC, length(doc_id), doc_id LIMIT 20",
        (f"{series}{digits}%",)).fetchall()
    return Completion(values=[r["doc_id"] for r in rows])
