# The terms-acknowledgement gate

Recorded 2026-11-15. The gate is used by the `gm` and `can` collections and is meant for `autosar` later. The
code is `primarysource/terms.py`; the tests are `tests/test_terms.py` and the gate tests in `tests/test_gm.py` and
`tests/test_can.py`.

## 1. What it is, and what it is not

A collection that holds a publisher's files serves their text. Whether the owner may do that is the owner's reading
of the publisher's terms. This package cannot check it and does not try:

- **The gate records the owner's assertion. It does not check anyone's licence.** It does not read the publisher's
  terms, does not know whether the owner's copy was lawfully obtained and does not decide what the terms allow.
- Setting the variable is a statement by the person who sets it, not by this package or by whoever installed it.
  No agent, script or test may set a real collection's variable for the owner's files. The tests set it with
  `monkeypatch`, on invented PDFs only.
- No publisher's terms text is shipped here. The collections do not quote the terms; they point the owner at them.

## 2. The variable

Per collection: `PRIMARYSOURCE_<NAME>_ACCEPT_TERMS` (`PRIMARYSOURCE_GM_ACCEPT_TERMS`,
`PRIMARYSOURCE_CAN_ACCEPT_TERMS`). The general `PRIMARYSOURCE_ACCEPT_TERMS` is not read: an assertion about one
publisher's files must not cover another's.

| Value | Meaning |
|---|---|
| `1`, `true`, `yes` (any case) | The owner has read the publisher's terms for the files in this collection's home and accepts them |
| unset, blank, `0`, `false`, `no`, `off` | Not accepted |
| anything else | An error: `PRIMARYSOURCE_GM_ACCEPT_TERMS='maybe' is not a yes or a no`, as `settings.py` does for the network variable. A typo is never read as a quiet "no" |

## 3. What it gates

- **Import.** `primarysource <name> import`, `import_file` and `import_folder` refuse without it. The CLI checks
  before the home folder or its lock exists, so a refused command creates nothing.
- **Every read.** `read`, `outline`, `search`, `cite`, `docs`, the `index` rebuild and the five MCP tools refuse
  without it.
- **A recorded acknowledgement.** An import with the variable set writes into the collection's `install.json`:

  ```json
  "terms_acknowledgement": {
    "variable": "PRIMARYSOURCE_GM_ACCEPT_TERMS",
    "documents": {"17OBDG01-hybrid": "2026-11-15T14:03:22+00:00"}
  }
  ```

  The time is UTC (`datetime.UTC`). Records merge across imports: a document already recorded keeps its first
  timestamp, a new one gets the time of its own import.
- **Serving needs both.** Serving a document needs the variable *and* a recorded acknowledgement for that document.
  An `install.json` or index built outside the gated import, with the variable set, is still refused: the error
  names the document and the import that records one. A search needs a record for every document in the index, so
  one unrecorded document blocks the search of the others rather than being answered silently. An index therefore
  never exists without a recorded assertion.

The refusal is a `LibError`: the message names the variable and the home folder; the hint says to read the
publisher's terms and, if the owner accepts them, to set the variable. A terms URL appears in the hint only when the
collection passes one that was read and checked. `Terms(url=None)` is the default, and both `gm` and `can` pass
`None`: GM's and Bosch's terms pages were not verified, so the error does not point at one.

## 4. Why `iso` is not behind it

The `iso` collection exists, has users, and is described in `docs/iso.md` on a different footing: the owner bought
the PDFs and ISO's own pages describe them as single-user copies. Adding the gate would change behaviour for those
users, because their next `iso search` would refuse until they set a new variable, and their existing `install.json`
has no acknowledgement record, so serving would also refuse. That is a decision for the owner, not a side effect of
adding two collections.

How `iso` could opt in later: give `primarysource/iso/` a `terms.Terms("iso", "ISO")` and call
`terms.require_served` at the top of `library.load`, `library.search` and `library.docs`, and
`terms.require_accepted` and `terms.record_acceptance` in `importer.import_file`. Existing installs would then need
one re-import to record the acknowledgement, and `docs/iso.md` would say so. `iso` could also be rebuilt on
`primarysource/localpdf/` (the gm and can volume) with its designation logic as the spec's naming function; that is
a larger change and is not proposed here.

## 5. Candidate: `autosar`

AUTOSAR's published standards (for example the SOME/IP protocol specification) are public downloads from
autosar.org. AUTOSAR's own copyright and licence terms were not read for this work, so nothing is recorded about what
they allow, and no code exists. If an `autosar` collection is built it would use this gate
(`PRIMARYSOURCE_AUTOSAR_ACCEPT_TERMS`) and, if the owner fetches the files themselves, the local-PDF volume's import.
`ROADMAP.md` carries it as `col.autosar`, status `[ ]`.
