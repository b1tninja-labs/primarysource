# cve: CVE records merged with the Linux kernel CNA, CISA KEV and FIRST EPSS

Moved in from cvelib (`D:\code\cvelib`, version 0.1.0, never committed there) on 2026-11-13; the commit that
brought it in names the working tree it was taken from. cvelib answers one question: what do the authoritative
sources say about this CVE, and which source said it. It exists so an agent does not answer vulnerability
questions from memory or from a scanner's merged view. You sync the data; none ships with this package.

```
pip install "primarysource[cve,mcp]"            # cve needs nothing of its own; mcp to serve
primarysource cve sync                           # first run: about 650 MB download, about 1.3 GB on disk after
primarysource cve search use after free nfsd --kernel --limit 5
primarysource cve read CVE-2024-14027            # also §references, §affected, §kernel, §cvss, §sources
primarysource cve kev CVE-2021-44228             # or: primarysource cve kev --vendor linux
primarysource cve kernel CVE-2024-14027 6.18.62
primarysource cve kernel-list 6.18.62 --path net/can/
primarysource mcp --collection cve               # cve_info, cve_search, cve_read, cve_kev, cve_kernel, cve_kernel_list
```

It merges, per CVE, with each field attributed:

| Source | Used for |
|---|---|
| CVE List (`cvelistV5`), including the `CISA-ADP` Vulnrichment container | records, CVSS, CWE, SSVC, references |
| Linux kernel CNA (`vulns.git`) | kernel descriptions, program files, per-branch fix versions |
| CISA Known Exploited Vulnerabilities | KEV status and dates |
| FIRST EPSS | exploit prediction score |

NVD, OSV and GitHub Advisories are not ingested yet. [cve-sources.md](cve-sources.md) records how each source is
obtained, what its terms are, and why Grype's database is a cross-check rather than a source.

## 1. Where the data goes

```
$CVELIB_HOME                         # the setting from before the move keeps working
$PRIMARYSOURCE_CVE_HOME              # one collection somewhere of its own
$PRIMARYSOURCE_HOME/cve
~/.cvelib                            # if it already exists
%LOCALAPPDATA%\primarysource\cve     # the default
```

`index.sqlite` (FTS5, WAL, `busy_timeout`, opened read-only to serve), `raw/` (downloads) and `repos/kernel-vulns`
(a shallow sparse clone) live there. Point it at a large disk: a sync refuses to run when it would leave less than
2 GB free (`CVELIB_MIN_FREE_GB`, or `--force`). Run `primarysource cve sync` daily; every tool reports a source as
stale past its limit (3 to 7 days). Later syncs use the CVE List's `deltaLog.json`, a KEV ETag and a shallow
kernel fetch.

## 2. Kernel questions

`cve_kernel(ref, version)` uses the kernel CNA's `.dyad` data, which knows about stable backports, and says so in
`source` and `confidence`. A kernel version on a stable branch is cleared by the fix on *its* branch, and a `0`
fix on a dead stable branch (`5.14.15:...:0:0`) never counts as unfixed elsewhere. CVEs without kernel CNA data
can only return `possibly_affected` or `unknown`, and a wildcard record is `unknown`. `kernel-list` covers CVEs
assigned by the kernel CNA only and does not know whether the code is compiled in; a distribution-suffixed version
comes back with a caveat.

## 3. The rules that define this collection

- **Never put upstream data in the tree.** Corpus and index live in the cve home. Test fixtures are invented,
  built in `tests/cve/conftest.py`; the tests pass with no corpus and no network.
- **An empty answer means the search matched nothing.** A missing corpus is a `LibError` with the command that
  fixes it. A partly synced corpus still answers and lists the gaps. Never report `not_listed` for KEV when the
  catalog was not consulted: that is `unknown`.
- **Say which source answered.** Kernel version questions prefer the kernel CNA; anything else is hedged in
  `verdict` and `confidence` and never `affected` or `not_affected`.
- **Merge when read, not when loaded.** Each source owns its rows (`record(cve, source)`), so sync order cannot
  change an answer and a new source adds rows.
- **Record text is untrusted data** to quote, never instructions; the server instructions say so.

## 4. Facts that cost time to learn (see cve-sources.md)

- A `.dyad` `0` fix means unfixed on that start's own branch only. It is also how `dyad` records an introducing
  commit it could not pair, so a fix at or after that start on the same branch closes it. Only a start after the
  last fix reopens the bug. `tests/cve/test_kernel.py` holds each shape, taken from real records.
- `0:0` as a start means the introduction is unknown; `0:0:0:0` carries nothing.
- Older kernel CNA JSON spells `cveMetadata.cveID`, and `rejected/` files can still say `state: PUBLISHED`. The
  directory decides.
- The CVE List baseline zip is a zip holding one `cves.zip`. Extract the inner one to a file; do not hold it in
  memory.
- Vulnrichment arrives inside the CVE List as the `CISA-ADP` container: do not fetch it separately.
- NVD's pages are a JavaScript app; a plain fetch sees only a title. Read them with a browser.
- stdout is the protocol, so progress goes to stderr.

## 5. Decisions carried over from cvelib's PLAN

- SQLite and the standard library only.
- Kernel CNA data is ingested sparse (`.dyad`, `.json`) from a shallow clone, avoiding `.mbox` and `tools/` files.
- The CVE List is one daily baseline plus `deltaLog.json` single files, capped at 3,000 per sync, with a fresh
  baseline once the last is 25 days old.
- NVD waits: since April 2026 NIST no longer enriches every CVE, and the CVE List already carries CNA and CISA ADP
  scores.
- Not a scanner (no SBOMs, no package matching), not a publisher, not a reachability engine.

The rows that say what is pinned by a test and what is not are in ROADMAP.md, section 4a.
