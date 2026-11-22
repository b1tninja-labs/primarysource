# sae: SAE standards from the owner's own PDFs

A local-only volume (the `gm` and `can` model, `docs/terms-gate.md`). Documents live in `$PRIMARYSOURCE_SAE_HOME`
(default `%LOCALAPPDATA%\primarysource\sae`), never in this repository or an image. `primarysource sae import <PDF or
folder>` extracts the text and builds the index; the PDF is not copied. It refuses until
`PRIMARYSOURCE_SAE_ACCEPT_TERMS=1` records the owner's assertion that they have read the terms under which the copies
were obtained and accept them. The gate is a record of that assertion, not a check of anyone's licence. SAE's terms URL
was not verified, so the error names none.

## What is recognised (by file name only; anything else is skipped with a note)

| File | Document | Id | Notes |
|---|---|---|---|
| `J2735_V201603.pdf` | SAE J2735, March 2016 (DSRC message set dictionary), 267 pages, 24 bookmarks, SAE copyright notice | `sae:j2735-201603` | An older edition; SAE has issued later ones (m) |
| `sae.j1979.2002.pdf` | SAE J1979, 2002 | `sae:j1979-2002` | Posted by Public.Resource.Org, CC0-tagged by the uploader on archive.org (`docs/local-source-survey.md` section 5); superseded |

Read 2026-11-15 in the `awesome-vehicle-security-and-safety` clone and judged **not** SAE standards, so not recognised:
- `SAE J1698/Event Data Recorder(SAE J1698).pdf`: an 8-page printout of a doc88.com listing page (dated 2018-11-22),
  not the standard.
- `SAE J2534/SAE J2534 API REFERENCE.pdf`: Drew Technologies' own PassThru API reference (copyright 2003), not the SAE
  J2534 standard.

## Licence posture

SAE standards are sold. The owner has said their company bought the J2735 copy. That is the owner's statement, recorded
by the gate when it is set; it was not verified here, and a company purchase may carry a single-user or internal-use
term that does not allow copies to be shared or published. A copy that sits in a public repository (the clone's origin
is a third-party GitHub repository) is a separate question for the owner and their company. This collection keeps the
copy local to the owner's machine and serves it over stdio.
