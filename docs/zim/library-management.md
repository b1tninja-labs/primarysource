# Design: managing the library (add, fetch, cache, sync, remove) for agents that need official docs

Status: **design, 2026-11-07. Steps 1, 2 and 3 of section 5 are built**, and step 4 in part (`sync --update`; no standalone `update` command, no `zim_install`). Built: sidecars, `verify`, `remove`, `prune`, `du` (ROADMAP `zl.lib_provenance`); the catalogue snapshot, `available`, `zim_available`, `obtainable` (`zl.lib_catalog_snapshot`); `add`, `sync` with manifest and groups, resumable locked downloads (`zl.lib_add`, `zl.lib_resume`, `zl.lib_sync`, `zl.lib_groups`). Written to be read before any
code is added to `catalog.py`, `library.py` or the CLI. ROADMAP rows are in section "Future" (`zl.lib_*`).

## 1. What exists

`zimlore catalog <q>` searches the public Kiwix OPDS feed; `zimlore get <name>` downloads the newest edition into
`$ZIMLORE_HOME/zim`, verified against the `.meta4` SHA-256; `zimlore outdated` compares installed dates with the
catalogue; `zimlore list|resolve|info` read what is installed. Editions coexist (the file name carries the date),
so replacing one never needs to overwrite an open file. Missing-library errors already name `zimlore get`.
**Absent:** removing, adding a local file, any record of where a file came from, updating, a declarative set of
libraries, cleanup of old editions, disk accounting, resumable downloads, and any way for an agent to ask "is this
obtainable?" without the network.

## 2. Principles (what an agent seeking official documentation needs)

1. **Provenance is data, not trust.** Every installed ZIM gets a sidecar `<file>.zimlore.json`: source URL,
   catalogue name and date, SHA-256 and size as verified, fetched-at, and who added it (`get`, `add`, `sync`). A
   file with no sidecar is reported as `provenance: unknown`, never as official.
2. **"Official" is a claim to qualify, not to make.** Kiwix's DevDocs ZIMs are a third party's scrape of each
   project's documentation (publisher `openZIM`, creator `DevDocs`); only the project itself publishes official
   docs. `resolve` should report `origin` as one of `project-built` (the project shipped the ZIM or the HTML we
   built from), `scraped-from-official-site` (what DevDocs/Kiwix do) or `community`, from sidecar facts plus the
   ZIM's `Creator`/`Publisher`/`Source`, and say which it could not determine. Never infer "official" from a name.
3. **The MCP server stays offline.** Network lives in `catalog.py` only. An agent can *learn* what is obtainable
   without a network and *ask the human* to obtain it; whether an agent may install is a separate, off-by-default
   switch (section 4).
4. **Every state has a command.** Missing, stale, unverified, corrupt: each error names the exact command that fixes
   it (the existing rule, extended to the new states).
5. **Reproducible and shareable without content.** A project can declare the documentation it relies on in a file
   that names ZIMs (and, later, purls) but contains none, so a clone plus `zimlore sync` rebuilds the same library.

## 3. CLI surface (proposed)

| Command | Does | Notes |
|---|---|---|
| `zimlore add <path\|url>` | install a local ZIM (copy or link) or a URL | libzim opens it first (`Archive.check()` for integrity), sidecar records `added: local`, size, SHA-256 computed locally; a URL needs `--sha256` or a `.meta4`, never trusted blind |
| `zimlore remove <name> [--edition DATE] [--all]` | delete editions | refuses while a handle may be open on Windows (names the file to delete by hand), removes the sidecar; shows bytes freed |
| `zimlore update [name...]` | fetch newer editions | stages as `.part`, verifies, renames to the new dated name, keeps the previous edition unless `--prune`; atomic: the old file is never touched |
| `zimlore sync [--manifest FILE] [--starter]` | make installed match a manifest | installs missing, updates stale per policy, reports extras; `--dry-run` prints the plan and total download size first |
| `zimlore prune [--keep N]` | drop old editions and stray `.part` files | default keeps the newest 2 |
| `zimlore verify [name]` | re-check files against their sidecar hash and libzim's own checksum | for "has this file changed since I installed it" |
| `zimlore du` | disk use per library and total | with `--budget 2GB` a warning when a sync would exceed it |
| `zimlore catalog --refresh` / `--offline` | refresh or read the cached catalogue snapshot | see below |

**Cached catalogue snapshot.** `catalog --refresh` stores the English OPDS index (about 1.5 MB, 1,309 entries on
2026-11-07) as `$ZIMLORE_HOME/catalog.json` with its fetch time. Everything that suggests a download ("not
installed; `zimlore get devdocs_en_flask`, 0.6 MB") can then work with no network, and is labelled with the
snapshot's age. Without a snapshot the error says to run `catalog --refresh` once.

**Manifest.** `$ZIMLORE_HOME/libraries.toml` (global) and an optional `.zimlore.toml` at a project root:
`libraries = ["devdocs_en_python", "devdocs_en_rust"]`, `groups = ["languages", "web-testing"]`, `max_age_days`,
`budget`. Groups are named sets shipped in the package (the starter sets proposed earlier), listing ZIM names only.
Later, `purls = ["pkg:pypi/flask@3.1.0"]` once the producer exists (`future-docs-by-purl.md`).

**Robustness the downloader still lacks:** resumable downloads (HTTP Range onto the `.part`), a mirror failure
retry, a download size cap taken from the `.meta4` before the first byte, and a lock file so two `get`s cannot
write one `.part`.

## 4. What an agent may do over MCP

Today: read-only tools. Proposed, all returning the usual `{"error","hint"}` objects:

- `zim_available(query)`: **offline** search of the cached catalogue snapshot, returning name, title, date, size
  and the exact install command. This is the main gain: when `zim_resolve` fails, the agent can tell the user
  what to install instead of guessing.
- `zim_resolve` miss: includes `obtainable: [...]` from the snapshot, so one call is enough.
- `zim_install(name)`: **disabled unless `ZIMLORE_ALLOW_INSTALL=1`**. It downloads (hash-verified, size-capped,
  `kiwix.org` hosts only, budget-checked) and returns the new ref. Off by default because it spends the user's
  network and disk and writes outside the project at an agent's initiative; when off it returns the CLI command to
  hand to the user. Likewise `zim_remove` is **not** offered to agents at all.
- Staleness stays in every response; add `provenance` to `zim_resolve`/`zim_cite` so a citation can say "scraped
  by DevDocs from the project's site, ZIM 2026-10-01, SHA-256 abcd...".

## 5. Order of work

1. Sidecar provenance + `verify` + `remove` + `prune` + `du` (small, no new network behaviour).
2. Catalogue snapshot + `zim_available` + `obtainable` in resolve misses (the agent-facing win).
3. `add` for local files and `sync` with manifest and groups; resumable downloads.
4. `update` and the opt-in `zim_install`.
Each step gets tests against a local HTTP server and synthetic ZIMs, as `catalog.py` does today, and a ROADMAP row
only turns `[ok]` after a mutation check.

> **Update 2026-11-07:** question 4 below (is `zim_install` acceptable) is superseded by `docs/on-demand-docs.md`: the maintainer
> described an on-demand mode that looks up a purl, checks upstream for official docs in a supported format, or
> generates them in a container task. Installing from the catalogue stays a human CLI action.

## 6. Open questions (the maintainer's)

- Link or copy on `add`? Copy is safe on Windows (no dangling links, no locks on the original); link saves
  gigabytes for a Stack Overflow ZIM. Recommendation: copy by default, `--link` explicitly.
- Should groups ship in the package (a curated starter set is an editorial decision) or only be user-defined?
  *Built provisionally:* `zimlore/groups.py` ships `languages-core`, `web-testing` and `infra` (catalogue names only,
  sizes measured 2026-11-07: about 52, 29 and 42 MB). Marked `EDITORIAL_DEFAULT = True` in code; the membership
  awaits this decision and deleting the module loses nothing but the `--group` shorthand.
- Manifest semantics chosen while building `sync` (also open to the maintainer): `budget` caps the library's total
  size on disk after the sync (installed plus the catalogue's approximate sizes), `max_age_days` only flags old
  editions (`--update` is still what fetches), and `--group` adds to whatever manifest was found.
- May the manifest be committed to a project repo? Recommendation yes (names only); it must never name URLs that
  execute anything, only catalogue names or purls.
- Is `zim_install` acceptable at all? It is the one place an agent's initiative changes the machine; the design
  keeps it behind an environment variable the user must set.

## 7. Deleting and downloading: the rules as built (after the independent review)

These changed behaviour; each has a regression test in `tests/test_manage_safety.py` or
`tests/test_catalog_hardening.py`.

**Editions.** An edition is a ZIM `uuid`. Copies of one uuid in two directories are one edition (a `prune` keep count
counts them once, and deleting that edition deletes every copy). Editions are ordered by the *parsed* `Date`
(`library.parse_date`: `2026-9-15` is September 15th); text is never compared. Two different uuids sharing a Name and
Date are an ambiguity: `remove --edition DATE` refuses and lists the candidates (use `--edition UUID`), `prune` refuses
the library.

**`prune`.**
- Refuses, per library and with the reason under `refused`, when any edition has a `Date` that does not parse, when two
  editions tie, or when an edition it would *keep* fails verification (libzim's checksum, the sidecar size and
  SHA-256, or nothing can vouch for it). The older edition may be the only good copy. Exit 1 under `--yes`.
- Deletes only zimlore-installed files: a sidecar saying `added_by` get, sync or add. Files with no sidecar (a shared
  Kiwix library) or `adopt` are listed under `skipped` and kept; `--include-unmanaged` deletes them.
- Sweeps only `*.zim.part` and `*.zimlore.json.tmp` regular files in the download directory (every directory with
  `--include-unmanaged`), untouched for ten minutes (`manage.QUIET_SECONDS`), with no `.part.lock`. `du` counts
  partial downloads by the same rule.

**Reporting.** `remove` and `prune` return `deleted` and `failed` lists whatever happens. A file that vanished is
success (`already_gone`); any other `OSError` (Windows: `WinError 32` while a reader holds the file) is recorded with a
hint and the rest still go. Exit code 1 when anything failed. The sidecar is removed before its ZIM and put back if
the ZIM cannot be deleted; a sidecar that cannot be removed stops that delete, so no orphan sidecar is left to be
inherited by a later file of the same name. Handles are released per file (`library.close_path`), and opening a
replaced file drops the handle to its predecessor.

**`verify --adopt`.** The sidecar leaves `catalogue_name`, `catalogue_date` and `fetched_at` empty and sets
`adopted_at`: nothing observed those. Size and SHA-256 come from one open handle. A ZIM with no checksum of its own is
`adopted-unchecked`.

**Downloads.** Every redirect hop is re-checked: https only (plain http only to a local host), never https down to
http, never to a loopback, private or link-local address unless the request began at a local host (host names are not
resolved: a public name pointing at a private address is not caught). The `.meta4` must come from `kiwix.org` and may
only be redirected inside it; only the `.zim` bytes may come from another mirror. A download stops after
`catalog.DOWNLOAD_DEADLINE_SECONDS` (the `.part` resumes), refuses a file larger than the free disk space, and never
writes more than the `.meta4` size. Malformed numbers, truncated bodies and install failures are `ZimloreError`s with a
retry hint. `zimlore get` never replaces an existing file of the same name: identical content (sidecar SHA-256 and size
equal the `.meta4`'s) is a no-op saying so, anything else needs `--replace`, and on Windows a file that is open
elsewhere is reported before anything is downloaded. File names must be plain (no Windows device names), catalogue
text is stripped of control and bidi characters, and `get` and `outdated` page through every catalogue edition and
take the newest by date rather than trusting the feed's order.
