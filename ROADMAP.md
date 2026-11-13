# primarysource roadmap

Same rule as every other matrix in this workspace: **a row reads `[ok]` only when a named test would fail if the
behaviour regressed.** A row for something planned reads `[ ]` and names where the behaviour exists today.

Legend: `[ok]` implemented and pinned by a named test -- `[part]` partial, with what is missing stated --
`[ ]` not implemented -- `[no]` deliberate non-goal.

## 1. Core that exists

| Obligation | Spec | Status | Where |
|---|---|---|---|
| `cl.error_hint` | PLAN.md §3 | `[ok]` | `tests/test_model_render_home.py::test_an_error_carries_its_hint_into_the_text` |
| `cl.model_sections` | PLAN.md §3 | `[ok]` | `tests/test_model_render_home.py::test_a_section_is_found_by_id_and_a_missing_one_is_none`, `tests/test_model_render_home.py::test_duplicate_section_ids_are_reported_and_the_first_wins` |
| `cl.span_hash` | PLAN.md §3 | `[ok]` | `tests/test_model_render_home.py::test_span_hash_is_stable_and_changes_with_the_text` |
| `cl.paging` | PLAN.md §3 | `[ok]` | `tests/test_budget.py::test_paging_follows_next_and_loses_nothing`, `tests/test_budget.py::test_a_page_always_makes_progress_when_one_unit_exceeds_the_budget`, `tests/test_budget.py::test_a_unit_is_never_split` |
| `cl.ref_grammar` | PLAN.md §3 | `[part]` | `tests/test_refs.py::test_the_three_existing_ref_spellings_parse`, `tests/test_refs.py::test_a_string_that_is_not_a_ref_is_refused_with_a_hint`. Gap: the looser spellings rfclib accepts (`rfc 9000`, `section 9.6`, `p3`) and zimlore's `%23` escape are not handled, cvelib's `CVE-YYYY-N§section¶n` (¶ = nth list item) is not among the tested spellings, and no library uses this parser yet |
| `cl.result_text` | PLAN.md §5.1 | `[ok]` | `tests/test_model_render_home.py::test_footer_lines_come_out_in_the_fixed_order_and_empty_ones_are_dropped`, `tests/test_model_render_home.py::test_an_unknown_footer_key_or_a_multiline_value_is_a_bug` |
| `cl.home` | PLAN.md §3 | `[ok]` | `tests/test_model_render_home.py::test_home_prefers_the_variable_then_the_per_user_directory` |
| `cl.atomic_write` | PLAN.md §3 | `[ok]` | `tests/test_model_render_home.py::test_atomic_write_replaces_the_file_and_leaves_no_part_file` |

## 2. Planned

| Obligation | Spec | Status | Where |
|---|---|---|---|
| `cl.bulk_lock` | PLAN.md §3 | `[ ]` | exists in rfclib `fsutil.py` (`O_EXCL` `.write.lock`, taken over after 6 h); zimlore `catalog.py::_acquire_lock` is the same idea for one download |
| `cl.fetch_pinned` | PLAN.md §3 | `[ ]` | digests pinned in code in itulib `sources.py` + `corpus.py`; resumable `.part` under a lock, verified then `os.replace`, in zimlore `catalog.py` (the strongest base); `.part` + disk reserve in cvelib `sync.py`. nistlib `ingest/fetch.py` and usblib record a digest on first fetch and pin none (trust on first use). itulib writes the PDF in place (`path.write_bytes`) |
| `cl.settings_network` | PLAN.md §3 | `[ ]` | rfclib `config.py`: `<PREFIX>_NETWORK` = auto, on-demand, offline, and `require_network()` raising `NetworkDisabled`. No other library has an offline switch |
| `cl.settings_readonly` | PLAN.md §3 | `[ ]` | rfclib PR #1: `RFCLIB_READONLY` / `--read-only` forces offline and opens the index `mode=ro`, so a shared server can run on a read-only volume |
| `cl.reader_pdf_pypdf` | PLAN.md §4 | `[ ]` | exists in itulib `text.py` |
| `cl.reader_pdf_pdftotext` | PLAN.md §4 | `[ ]` | exists in nistlib and usblib `ingest/extract.py` |
| `cl.reader_html` | PLAN.md §4 | `[ ]` | exists in zimlore `markdown.py` |
| `cl.reader_text` | PLAN.md §4 | `[ ]` | exists in rfclib `index/txtseg.py` |
| `cl.reader_zip_stream` | PLAN.md §4 | `[ ]` | exists in usblib `ingest/acquire.py` (unpacks; the core version streams members) |
| `cl.segment_numbered` | PLAN.md §3 | `[ ]` | exists in usblib `ingest/extract.py::split_sections` |
| `cl.segment_bookmarks` | PLAN.md §3 | `[ ]` | exists in itulib `text.py` |
| `cl.index_fts5` | PLAN.md §3, §5.7 | `[ ]` | exists in rfclib `index/search.py` (`bm25(chunks_fts, 3.0, 1.0)`), itulib `index.py` (weights `2.0, 0.0, 15.0, 1.0`, ×0.6 demotion), cvelib `store.py` (external content with triggers, weights `8,1,4,4`); all `porter unicode61`. Column weights and the rank adjustment are per collection |
| `cl.index_readonly_open` | PLAN.md §3 | `[ ]` | prior art: cvelib `store.py` (`?mode=ro` URI, WAL, `busy_timeout=15000`) and rfclib PR #1 (`open_db(read_only=True)` via `mode=ro`, skipping schema setup; `subjects.ensure_schema` checks before writing). itulib's `_open` sets none of these |
| `cl.index_write_txn` | PLAN.md §3 | `[ ]` | rfclib PR #1: `BEGIN IMMEDIATE` around `index_doc`, fixing a `MAX(id)` chunk-id race between concurrent writers; writers also need WAL and a busy timeout |
| `cl.index_schema_version` | PLAN.md §3 | `[ ]` | `PRAGMA user_version` checked on open, refusing with a hint that names the rebuild command. itulib's `SCHEMA` does this through `meta`; cvelib writes `SCHEMA_VERSION` and never reads it; rfclib migrates ad hoc |
| `cl.index_atomic_rebuild` | PLAN.md §3 | `[ ]` | in no library today: itulib unlinks and recreates, rfclib rebuilds in place under the bulk lock. Build into a temporary file, then `os.replace` |
| `cl.search_relaxed` | PLAN.md §3 | `[ ]` | exists in itulib `index.py::search_mode` and cvelib `service.py` (strict AND, then OR with `relaxed`); rfclib has no such flag |
| `cl.fts_query_sanitise` | PLAN.md §3 | `[ ]` | user text quoted term by term so FTS5 operators cannot crash a tool: itulib `text.py::fts_query` (a hyphen read as NOT once raised `OperationalError`), rfclib `_fts_query` (passes raw syntax only when it sees operators, retries quoted on error) |
| `cl.next_is_a_ref` | PLAN.md §7 | `[ ]` | a read's `next` is a ref string `read` accepts back, as in rfclib and cvelib's read; itulib and zimlore return an integer `start` |
| `cl.grep_bounded` | PLAN.md §3 | `[ ]` | itulib's `itu_grep` has no timeout |
| `cl.cite_skeleton` | PLAN.md §3 | `[ ]` | exists in rfclib `cite.py` |
| `cl.cli` | PLAN.md §2 | `[ ]` | |
| `cl.mcp_stdio` | PLAN.md §2 | `[ ]` | |
| `cl.mcp_http` | PLAN.md §5.5 | `[ ]` | prior art: rfclib PR #1 (branch `claude/shared-mcp-http-5bcf0e`, not merged): `--transport http`, stateless streamable HTTP with JSON responses on `/mcp`, `--host` plus a DNS-rebinding allow-list (`--allowed-host`) for a non-loopback host, `/healthz`, read-only mode; pinned by that branch's shared-server test module |
| `cl.mcp_error_contract` | PLAN.md §7 | `[ ]` | one shape for every library: rfclib `_run` (ToolError, `isError`), itulib `_fail` and cvelib `CvelibError.as_dict` (`error`/`hint` object as a normal result), zimlore `ZimloreError.as_mcp_dict` (`hint` vs `tool_hint` vs `user_command`) |
| `cl.result_shape_measured` | PLAN.md §5.1, §7 | `[ ]` | tokens of text-with-footer against compact JSON on the same reads, before a second library adopts; three libraries return each shape today |
| `cl.tool_prefix` | PLAN.md §5.4 | `[ ]` | rfclib, nistlib and usblib expose unprefixed `search`, `read`; itulib, zimlore and cvelib use `itu_`, `zim_`, `cve_` |
| `cl.packaging_serving` | PLAN.md §3, §5.5 | `[ ]` | rfclib PR #1: Dockerfile and entrypoint, GHCR push, MCP Registry `server.json` (PyPI and OCI packages) |
| `cl.test_kit` | PLAN.md §3 | `[ ]` | fixture-corpus builder, licence tripwire (itulib's and zimlore's licence tests), ROADMAP row gate (zimlore's roadmap-rows test, which checks every named test exists); this repository has no row gate yet |
| `cl.collection_registry` | PLAN.md §5.8 | `[part]` | `tests/test_registry.py::test_a_registered_collection_loads_by_name`, `tests/test_registry.py::test_builtins_win_over_plugins_and_nothing_is_imported`, `tests/test_registry.py::test_names_and_prefixes_are_checked`. `primarysource/registry.py`: built-ins and the `primarysource.collections` entry-point group. Gap: a `Collection` carries name, prefix, unit and grammar only, with no builders yet, and no collection is registered |
| `cl.missing_extra_hint` | PLAN.md §5.8 | `[ok]` | `tests/test_registry.py::test_a_missing_extra_names_the_install_command`, `tests/test_registry.py::test_an_unknown_collection_lists_the_registered_ones` |
| `cl.multi_collection_server` | PLAN.md §5.8 | `[ ]` | `primarysource mcp --collection a --collection b`: one process, separate databases, prefixed tools |
| `cl.home_per_collection` | PLAN.md §5.8 | `[ ]` | `$PRIMARYSOURCE_HOME/<collection>/`, with the old `<LIB>_HOME`/`<LIB>_DATA` read as a fallback for one release |
| `cl.adopt_nistlib` | PLAN.md §5.8, §6 | `[ ]` | moves in as `primarysource.nist` with its history and tests. Blocked on relicensing Apache-2.0 to MIT (PLAN.md §7) |
| `cl.adopt_usblib` | PLAN.md §5.8, §6 | `[ ]` | moves in as `primarysource.usb`, together with nistlib, sharing one skeleton. Same licence block |
| `cl.adopt_cvelib` | PLAN.md §5.8, §6 | `[ ]` | `D:\code\cvelib`, uncommitted; moves in as `primarysource.cve` if its author agrees |
| `cl.adopt_itulib` | PLAN.md §5.8, §6 | `[ ]` | moves in as `primarysource.itu`, with `pypdf` behind `[itu]` |
| `cl.adopt_zimlore` | PLAN.md §5.8, §6 | `[ ]` | moves in as `primarysource.zim`, with `libzim` behind `[zim]` |
| `cl.adopt_rfclib` | PLAN.md §5.8, §6 | `[ ]` | moves in as `primarysource.rfc`; `rfclib` on PyPI becomes a thin distribution that depends on `primarysource[rfc]` |

## 3. Non-goals

| Obligation | Spec | Status | Where |
|---|---|---|---|
| `cl.ship_a_corpus` | PLAN.md §5.6 | `[no]` | this repository holds no document text; tests use invented text |
| `cl.one_meaning_of_para` | PLAN.md §5.2 | `[no]` | the unit is declared per library instead |
| `cl.embeddings` | PLAN.md §5.7 | `[no]` | keyword search (FTS5 BM25) only, by the owner's instruction (2026-11-12); rfclib keeps `index/embed.py` and `index/hybrid.py` as its own `[semantic]` extra |
| `cl.corpus_specific_parts` | PLAN.md §2 | `[no]` | catalogue crawlers, errata sources, status vocabularies, citation strings, rfclib's subject tree and packs, zimlore's libzim search, cvelib's multi-source merge stay in their libraries |
