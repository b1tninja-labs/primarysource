# gm: GM's own published OBD documents

Recorded 2026-11-15. This document was asked for by the gattmirror and obdhub work, which needs citable primary
sources for the Mode $06 data and the per-group diagnostic parameters of a GM vehicle (the Chevrolet Volt is OBD
Group 1A). It records:
- where the files go;
- the licence posture;
- how the collection cuts and cites them;
- what the extractor cannot do.

```
pip install "primarysource[gm,mcp]"      # pypdf, needed only to import; mcp to serve
primarysource gm import                  # every new or changed PDF in the gm home
primarysource gm import FILE --id my-id  # one file whose name is not recognised
primarysource gm index                   # rebuild the search index from the imported text
primarysource mcp --collection gm        # gm_search, gm_read, gm_outline, gm_info, gm_cite
```

## 1. Where the files go

```
$PRIMARYSOURCE_GM_HOME                   # the owner's setting: D:\Research\volt\GM
$PRIMARYSOURCE_HOME/gm                   # otherwise
%LOCALAPPDATA%\primarysource\gm          # the default
```

- The PDFs go directly in the home, as GM published them, one file per document. The import writes `corpus/`
  beside them: `index.json`, `text/<doc_id>.txt`, `sections.sqlite` and `install.json`.
  `PRIMARYSOURCE_GM_CORPUS` moves just that folder.
- On the owner's machine, `setx PRIMARYSOURCE_GM_HOME D:\Research\volt\GM` makes the existing folder the home.
- The PDF is not copied, and the repository holds no GM text: `.gitignore` refuses `*.pdf` and `AGENTS.md`
  forbids document text in the tree. The tests use invented tables.

## 2. Licence posture

- **Local copies only.** These are GM's own files, published for the aftermarket, but no redistribution terms
  were read for them (nothing was fetched for this collection). So the text is treated as the owner's own copy:
  never in the repository, never in an image layer, never pushed anywhere.
- **Served over stdio** on the owner's machine (`primarysource mcp --collection gm`), or in the owner's own
  container with the home mounted read-only, for example
  `-v D:\Research\volt\GM:/data/gm:ro -e PRIMARYSOURCE_GM_HOME=/data/gm`. The import then needs a writable
  `PRIMARYSOURCE_GM_CORPUS`.
- **Out of scope.** SAE J1979 and ISO 15031-5 are not in the corpus. GMLAN enhanced diagnostics are proprietary
  and not covered by these files.

## 3. Documents and refs

The id comes from the file name (`primarysource/gm/designation.py`). Case is ignored, a browser's ` (1)` suffix is
ignored, and GM's own spelling `Transmisson` is read as `transmission`.

| File | `doc_id` |
| --- | --- |
| `17OBDG01 Hybrid Diagnostics.pdf` (also `02`, and `Engine` or `Transmission` for `03` to `06`) | `17OBDG01-hybrid`, `17OBDG03-engine`, `17OBDG03-transmission` |
| `2017_OBD_GROUP_SUMMARY.pdf` | `2017-group-summary` |
| `GM CAN mode $06 data final_dm.pdf` | `mode6-can` |
| `GM Class2 mode $06 data final_dm.pdf` | `mode6-class2` |

Two files that are byte-identical (the owner's folder holds `17OBDG03 Transmisson Diagnostics.pdf` twice, once as
`(1)`) are imported once and the other is reported as a duplicate. An unrecognised name is refused with `--id`.

Refs: `gm:<doc_id>§<section>`, or `gm:<doc_id>:<first>-<last>` for a line range. The `gm:` prefix is optional.
A citation line is `GM 17OBDG01 Hybrid Diagnostics §P0010`.

The files have no bookmarks and no numbered clauses (measured 2026-11-15: no outline in any of the 14), so the
sections follow the tables (`primarysource/gm/segment.py`):

| Kind | Sections |
| --- | --- |
| Diagnostic parameter files (`17OBDG*`) | a run of pages with the same running title (`ecm-summary-tables-initial-dtcs`, `initial-supporting-table-<name>`), and inside a summary-table run one child per DTC, id `P0010`. A DTC that repeats in one file is `P0010-2`. |
| Mode $06 references | one per monitor heading (`mon-oxygen-sensor-monitor-bank-1-sensor-1`), one child per test row, id `<OBDMID or Test ID>-<TID or Comp ID>` (`01-02`, repeats `01-02-2`), and `footnotes` for the last pages. |
| The group summary | one per page, `p1`, `p2`. |

The text has one line added before each page, `[page N]`. The text is `pdftotext -layout` when that is on PATH, else
`pypdf`'s layout mode.

## 4. What the extractor cannot do

Measured on the owner's 14 files, 2026-11-15:

- **No scanned pages.** Every page of every file has a text layer (`install.json` lists `no_text_pages`, empty for
  all).
- **Tables are text columns, not cells.** A row whose cells wrap is interleaved line by line, and a Mode $06 row's
  description can sit on the line above or below its ids. A section is a range of lines, so read the whole section
  (`gm_read`) rather than one line. A DTC section whose row is broken by the layout can be one line long.
- **Mode $06 monitors.** A monitor heading that wraps over two lines, or has no "Monitor" in it (the misfire
  counter rows `A2-0B` and after), is not a section of its own; its rows sit under the monitor before it.
- **Odd glyphs.** A bullet or a minus sign can come out as a control character or U+FFFD.
- **The summary file** is a vehicle-to-file matrix, kept as pages. The mapping is in the text, not in structure.
- **Not identified.** `primarysource identify` has no hook for gm.

Search ranks sections by BM25 with the heading weighted 4, so a DTC code (`P0010`) finds its section and the
supporting tables that name it.

## 5. Tests

`tests/test_gm.py`: designations, both segmenters and the fallback, the importer (skip, duplicate, unknown name,
corrupt file), the home setting and the command line, the five prefixed tools and the ref prefix. Invented text
only.
