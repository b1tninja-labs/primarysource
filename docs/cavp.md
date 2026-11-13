# cavp: NIST cryptographic test vectors

`primarysource.cavp` serves the authoritative CAVP and ACVP test vectors: CAVP `.rsp` response files and ACVP
JSON vector sets. It is a collection of its own, not part of `nist`, because a vector is not a document: the unit
is a case, and a ref names a set, a group and a case. Prefix `cavp_`. Standard library only (`mcp` to serve).

    primarysource cavp fetch            # download the pinned sources in vectors.toml, verify sha256, import
    primarysource cavp sets
    primarysource cavp read 'nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3'
    primarysource cavp find nist:cavp/ecdsa/SigVer.rsp Qx 87F8...          # hex compared without case or 0x
    primarysource mcp --collection cavp   # cavp_sets, cavp_groups, cavp_read, cavp_find, cavp_cite

Imported sets live in `$PRIMARYSOURCE_HOME/cavp` (else the per-user `primarysource/cavp`) as `index.json` plus
`sets/<id>.json`. No vector data is stored in the repository: tests use invented vectors.

## Refs

    nist:cavp/<family>/<file>[#[<group>][/<case>]]       CAVP, e.g. nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3
    nist:acvp/<set>[#<tgId>[/<tcId>]]                    ACVP, e.g. nist:acvp/ECDSA-SigVer-1.0#1/3

- The set id is the path after `nist:`; for CAVP `<family>/<file>` is a name chosen in `vectors.toml`
  (`ecdsa/SigVer.rsp`, `rsa/SigVer15_186-3.rsp`), for ACVP the vector-set directory name of the
  `usnistgov/ACVP-Server` repository (`ECDSA-SigVer-1.0`). `nist:` is optional on input.
- **CAVP group**: the `[...]` header line(s) of the `.rsp`, written in brackets in the ref, text verbatim without
  the brackets (`P-256,SHA-256`, `mod = 2048`). Consecutive header lines join with `,`. A label that repeats in
  one file is suffixed `~2`, `~3`. The text after the last `/` is the case, so a label may contain `/`.
- **CAVP case**: its `COUNT` when every case of the group has a unique one, else its 1-based position.
- **ACVP**: the group is the `tgId`, the case the `tcId`. `prompt.json` (inputs) and `expectedResults.json`
  (answers) are joined by (tgId, tcId): a case has `fields` (inputs) and `expected` (`expected.testPassed`).
- RSA `SigVer` files put the modulus `n` in a block of its own before the cases that use it. Such a
  context block is merged into every following case of the group, so a case read is self-contained.
- A case read ends with `cite:` (algorithm, mode, group, case, source URL, pinned sha256) and `span:` (hash of the
  exact text).

## Bounds and pins

Source files over 64 MiB, lines over 1 MiB, more than 100,000 groups, 2,000,000 cases, 64 fields in a case or 100
header lines are refused. A zip member is read into memory and never unpacked to disk; JSON that fails to parse
or nests too deeply is refused. Every `vectors.toml` entry pins the sha256 of the downloaded artifact (the zip, or
`prompt.json`; ACVP also pins `expectedResults.json`); an entry without a pin is refused. The set records both
the artifact digest and the member digest. `primarysource cavp pin <file>` prints a digest. ACVP URLs are pinned
to a commit of `usnistgov/ACVP-Server`, never a branch.

## Research (all fetched 2026-11-13)

| Source | Finding |
|---|---|
| CAVP zips per algorithm, e.g. `https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Algorithm-Validation-Program/documents/dss/186-4ecdsatestvectors.zip` (HTTP 200, last-modified 2024-09-29) | Linked from the CAVP pages (`.../cryptographic-algorithm-validation-program/digital-signatures`, `.../secure-hashing`, ...). `.rsp` response files plus `Readme.txt`. The FIPS 186-4 RSA files are in `186-3rsatestvectors.zip` (`SigVer15_186-3.rsp`, `SigVerPSS_186-3.rsp`, `SigVer931_186-3.rsp`). The page notes the RSA examples were updated 2015-05-12 to drop mod 1024 for SigGen. |
| ACVP vectors: `https://github.com/usnistgov/ACVP-Server/tree/master/gen-val/json-files/<set>/` | One directory per algorithm and revision (`ECDSA-SigVer-1.0`, `AES-GCM-1.0`, `Ascon-AEAD128-SP800-232`, ...). Files: `registration.json`, `prompt.json`, `expectedResults.json`, `internalProjection.json`, `validation.json`. `ECDSA-SigVer-1.0` at commit `975de31e` (master, 2026-08-12): 330 groups, 2310 cases. |
| `https://github.com/usnistgov/ACVP-Server` (GitHub licence API: none detected) | The repository has no LICENSE file. It is NIST-authored (see Licence), so the public-domain statement below applies; flag to the owner that GitHub cannot show a licence for it. |

### Licence and placement

NIST's statement, `https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications`
(page updated 2026-11-05): data and works created by NIST employees are, under 17 U.S.C. 105, "not subject to
copyright protection in the United States"; they may be subject to foreign copyright. NIST grants, for any foreign
copyright, a non-exclusive, irrevocable, royalty-free right to publish, modify and distribute, with
acknowledgement of NIST as the source, modified works noting the change, and a disclaimer of warranty (AS IS).
Standard Reference Data (15 U.S.C. 290e) is the exception, and CAVP vectors are not SRD. The credit line this
collection prints (`cavp_cite`, `primarysource.cavp.model.CREDIT`) follows that statement.
`usnistgov/oscal-content` states the same in `LICENSE.md` (public domain in the US, CC0 1.0 worldwide).

**Placement**: NIST-authored works may go in an image layer or be fetched, with the credit line. This collection
fetches (the user's `primarysource cavp fetch`) and stores in the user's home, like the other collections, so
nothing is redistributed by the package. A pre-populated image layer is permitted if wanted; it must carry the
credit line and the pinned digests.

## Proposals for primarysource.nist

For the owner of `primarysource/nist/`, which this work did not touch. Facts first, then the rows.

1. **CSRC publications bulk export.** `https://csrc.nist.gov/publications` links
   `https://csrc.nist.gov/files/pubs/shared/docs/NIST-Cybersecurity-Publications.xlsx` (HTTP 200, 456,692 bytes,
   last-modified 2026-11-12; page text: current draft and final FIPS, SPs, NISTIRs, ITL Bulletins, CSWPs). It is
   an OOXML workbook (stdlib `zipfile` + `xml.etree`, shared strings in the `x:` namespace), 941 rows, columns:
   Stage, Substage, PubID, Series, Publication Number, Title, Citation Date, Release Date, **Supersedes**,
   **SupersededBy**, Keywords, Abstract, Authors, Editors, Topics, Family, DOI, URL, CurrentURL. Stages seen:
   Final 858, Public Draft 83 (substage IPD/2PD/FPD). `SupersededBy` is filled for 2 rows
   (`NIST FIPS 140-2-upd2` -> `NIST FIPS 140-3`, `NIST IR 6859` -> `NIST SP 800-82`). It has **no withdrawn rows**.
   There is no JSON or CSV export and no API. Feeds exist only for drafts open for comment:
   `https://csrc.nist.gov/CSRC/media/feeds/pubs/drafts-open-for-comment.json` (and `.xml`, updated 2026-11-12).
   Withdrawn and obsolete drafts are reachable only through the search listing the current `discover_nist.py`
   scrapes (`.../publications/search?...status-lg=Withdrawn`). Measured in `data/nist-catalog.json`: 911 entries,
   290 Withdrawn, 266 Draft (Obsolete), 45 Draft, 236 in scope, one "superseded by FIPS 140-3".
   - Row `ns.csrc_xlsx`: parse the workbook (stdlib) into the catalogue as a second, bulk source; use it for
     `Supersedes`/`SupersededBy`, DOI, CurrentURL and keywords, and to cross-check the scraped listing's finals.
     Pin by recording the sha256 and `last-modified` of the workbook in the catalogue.
   - Row `ns.status_served`: serve `data/nist-catalog.json`, which today is only read to compute defaults.
     Proposed tool `nist_status(query, status=None, limit=20)` (prefix per `ns.tool_prefix`): match by number
     (`800-53`, `FIPS 140`), return one line per catalogue row: `SP 800-53 Rev. 4 | Withdrawn | 1/22/2015 |
     superseded_by | detail_url`, newest first, then the footer `cite:` with the catalogue's source and fetch date.
     `status` filters (Final, Withdrawn, Draft, `Draft (Obsolete)`). Zero matches is stated, a missing catalogue is
     a `LibError` naming `discover_nist`. The labels: series `SP 800` + number `800-53 Rev. 4` -> `SP 800-53 Rev. 4`;
     FIPS -> `FIPS 140-2`. A bare publication with several rows (revisions, drafts) groups them.
   - Row `ns.superseded_for_withdrawn`: `discover_nist.py` fetches detail pages only for Final candidates, so
     `superseded_by` is empty for all 290 Withdrawn rows. A detail-page pass for withdrawn rows (1 request per
     second, ~290 requests) would fill it; or take it from the workbook where present.
2. **OSCAL.** `usnistgov/oscal-content` latest release v1.6.0 (2026-10-22), single release asset
   `generated-content.zip` (11,715,082 bytes); `main` is commit `f0de6d8d...` (2026-10-22), which is the commit
   `data/sources.toml` already pins for all ten `[[oscal]]` entries. Catalogues are published in three formats
   side by side (`nist.gov/SP800-53/rev5/{json,xml,yaml}/`, plus `-min.json`), under
   `AI100-1, CSF, SP800-171, SP800-172, SP800-218, SP800-53`. Proposal row `ns.oscal_pin_check`: a check that the
   pinned commit is still the repository head and report drift (read-only API call to
   `https://api.github.com/repos/usnistgov/oscal-content/commits/main`), and `ns.oscal_json`: prefer the JSON
   catalogue (stdlib `json`, no namespace handling) over XML when rendering. Not urgent: XML works.
3. **NVD/CPE (brief).** NVD publishes CVE, CPE and CPE-match through the NVD API 2.0 and gzip JSON feeds
   (`nvd.nist.gov/developers`); cvelib covers CVE, so the open rows are the CPE dictionary and CPE-match data only.
   Not fetched in this pass; row `ns.nvd_cpe` as a candidate for a separate `cpe` collection, `[ ]`.
4. **Licence.** The nistlib `pyproject.toml` declared Apache-2.0 for the code, which is the owner's (the move
   settled it). Separately, NIST publications themselves are public domain in the US (statement above), so the
   `nist` collection may hold them in an image layer with NIST's credit line; the fetched-PDF model needs none.

## Rows to add to ROADMAP.md (coordinator)

| Obligation | Status |
|---|---|
| `cv.rsp_parse`: CAVP `.rsp` groups, cases, context blocks, COUNT ids, bounds | `[ok]` `tests/test_cavp_parse.py::test_rsp_groups_cases_header_and_mode`, `::test_rsp_modulus_block_is_context_merged_into_following_cases`, `::test_rsp_bounds` |
| `cv.acvp_parse`: prompt joined with expectedResults, server-response list, mismatch refused | `[ok]` `tests/test_cavp_parse.py::test_acvp_joins_prompt_and_expected_by_group_and_case`, `::test_acvp_refuses_mismatched_or_malformed_files` |
| `cv.ref`: `nist:cavp/...#[group]/case` and `nist:acvp/...#tg/tc` | `[ok]` `tests/test_cavp_parse.py::test_refs_round_trip_and_reject_bad_ones` |
| `cv.pinned`: a wrong or missing sha256 pin is refused; shipped entries are pinned and ACVP URLs name a commit | `[ok]` `tests/test_cavp_serving.py::test_a_wrong_or_missing_pin_is_refused`, `::test_shipped_vectors_toml_pins_every_entry` |
| `cv.bounded_zip`: a zip member is read in memory under a cap | `[ok]` `tests/test_cavp_parse.py::test_zip_member_is_read_in_memory_and_bounded` |
| `cv.tools`: read, find, sets, cite, paging, errors name the remedy | `[ok]` `tests/test_cavp_serving.py::test_read_a_case_in_full_with_cite_and_span`, `::test_find_compares_hex_without_case_and_says_when_nothing_matches`, `::test_errors_name_the_remedy` |
| `cv.mcp`: `cavp_` prefixed read-only tools | `[ok]` `tests/test_cavp_serving.py::test_server_tools_are_prefixed_read_only_and_errors_name_the_remedy` |
| `cv.real_import`: the shipped pins fetch and import | `[part]` imported by hand from downloaded files on 2026-11-13 (ECDSA SigVer 75 groups / 1125 cases; RSA SigVer15, PSS and 931 each 3 groups / 270 cases; ACVP ECDSA-SigVer-1.0 330 groups / 2310 cases); `cavp fetch` over the network is not run in CI |
| `cv.more_sets`: AES, SHA, HMAC, KDF/HKDF, EdDSA, ML-KEM/ML-DSA, DRBG vectors for the portfolio consumers (sigwire[verify], pkix, ohttp, srtpkit, ntspy) | `[ ]` add `[[vector]]` entries with measured pins; ACVP sets for post-quantum algorithms are in `gen-val/json-files` |
| `cv.verify_runner`: a helper that feeds cases to a consumer's verify function and reports per-case results | `[ ]` |
| `cv.acvp_internal`: `internalProjection.json` (inputs and answers, 2.3 MB for ECDSA-SigVer) as an optional source | `[ ]` |
| `cv.expected_reason`: CAVP `Result = F (3 - S changed)` is kept as raw text; a parsed pass/fail and reason | `[ ]` |
| `cv.image_layer`: a pre-populated image layer with the credit line | `[ ]` decision |
| `cv.cavp_catalogue`: CAVP page scrape for the zip list, so new zips are found without hand-editing `vectors.toml` | `[ ]` |

Registry line (BUILTIN in `primarysource/registry.py`): `"cavp": "primarysource.cavp:COLLECTION",`
pyproject extra: `cavp = []` (standard library only; serving needs `mcp`). `vectors.toml` ships as package data
(`primarysource/cavp/data/`, covered by the wheel's `packages = ["primarysource"]`).
