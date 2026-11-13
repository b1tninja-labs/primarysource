# Research record

Everything here was read or measured on **2026-11-07**. "Verified" means I fetched or ran it in this session;
"not verified" is stated where a fact would otherwise be assumed. Nothing is from memory.

## 1. Context7

Sources: the repository `upstash/context7` (README fetched raw through `gh api`, plus a page summary), and
`context7.com/docs/api-guide` (read through a summarising fetch, so second-hand).

| Fact | Source |
|---|---|
| MCP tools: `resolve-library-id(libraryName, query)` returns Context7-compatible IDs; `query-docs(libraryId, query, language?)` returns documentation. CLI equivalents `ctx7 library` / `ctx7 docs` (Node 22.13+). | repository README |
| IDs are the library's URL path on context7.com: `/owner/repo` for Git hosts, plus `/websites/<name>`, `/llmstxt/<source>`, `/packages/<name>` or `/npm/<name>`, `/docs/<name>`. A version is `/owner/repo/<version>` or `/owner/repo@<version>`; an unindexed version falls back to the closest match, an unindexed branch returns `404 version_not_found`. | api-guide |
| Hosted MCP endpoint `https://mcp.context7.com/mcp`; auth by `Authorization: Bearer <key>`. The repository holds only the MCP server (MIT); "the API backend, parsing engine, and crawling engine are private". | README |
| Rate limits: unkeyed requests get low limits, keyed ones more by plan; `429` carries `Retry-After`, `RateLimit-Limit/-Remaining/-Reset`. A free key is "recommended for higher rate limits". | README, api-guide |
| REST: `GET /api/v2/libs/search`, `GET /api/v2/context` (`libraryId`, `query`, `type=json|txt`, `language`), `GET /api/v3/search` (up to four `library` hints, `version`). JSON has `codeSnippets` (`codeTitle`, `codeList`) and `infoSnippets`. | api-guide |

**Not verified:** any token limit or default response size (the api-guide documents none), the text response
format, pricing tiers, the number of indexed libraries, the ranking method. The README comparison table in this
repository therefore makes no claim about them.

## 2. Kiwix and the ZIM format

| Fact | Source |
|---|---|
| Catalogue feed: `https://library.kiwix.org/catalog/v2/...` answers `301` to `https://opds.library.kiwix.org/catalog/v2/...`. Root, `entries`, `partial_entries`, categories, and an OpenSearch description exist. `entries?q=&lang=&name=&count=` filter; `totalResults` is reported. **3,656** entries in total; `lang=eng` (count 5000) returned **1,309**. | fetched and parsed |
| Per entry: `name`, `title`, `updated`, `summary`, `language`, `tags`, `articleCount`, `mediaCount`, author, and an acquisition link of type `application/x-zim` whose href ends `.zim.meta4`. | fetched |
| The feed's `length` is **rounded**: `devdocs_en_flask_2026-10` is listed as 617,472 bytes and is 617,313 bytes on disk. | measured |
| `.meta4` (Metalink) carries the true `<size>` and `<hash type="sha-256">`. The `.zim` URL redirects (`301` to `lb.download.kiwix.org`, `302` to a mirror host). Downloaded `flask.zim` and `python.zim` SHA-256 matched the `.meta4` exactly. | measured |
| **DevDocs**: 243 ZIMs named `devdocs_en_<slug>`, 666,053,632 bytes in total, median 0.85 MB, largest `devdocs_en_scikit-learn` 58.4 MB, dated 2026-05-04 … 2026-10-31. Scraper `devdocs2zim v0.2.1`. | catalogue, ZIM metadata |
| Other developer ZIMs: `docs.python.org_en_all` 3,959 MB (2026-08-28), `peps.python_en_all` 9.1 MB, `devhints.io_en_all` 3.7 MB, `www.mankier.com_en_all` 183 MB (2026-10-27), `archlinux_en_all` 38 MB, `gentoo_en_all` 96 MB, `php.net_en_all` 32.8 MB (**2024-08-13**), `freecodecamp_en_*`, `stackoverflow.com_en_all` 114,856 MB (2026-07-02), 181 Stack Exchange ZIMs totalling 191.4 GB. | catalogue |
| Mandatory metadata (seen in both real ZIMs): `Name`, `Title`, `Creator`, `Publisher`, `Date` (YYYY-MM-DD), `Description`, `Language` (ISO 639-3); also `Tags`, `Scraper`, `Counter`, an `Illustration_48x48@1` PNG. **Neither real ZIM has a `License` key.** `License` and `Source` are optional keys: this comes from scraperlib's code, because the authoritative spec page (`wiki.openzim.org/wiki/Metadata`) was blocked by a bot filter. | ZIM files; search result |
| The catalogue tag `_ftindex:no` is on every DevDocs entry, **yet both downloaded ZIMs report `has_fulltext_index == True` and answer full-text queries** (flask: 15 estimated matches for "blueprint"). The tag does not mean what its name says; zimlore trusts the archive header. | measured |

**Not verified:** how many catalogue ZIMs carry a `License` key (n = 2 inspected); whether the other
documentation ZIMs (`docs.python.org_en_all`, mankier, Arch) are full-text indexed; kiwix-serve's HTTP surface
(only its existence and GPL-3.0 licence were read, from `kiwix/kiwix-tools`).

## 3. libzim / python-libzim

| Fact | Source |
|---|---|
| `libzim` 4.1.0, released 2026-11-05, `Requires-Python >=3.11,<3.16`, licence **GPL-3.0-or-later** (wheel `METADATA`); the repository `openzim/python-libzim` says GPL-3.0, `openzim/libzim` GPL-2.0, `kiwix/kiwix-tools` GPL-3.0. | PyPI JSON, wheel, `gh api` |
| Wheels: `cp311-abi3` for win_amd64, macOS 13 arm64 and x86_64, manylinux_2_28 x86_64/aarch64, musllinux_1_2 x86_64/aarch64, plus `cp314t`/`cp315t` free-threaded wheels, and an sdist. **No Windows ARM64 wheel.** abi3 means one wheel covers 3.12, 3.13, 3.14. | PyPI JSON |
| Verified here: installed and imported on CPython 3.14.3 and 3.12, Windows. **3.13 is not installed on this machine, so it is untested** (the abi3 wheel should cover it). | run |
| API (snake_case, not the camelCase older examples use): `Archive(path)`, `entry_count`, `article_count`, `has_fulltext_index`, `has_title_index`, `get_entry_by_path/id`, `has_entry_by_path`, `main_entry`, `get_metadata(key)` (bytes), `metadata_keys`, `Entry.is_redirect/get_redirect_entry/get_item`, `Item.mimetype/content`; `libzim.search.Searcher/Query`, `libzim.suggestion.SuggestionSearcher`; writer: `Creator`, `Item`, `StringProvider`, `Hint`, `add_redirection`. A `SearchResult` has a `path` and **no score and no snippet**. Entries are stored sorted by path, which `zim_outline --prefix` relies on (checked: `paths == sorted(paths)` on a 519-entry ZIM). | introspection |
| Query behaviour found by running it: the parser requires **every** term (a word found in no page empties the result), applies stemming (`tests` finds `testing`), accepts `OR`, but a 4-term `OR` query containing an absent word returned nothing — so zimlore fuses per-word searches instead. A malformed query did not raise. | measured |
| DevDocs ZIM page shape: each article is a complete HTML page with an application shell (a `<devdocs-navbar>` custom element, preload links) around `<main class="_content">`; images are inline `data:image/png;base64` (the flask index page is 47 KB, mostly one image); code is `<pre data-language="python">`; sections are `<section id>`; API entries are `<dl><dt id="os.getcwd">`. Entry titles are not always page names (`api/index` is titled `_AppCtxGlobals`). | ZIM contents |

The writer leaves Xapian scratch next to the archive on Windows (`<name>.zim*idx*`, sealed read-only);
`rfclib/packs/zimexport.py` already knew this and `tests/zimfixture.py` sweeps it the same way.

## 4. MCP SDK

`mcp` 2.3.0 is what `itulib` pins (`mcp>=2.3`) and what is installed. `from mcp.server.mcpserver import MCPServer`
(`FastMCP` was renamed); `@app.tool(description=...)`, `@app.prompt(...)`, `run_stdio_async()`; on the client,
`InitializeResult.server_info` (not `serverInfo`). Driven end to end by `tests/test_cli_and_mcp.py` and by the
live run in section 5.

## 5. Live run against real ZIMs

`devdocs_en_flask_2026-10.zim` (617,313 bytes) and `devdocs_en_python_2026-10.zim` (4,775,641 bytes) were
downloaded to a scratch directory outside the repository, their SHA-256 matched to the `.meta4`, and the real MCP
client (`mcp.client.stdio.stdio_client` + `ClientSession`) spawned `python -m zimlore.mcp` over stdio and called
all seven tools. Observed: 7 tools listed; both libraries listed with date and `full-text`; `zim_resolve python`
→ `devdocs_en_python`; `zim_read` of `patterns/appfactories/index` returned 9 of 33 blocks with a `next` cursor and
the two pages together held a `python` code fence; `zim_read python§library/os#os.getcwd` returned exactly the definition
and its sentence; `zim_outline` of `library/zoneinfo` gave anchors; `zim_links` marked internal targets
`in_zim: true` and left external ones as URLs; errors (`no entry 'nope'`, unknown library `cobol`) came back as
objects with a hint and the installed names.

## 6. Retrieval eval, three runs of the same 34 cases

The cases were written from entry titles and committed (`c3c468b`) before any run. Scoped to one library:

| Run | hit@1 | hit@5 | MRR |
|---|---|---|---|
| 1. strict Xapian query (every word required) | 8/34 | 14/34 | 0.310 |
| 2. + per-word fusion weighted by rarity when strict finds fewer than `limit` | 10/34 | 21/34 | 0.421 |
| 3. + title-suggestion boost (`TITLE_BOOST = 3.0`, tried once) | 10/34 | 23/34 | 0.436 |

A title-suggestion-only baseline scored 0/34 (paraphrases do not prefix-match titles). With no library given, 1/4.
Run 1's misses were dominated by the all-terms rule; the remaining misses are mostly vocabulary gaps no keyword
engine bridges. The cases are few, so differences of one or two should not be read as signal.
