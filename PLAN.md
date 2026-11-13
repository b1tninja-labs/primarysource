# primarysource plan

Written 2026-11-12. The evidence behind this plan is six read-only inventories of the existing libraries and of the
Docker MCP Toolkit, made the same day; they are summarised here, not repeated.

## 1. Why this exists

Six libraries give agents citable context:
- `rfclib`: the RFC series.
- `itulib`: ITU-T recommendations.
- `zimlore`: Kiwix ZIM archives.
- `nistlib`: NIST publications.
- `usblib`: USB-IF specifications.
- `cvelib`: CVE records merged with the kernel CNA, KEV and EPSS. It is in `D:\code\cvelib`, with no commits yet,
  and was added on 2026-11-12 (see §8).

Measured:

- `rfclib`, `itulib`, `zimlore` and `cvelib` each wrote their own ref grammar, token-budgeted pager, citation
  builder and error-with-a-hint type. All four define `CHARS_PER_TOKEN = 4` separately.
- `nistlib` and `usblib` are one skeleton copied twice. With package names normalised, 10 of their 11 shared
  modules differ by 0 to 17 lines, and the splitter (`ingest/extract.py`) has already drifted 223 lines apart.
  Both re-read and tokenise the whole corpus on every query (1.97 s measured on nistlib). Neither has a ref string
  or paging.
- All six serve MCP over stdio only, so every client starts its own process. Eight `rfclib` processes on one
  SQLite file preceded a corrupted database (cause not established). rfclib PR #1 (branch
  `claude/shared-mcp-http-5bcf0e`, not merged) is the first exit from stdio-only.

`primarysource` is the part none of them should own alone.

## 2. What it is

Two things at once:

1. **The one package for every collection** (§5.8): model, ref grammar, pager, citation skeleton, index,
   readers, MCP scaffolding and base classes in the core, with each library moved in as a collection
   subpackage behind an optional extra. A collection is a source registry plus the corpus-specific parsers,
   citation string and status vocabulary.
2. **A tool in its own right**: point it at a folder of documents and search, read and cite them from a CLI or
   over MCP, with no library written for that folder.

## 3. Layers, and where each comes from

| Layer | State | Best existing source |
|---|---|---|
| Errors with a hint | built | zimlore `errors.py` (two audiences: `hint` for the CLI, `tool_hint` for MCP, `user_command` when a human must act), itulib `mcp._fail`, cvelib `errors.py` |
| Document, section, declared unit, span hash | built | rfclib `blocks`, zimlore `Document`, rfclib `query.span_hash` |
| Token budget and pager | built | rfclib `views.py`, itulib `index.page`, zimlore `service.read`, cvelib `service._page` |
| Ref grammar | built | rfclib `_REF`, itulib `parse_ref`, zimlore `refs.py`, cvelib `service._REF` (`CVE-YYYY-N§section¶n`) |
| Result text with fixed footer | built | rfclib's text results; fields from itulib and zimlore's JSON |
| Home resolution, atomic write | built | rfclib `config.py`, `fsutil.py` |
| Bulk lock | planned | rfclib `fsutil.bulk_lock` |
| Settings: network mode and read-only mode | planned | rfclib `config.py`: `RFCLIB_NETWORK` (auto, on-demand, offline) with `require_network`; `RFCLIB_READONLY` in rfclib PR #1 |
| Pinned, digest-verified fetch and manifest | planned | itulib `sources.py` + `corpus.py` (digests pinned in code), zimlore `catalog.py` (`.part` resume under an `O_EXCL` lock, verified, then `os.replace`), cvelib `sync.py` (ETag, `.part`, disk reserve). nistlib and usblib record a digest on first fetch and pin none |
| Readers | planned | section 4 |
| Segmenters | planned | usblib numbered-heading splitter, itulib bookmark walker, rfclib `txtseg`, zimlore HTML headings |
| FTS5 index (BM25), schema version, read-only query open, write transaction, atomic rebuild | planned | rfclib `search.py`/`lexical.py`, itulib `fts_query` and relaxed matching, cvelib `store.py`. Read-only open: cvelib `store.py` (`mode=ro`, WAL, `busy_timeout`) and rfclib PR #1 (`open_db(read_only=True)`). Write transaction: rfclib PR #1 (`BEGIN IMMEDIATE` in `index_doc`, which fixed a chunk-id race between concurrent writers). Schema version: itulib's `SCHEMA` refuses a mismatched index; cvelib writes a version and never reads it; rfclib's migrations are ad hoc. Atomic rebuild exists nowhere |
| Embeddings and hybrid ranking | **not in the core** (§5.7) | stays rfclib's own `[semantic]` extra (`embed.py`, `hybrid.py`) |
| Citation skeleton, status, subjects | planned | rfclib `cite.py`, `doc_relations`, `subjects.py`; nistlib `status.py` |
| CLI | planned | |
| MCP server, stdio and http from one switch | planned | rfclib PR #1: `rfclib mcp --transport http` (stateless streamable HTTP, JSON responses, `/mcp` on port 8765), `--host` with a DNS-rebinding allow-list for a non-loopback host, `/healthz`, `--read-only`. The lazy `MCPServer` import, exit 2 without the extra, and the stdio runner are nearly identical in itulib, zimlore and cvelib |
| Packaging for serving | planned | rfclib PR #1: two-stage Dockerfile (uid 10001, `/data` volume, HEALTHCHECK on `/healthz`), GHCR push, MCP Registry `server.json` with a PyPI package and an OCI package |
| Test kit | planned | a fixture-corpus builder (rfclib `conftest`, cvelib `conftest`, zimlore `zimfixture.py`), the licence tripwire (itulib and zimlore `test_license.py`), the ROADMAP row gate (`zimlore/tests/test_roadmap_rows.py`) |

## 4. Readers

All readers stream; none extracts an archive to disk.

| Format | Met in | Start from |
|---|---|---|
| Plain text with page furniture | RFC `.txt` | rfclib `txtseg.py` |
| RFCXML | RFC | rfclib `rfcxml.py` |
| HTML | RFC html, ZIM articles, catalogue pages | zimlore `markdown.py` |
| PDF | ITU, USB-IF, NIST | itulib (`pypdf`), nistlib/usblib (`pdftotext`) |
| OSCAL XML | NIST | nistlib `oscal.py` (stays in nistlib; the generic XML walk moves) |
| ZIP of PDFs | USB-IF | usblib `acquire.py` |
| JSON | RFC errata | stays in rfclib |

RTF and DOCX were not met in any inventory. They are reader slots, not commitments.

**PDF backends.** `pypdf` first: pure Python, gives bookmarks, no system package. `pdftotext` is an optional
backend for layout-heavy documents. The owner has said needs were found elsewhere for `pypdfium2` and PyMuPDF;
they are later backends, added when a document needs more than `pypdf` gives (tables, layout, rendering), each as
its own extra. Before PyMuPDF is added, read its licence: it is not MIT, and this package is. (Not verified here.)
Backends give different text, so the backend name and version are part of an index's source hash.

## 5. Decisions already made

1. **Tool results are text**, with `cite:`, `unit:`, `span:`, `next:`, `relaxed:`, `warning:` footer lines in that
   order (`primarysource/render.py`). The passage dominates the tokens and JSON escapes every newline in it; `rfclib`,
   the only published library, already returns text. Structured content can be added later without breaking text
   readers. No token comparison of the two shapes was measured.
2. **`¶n` keeps its per-library unit, and the unit is declared** (`primarysource/model.py::Unit`). RFCs have real
   paragraphs; an extracted PDF clause has only sentences. The section is the durable address.
3. **Own repository.** `rfclib`'s repository is private and `itulib`'s is public; a public library cannot depend
   on a private one. With §5.8 this repository becomes the home of every collection, so it must be public, and
   rfclib's code becomes public when it moves in. That is already true of its published PyPI sdist.
4. **A collection is the unit of storage and naming**: one database and one tool-name prefix. Since §5.8, one
   server process or container may serve several collections.
5. **Serving shape**: one long-lived HTTP server per library under `docker compose` on loopback. The Docker MCP
   Toolkit's gateway starts a container per server per client session (or per call), so it does not give one
   shared process; it can front these servers later.
6. **Corpus placement**: RFC text may go in an image layer (terms the project quotes); NIST text may, for
   NIST-authored works with NIST's credit line, once nistlib records authorship; ITU, USB-IF and ZIM content go on
   volumes.
7. **Keyword search only.** The core's index is FTS5 ranked by BM25, with column weights and a rank hook per
   collection. The core has no embeddings or vector store, and no shared server depends on one. This was the
   owner's instruction on 2026-11-12. rfclib's hybrid ranking stays rfclib's own optional extra, and its CI
   already checks that it degrades to keyword search without that extra.
8. **One package, collections as optional extras** (owner's decision, 2026-11-12, chosen over one repository
   holding separate distributions). The libraries move into this package and stop being separate projects:

   | Collection | Subpackage | Extra | Tool prefix |
   |---|---|---|---|
   | RFC series | `primarysource.rfc` | `[rfc]` | `rfc_` (bare names kept until the owner decides, §7) |
   | ITU-T | `primarysource.itu` | `[itu]` (`pypdf`) | `itu_` |
   | NIST | `primarysource.nist` | `[nist]` | `nist_` |
   | USB-IF | `primarysource.usb` | `[usb]` | `usb_` |
   | Kiwix ZIM | `primarysource.zim` | `[zim]` (`libzim`) | `zim_` |
   | CVE | `primarysource.cve` | `[cve]` | `cve_` |

   Shared extras: `[mcp]` for the server and `[all]` for everything. Rules that follow from this:
   - **The core never imports a collection.** A collection registers itself (name, tool prefix, unit, ref
     pattern, builders), and the CLI and the MCP server serve whichever collections are named or installed:
     `primarysource mcp --collection nist --collection usb`. A collection whose extra is missing fails with a
     `LibError` that names `pip install "primarysource[<name>]"`, never with an `ImportError`. The registry is
     `primarysource/registry.py`. It reads the built-in table and the `primarysource.collections` entry-point
     group the same way, so a collection whose licence or release cadence must differ can ship as its own
     package that depends on `primarysource` and registers itself. A built-in always wins a name clash.
   - **One process can serve several collections**, each with its own database and its own tool prefix. §5.4
     still holds: a collection is the unit of storage and naming. Serving more than one is now a flag instead of
     another container.
   - **An extra adds dependencies only.** Every collection's code ships in every wheel, so the package has one
     version and one licence (MIT). Each move needs the owner's yes on the licence where the library declared
     another (§7).
   - **Each move keeps the library's history** (`git subtree add` into the collection's directory, then `git mv`
     into place) and brings the library's tests with it. The old repository is then archived with a README that
     points here. `rfclib` stays published on PyPI as a thin distribution that depends on `primarysource[rfc]`
     and keeps the `rfclib` command, so that nobody's configuration breaks.
   - **Tracked metadata moves; corpus text never does.** Catalogues, `sources.toml` and digests are package
     data. Fetched text lives under the home directory, per collection (`$PRIMARYSOURCE_HOME/<collection>/`).
     The old `<LIB>_HOME`/`<LIB>_DATA` variables are read as fallbacks for one release.

## 6. Adoption order

Since §5.8, "adoption" means moving the library in as a collection subpackage, not depending on this package
from outside. The order below stands.

0. **Before any adoption**:
   - commit this repository (done 2026-11-12);
   - merge rfclib PR #1, so that the HTTP transport, read-only open and write transaction are lifted from code
     that already serves rather than written twice.
1. `nistlib` and `usblib` together, because they are unpublished, have the least to lose and the most to gain:
   - the shared skeleton in place of the copy;
   - an FTS5 index in place of the per-query scan;
   - a ref string, token paging and one home.
2. `cvelib`, before its first commit if its author agrees. It already has the hardened open and the FTS5 shape,
   and it is the source for `cl.index_readonly_open`.
3. `itulib`:
   - pager, ref grammar and error type;
   - read-only open and atomic rebuild;
   - an atomic fetch (its `corpus.py` writes a PDF in place);
   - a digest check that runs when the file changes, not on every open.
4. `zimlore`: pager, ref grammar, error type and transport only. Its search stays libzim, and its download code
   moves *into* the core as the pinned fetch.
5. `rfclib` last, once `primarysource` is on PyPI: it is the published one, and its checkout has work in progress.

Each library's rows for its own step are in its ROADMAP:
- `nistlibrary/ROADMAP.md` §4;
- `usblibrary/ROADMAP.md` §4;
- `itulibrary/ROADMAP.md` §6;
- `zimlore/ROADMAP.md` §10.

rfclib has no matrix, so its items are in `PORTFOLIO.md` §9 item 13:
- lift `fsutil`, the settings, `open_db`'s read-only path and the `views` pager;
- replace the ad hoc migrations with `PRAGMA user_version`;
- add a `relaxed` flag to keyword search.

## 7. Open

- The name passed the PyPI check on 2026-11-12 (`projecthub shells names --index`: free on both signals, no live
  one-keystroke neighbour in 936,266 names). GitHub and off-PyPI brand collisions were not checked.
- Not in `PORTFOLIO.md`. Proposed: an untiered reference-library entry, like `rfclib`, `itulib` and `zimlore`.
  `nistlib`, `usblib` and `cvelib` are not registered either. `PORTFOLIO.md` §9 item 13 puts the registration
  to the maintainer.
- **Result shape is a decision taken without a measurement** (§5.1). rfclib, nistlib and usblib return text,
  while itulib, zimlore and cvelib return compact JSON. Measure both shapes on the same reads before the second
  library adopts either.
- **Error contract.** rfclib and nistlib raise an MCP tool error (`isError`). itulib, zimlore and cvelib return
  an `error`/`hint` object as an ordinary result. Proposed: one `LibError` that renders as an `isError` result
  and keeps zimlore's two audiences.
- **One cursor shape.** `next` is a ref string in rfclib and in cvelib's read, and an integer `start` in itulib,
  zimlore and cvelib's search. Proposed: a read's `next` is always a ref string that `read` accepts back, and
  the integer `start` stays for lists only.
- **Tool prefix** (§5.4). rfclib, nistlib and usblib use bare names, and itulib, zimlore and cvelib use `itu_`,
  `zim_` and `cve_`. Renaming rfclib's tools breaks a published interface, so it needs the owner's yes.
- **Licence of nistlib and usblib.** Both declare Apache-2.0 in `pyproject.toml` and ship no LICENSE file.
  This package and the rest of the family are MIT. Under §5.8 their code ships inside this MIT package, so
  moving them in needs the owner to relicense them to MIT. **This blocks step 1 of §6.**
- **The self-sufficiency rule** ("no third-party runtime dependencies"; the owner's rule, now applied
  portfolio-wide) and the extras in §5.8 (`mcp`, `pypdf`, `libzim`) disagree. Either the rule allows optional
  extras, or each of those needs becomes its own portfolio project first.
- First commit made on 2026-11-12. There is no GitHub remote yet. The repository must be public, or
  public-compatible, because itulib is public and will depend on it.

## 8. Review, 2026-11-12

A second read-only pass measured all six libraries against this plan. Its report is in the side-session notes
for the rfclib shared-server work. The pass also checked rfclib PR #1. It corrected the following:

- `cvelib` was missing.
- §1 said seven of the nistlib/usblib modules matched. The count is ten of eleven.
- `cl.index_readonly_open` said "in no library today". cvelib opens `mode=ro` already, and rfclib PR #1 adds
  the same.
- Embeddings were planned as an optional extra. They are now outside the core (§5.7).
- `cl.mcp_http` pointed at work in progress. It now names rfclib PR #1.

It also added:
- the settings, write-transaction, schema-version, packaging and test-kit layers;
- `cvelib` in the adoption order;
- the open contract questions in §7.

The code and tests were not touched, and the plan's other decisions stand.
