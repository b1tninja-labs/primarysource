# Survey of four local source sets (2026-11-15): licence evidence and candidate collections

Asked by the `gattmirror` session on the user's behalf. All four sets live outside every repository and are surveyed,
not imported. Nothing here is document text; the one quotation is under 15 words. Rule applied throughout: **a third-party
repository or file share holding a standard is not an authorised distribution**, so a file is "local-only" unless the
document itself, or the publisher's published terms, grants redistribution. Evidence and the URL it came from are given.
**(m)** = from memory, unverified.

## 1. Verdict in four lines

1. **Only one document in the four sets carries an explicit redistribution grant from its own publisher:** the Bosch
   *CAN Specification 2.0* (1991), whose first pages say the document as a whole may be copied and distributed without
   restrictions, while use of parts in other documents needs Bosch's consent. Nothing else read does.
2. **No set can be an upstream distribution.** The `awesome-vehicle-security-and-safety` repository is MIT-licensed by its
   own author (autoguard), which covers the repository's own text; it cannot license other bodies' PDFs. rusefi's
   documentation is GPL-3.0 for rusEFI's own content, and its own OEM-docs page says the OEM files are not rusEFI content.
3. **The SAE J1979 (2002) file is openly posted and CC0-tagged by its uploader, Public.Resource.Org, not by SAE.** SAE has
   not granted anything that I found. Good enough for local indexing by the owner; not evidence of a permission to mirror.
4. **The `iso` collection already is the right home for the ISO PDFs, but only for copies the owner bought.** Several ISO
   PDFs in these sets are marked as someone else's licensed or purchased copies and must not be imported.

## 2. Set 1: `awesome-vehicle-security-and-safety` (branch `windows-safe`, commit aa45907)

Repository licence (read from `LICENSE`): **MIT, Copyright (c) 2019 autoguard**. It is a link list and a bundle of 135
files, about 70 papers and about 50 protocol PDFs. The MIT grant is the author's, over the author's work. It carries no
rights over the bundled third-party documents. I read each protocol PDF's own first pages (title, copyright line, terms).

| File (under `vehicle protocol/`) | Body | What the file says about itself | Redistribution evidence | Suggested collection |
|---|---|---|---|---|
| `CAN/can20.pdf` CAN Specification 2.0 | Robert Bosch GmbH, 1991 | In-document: the whole may be copied and distributed without restrictions; parts in other documents need consent | **Explicit, in the document** (not re-checked against Bosch's own site; the official page was not found) | `can`: small, safe. Ship the whole file only, unmodified |
| `CAN/can_fd_spec.pdf` CAN FD 1.0 (2012-04-17) | Robert Bosch GmbH, (c) 2011 | Copyright line only; no copy/distribute statement in the first pages | **None found** | Local-only; pair with the CAN 2.0 collection if Bosch's site grants it (unverified) |
| `CAN/CANopen.pdf` (CiA DS-301 era, 122 pp) | CAN in Automation (CiA) | States the specifications may be implemented licence-free | Implementation freedom, **not** a right to redistribute the text | Local-only |
| `CAN/CANopen User Guide.pdf` | A vendor (MAN0900-01) | Vendor manual | None | Skip |
| `FLEXRAY/Flexray-Protocol-Specification-v2.1-Rev-A.pdf` | FlexRay Consortium, 2004-2005 | **A personally registered copy** (the cover names the registrant) with a disclaimer "for the purpose of information only" | None; a registered copy is the registrant's. The registrant's address must not be republished | Local-only; the successor is ISO 17458 (m), paid |
| `LIN/LIN-Spec_2.2.pdf` (194 pp, 2010-12-31) | LIN Consortium | "All distributions are registered" language | None | Local-only; successor is ISO 17987 (m) |
| `MOST/MOSTSpecification_3V0.pdf` (233 pp) | MOST Cooperation, 1999-2008 | "All rights reserved"; licence disclaimer | None | Local-only |
| `SOME_IP/AUTOSAR_PRS_SOMEIPProtocol.pdf` (FO Release 1.3.0, 64 pp) | AUTOSAR | Disclaimer: for information only; AUTOSAR's own copyright document governs | AUTOSAR's published terms (an AUTOSAR copyright document of 2015, per a Release Overview) were not read; the current releases R24-11 and R25-11 are on autosar.org | **Candidate `autosar` collection, fetched from autosar.org by the user** (the `usb`/`nist` model), not mirrored. Terms to read first |
| `ISO 15031/BS ISO 15031-1..6` (2001-2006) | ISO / BSI | `(c) ISO` and `(c) BSI 2005/2006` | **None**: BSI-issued copies of paid standards | **Do not import** unless the owner bought them |
| `ISO 15765-5(ISO-TP)/ISO 15765-1..4`, `ISO14229(UDS)/` (the same four files again, so the UDS folder holds no ISO 14229) | ISO | `(c) ISO 2004` / `2011` | None | Do not import; ISO 15765-2:2004 is also superseded by the 2016 and 2024 editions |
| `ISO11898/ISO 11898-1..5` (2004-2016) | ISO | Some PDFs carry no text layer at all (image scans: 11898-1, -2, -3) | None | Do not import |
| `DSRC/*` IEEE 802.11-2016, 802.11p, 1609.1-.4, `IEEE 802.1Qbv` | IEEE | Footers say "Downloaded ... from IEEE Xplore. Restrictions apply." | **None**: a download for one licensee | Do not import; use the owner's own IEEE files through the existing `ieee802` identification |
| `DSRC/4.0 .../J2735_V201603.pdf` (267 pp) | SAE International, (c) 2016 | SAE copyright | None | Do not import (SAE paid) |
| `SAE J2534/SAE J2534 API REFERENCE.pdf` (83 pp) | Drew Technologies, (c) 2003 | A vendor's PassThru API reference, not the SAE standard | None | Local-only |
| `SAE J1698/Event Data Recorder(SAE J1698).pdf` | SAE | (the filename only; the file could not be opened for text) | None | Do not import |
| `Bluetooth/Bluetooth_5-FINAL.pdf` (25 pp) | Bluetooth SIG marketing | "Bluetooth SIG Proprietary and Confidential" on the cover | None; **not a specification** | Skip |
| `Ethernet/Automotive Ethernet - The Definitive Guide.pdf` (1,628 pp) | Intrepid Control Systems, (c) 2014 | A vendor book | None | Skip |
| `5G/*`, `LTE-V2X*/*`, `TSN/*`, `Deterministic Ethernet/*`, `Broad-R-Reach/*` | Analyst reports, vendor decks, a Wikipedia print | Not standards | None | Skip |
| `paper/*` (about 70 papers) and `Car Hacking Book/*` | Academic papers, conference slides, a handbook (some marked by their authors) | Mixed; each has its own terms | Not assessed per paper | Out of scope as a standards collection; a `papers` volume would need a per-paper licence pass |

## 3. Set 2: `rusefi_documentation` (3,585 files, commit 96fd3d22)

- Repository licence: **GPL-3.0** (the `LICENSE` file, read). It covers rusEFI's own content.
- **Its own `oem-docs-readme.md` says the OEM documentation is not rusEFI content.** So the GPL does not extend to the
  1,856 files under `OEM-Docs/` and `PDFs/`, which are third-party documents committed by contributors.
- Standards found in `PDFs/` (by name; none opened): `ISO 15031-5-2006`, `ISO-15765-2-2004`, `ISO-16750-1..4`,
  `SAE J1979-2002`, `SAE J2716-2016`, `SAE-J2819-TP2.0`, `SAE970297`. These are copies of paid standards in a third-party
  repository: **not an authorised distribution**. The J1979-2002 file is the same document as the Public.Resource.Org one
  in section 5.
- Hardware vendor datasheets and schematics (Hellen/Proteus boards, connectors, sensors): the first-party schematics are
  rusEFI's; the vendor datasheets are not.
- The repository is **GPL documentation about rusEFI itself** (markdown pages, 568 files), which is redistributable under
  GPL-3.0 and would suit a `rusefi` layer collection like `gitdocs` or `pms`, **if** the owner wants rusEFI's wiki indexed.
  It is not a standards source. 143 `.trc` CAN traces and 25 `.logicdata` captures are test data, not text.
- **Not an upstream** for any standard.

## 4. Set 4: GM Mode $06 / diagnostic parameter PDFs (14 files, `D:\Research\volt\GM\`)

Read from the files: the first pages carry no copyright line, no GM statement and no licence (a regular-expression
search over pages 1-3 found none). Content: the 2017 OBD group matrix, per-group Engine, Transmission and Hybrid diagnostic
parameter files (up to 1,887 pages each), and the generic Mode $06 definitions for CAN/GMLAN (36 pp) and Class 2 (16 pp).
`17OBDG03 Transmisson Diagnostics.pdf` and its `(1)` copy are the same size (2,108,557 bytes): a duplicate.

The volt catalogue (`docs/GM-OBD-REFERENCES.md`) says GM hosts them at `https://gsitlc.ext.gm.com/gmspo/mode6/pdf/` for
the aftermarket under the CARB/EPA service-information rules. That is a statement of why GM publishes them, **not a
copyright grant**: public availability under a regulation does not by itself license redistribution (m). I did not read GM's
site terms (an automated fetch of a manufacturer service site is likely gated, and I did not try).
- Suggested collection: **`gm`**, local-only volume, tables-heavy (the parameter files are tabular, 1,000+ pages each).
  The `pdfcorpus` splitter targets numbered clauses, so these need a table-oriented extractor or a per-row index. Check
  free disk first: the sum is 28.5 MB of PDF but the extractions are many times that.

## 5. Set 3: SAE J1979 (2002), `sae.j1979.2002.pdf`

| Fact | Finding | Evidence |
|---|---|---|
| File | 7,980,929 bytes, SHA-256 `83e8544682221c3ddb6b531bfc09ed0f916ef4c52f8fe863a1e6f7a17bb68231` (verified locally) | local file |
| Source | `https://archive.org/download/gov.law.sae.j1979.2002/sae.j1979.2002.pdf`, item `gov.law.sae.j1979.2002`; archive.org's MD5 `f7fe5bd3c80ce918c875f5d22b7cda76` and SHA-1 `198df33c8bf5507d932e94e06deb39fb215cade9` | `https://archive.org/metadata/gov.law.sae.j1979.2002`, read 2026-11-15 |
| Licence tag | **CC0 1.0** (`licenseurl` = creativecommons.org/publicdomain/zero/1.0/), uploader Public.Resource.Org, creator "Society of Automotive Engineers", no `rights` field | the same metadata |
| What it is | The 2002 edition, incorporated by reference into federal regulations (40 CFR 86.1806-05(h)(1)(ii) per the item description). Same document is on `https://law.resource.org/pub/us/cfr/ibr/005/sae.j1979.2002.pdf` | the same metadata; search result |
| Currency | **Superseded.** SAE sells later revisions (a 2017 edition and later; J1979-2 OBDonUDS is at revision 202604). A 2002 edition has no UDS-based OBD. | SAE Mobilus listings found in search |
| Redistribution by SAE | **No grant from SAE found.** CC0 here is the uploader's dedication, resting on the position that a law incorporated by reference is public; SAE's own copyright is not waived by that. I did not find SAE's response | not found |

Assessment: fine for the owner to index locally; a CC0 uploader tag is **weak evidence** and I would not distribute it
from this repository. As an upstream for a `sae` collection it is **one file, one superseded edition**, so its value is
historical (the ELM327 `ATSP`/mode numbering for PIDs `$01..$0A` is stable, but later modes and the CAN addressing details
changed).

## 6. Per-standards-body candidates for new collections

| Body | Items present | Obtainable free from the body? | Suggested collection | Priority |
|---|---|---|---|---|
| Bosch | CAN 2.0, CAN FD 1.0 | CAN 2.0: whole-document copy permitted in the document; the official URL not confirmed | `can` | Medium: tiny, clean |
| AUTOSAR | SOME/IP PRS (old FO R1.3.0); current R24-11/R25-11 on `autosar.org/fileadmin/standards/` | Public downloads; terms not read | `autosar` (fetch per user) | Medium, if the owner works on SOME/IP |
| SAE | J1979-2002, J2735, J2534 vendor doc | No; paid. Public.Resource.Org tag only | `sae` via the `iso`-style personal import | Medium: **add SAE covers to `identify`** |
| ISO | 15031, 15765, 11898 (BSI copies) | Paid | the existing `iso` import, the owner's own purchased PDFs only | Done as a mechanism |
| IEEE | 802.11, 802.1Qbv, 1609 | Paid; IEEE GET Program for some 802 (m) | the existing `ieee802` identify rule | Existing |
| CiA, LIN, MOST, FlexRay | specs | Consortium sites (m), terms not read | none | Low |
| GM | Mode $06 and parameter files | GM service site | `gm` local volume | Open task (volt) |
| rusEFI | GPL wiki | Yes (GPL-3.0) | `rusefi` layer | Low; not a standard |

## 7. Answers to the three questions

**(a) The `iso` collection.** `docs/iso.md` already describes the import of the owner's own PDFs. Among these files,
only copies the owner **bought** belong there. The BSI-stamped 15031 files, the 15765 and 11898 files, and the rusefi
copies are not. `primarysource identify <folder>` can name each PDF's designation and refuse the foreign ones, which
is a safe first step that copies nothing.

**(b) Further collections.** In order: `identify` rules for SAE and Bosch covers (cheap), a `can` collection from the
Bosch CAN 2.0 file (the one with an in-document grant), an `autosar` collection fetched from autosar.org after reading its
terms, a `gm` local volume. Papers and vendor books are out of scope.

**(c) Upstream distribution.** **No.** None of the four sets has explicit publisher permission, except the whole-document
grant in the Bosch CAN 2.0 PDF itself. Treat the rest as local-only.

## 8. Not verified

- Bosch's own page and terms for CAN 2.0 and CAN FD; the in-document grant was read, not the site.
- AUTOSAR's current copyright and licence terms; CiA, LIN, MOST and FlexRay consortium terms.
- GM's site terms; whether `gsitlc.ext.gm.com` is reachable.
- SAE's position on the Public.Resource.Org posting; whether J1979 was published later under a different licence.
- The contents of the rusefi `PDFs/` and `OEM-Docs/` files beyond their names; the licences of the `paper/*` PDFs.
- Whether the three image-only ISO 11898 PDFs have an extractable text layer; the SAE J1698 file did not open for text.
- Disk space: not measured here; the 1.1 GB figure on the worktree volume was the peer's.
