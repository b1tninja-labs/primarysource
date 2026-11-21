# bluetooth: the Bluetooth SIG's specifications

Recorded 2026-11-15, asked for by the owner: a collection covering the specifications listed at
<https://www.bluetooth.com/specifications/specs/>. It records:
- how to fetch and where the files go;
- what the SIG's site allows, as read;
- how the catalogue, the pins and the sections work;
- what is not covered.

```
pip install "primarysource[bluetooth,mcp]"      # pypdf, needed only to import; mcp to serve
primarysource bluetooth catalogue               # the SIG's list, one request
primarysource bluetooth list --search mesh
primarysource bluetooth fetch battery-service   # one or more documents, by slug
primarysource bluetooth fetch --dry-run         # how many and how long
primarysource bluetooth fetch                   # every adopted specification
primarysource bluetooth fetch --status draft    # the drafts
primarysource mcp --collection bluetooth        # bluetooth_search, _read, _outline, _info, _cite
```

## 1. Where the files go

```
$PRIMARYSOURCE_BLUETOOTH_HOME            # one setting for the collection
$PRIMARYSOURCE_HOME/bluetooth            # otherwise
%LOCALAPPDATA%\primarysource\bluetooth   # the default
```

In it: `catalogue.json`, `pins.json`, `pdf/<doc_id>.pdf` and `corpus/` (`index.json`, `text/`, `sections.sqlite`,
`install.json`). `PRIMARYSOURCE_BLUETOOTH_CORPUS` moves only the corpus. None of it is in this repository.

## 2. What the SIG's site says, read 2026-11-15

- **The listing** is server-rendered HTML with 265 rows (256 adopted, 8 draft, 1 approved supplemental document):
  name, revision, type, status, and deprecation and withdrawal dates where there are any. Each row links to a page for
  the document, and that page links the PDF (`bluetooth.org/DocMan/handlers/DownloadDoc.ashx?doc_id=...`, or
  `files.bluetooth.com/download/...`). The request answers `200` with `application/pdf`; no sign-in or click-through
  stood between the page and the file for Battery Service, the one checked.
- **robots.txt** disallows only `/wp-admin/` and sets `Crawl-delay: 10`. The fetcher paces itself at one request
  every 10 seconds, to bluetooth.com, bluetooth.org and files.bluetooth.com only, so `fetch` of every adopted
  specification is about 85 minutes. It resumes: what is imported is skipped, and a failure is reported and the run
  continues.
- **Terms of use** (`/terms-of-use/`): the SIG owns "all draft and adopted specifications", and a non-member gets a
  limited, revocable, non-transferable licence to use the content to evaluate Bluetooth technology. They do not
  mention scraping, redistribution of specifications or machine learning. The copyright policy is only the DMCA
  procedure. The member terms were not read.
- **Locked documents** (functional requirements, new work proposals) need a member login and are not fetched.

So the posture is the owner's own copies: personal volume, never in the repository or an image, served over stdio.
The licence is for evaluating the technology; anyone shipping a product on it should read the SIG's terms for their
own membership.

## 3. How it works

- **Catalogue** (`primarysource/bluetooth/catalogue.py`). `doc_id` is the last part of the document's page address
  (`core-specification-6-3`, `battery-service`, `hands-free-profile-1-10`), so two revisions of one specification are
  two documents. The citation name is `Bluetooth <title> <revision>`. The specification's PDF is the first row of the
  page's table that is not a test suite, ICS, IXIT, test case list, list of changes or erratum. A document with no
  such row (HTML only) is reported `no-pdf`.
- **Status** comes from the listing: `final` for adopted, `draft`, and `deprecated` or `withdrawn` when the listing
  gives such a date, so the tools warn when you read one that is not in force. The listing does not say whether a
  withdrawal date has passed.
- **Pins** (`pins.json`). The sha256 of each PDF as first fetched, trust on first use, because nothing publishes the
  digests beforehand. A later fetch whose bytes differ is refused (`changed`) unless `--repin`, since the SIG
  replaces files in place and a citation should not move silently.
- **Sections** are the PDF's numbered headings (`primarysource/pdfcorpus/split.py`, the splitter nist and usb use),
  so refs are `bluetooth:battery-service§3.2.1.4`. A PDF with no usable headings falls back to a section per page,
  `p1`, `p2`. Measured on Battery Service 1.1: 30 pages, 91 sections.
- **Not covered:** the HTML editions, the test documents (TS, ICS, IXIT, TCRL), errata and the lists of changes.
  Assigned numbers and the GATT supplement are not listing rows; they are added by hand in the catalogue and fetched
  by name (§5). Tables are `pdftotext -layout` columns, so a wrapped cell is interleaved (see `docs/gm.md` §4).
- **A download page in front of the file.** `files.bluetooth.com` answers a download address with a page saying the
  download starts by itself, linking the file with a one-time nonce. It has no terms to accept; the fetcher follows
  that link. The first full run did not, and 76 documents failed with "not a PDF" until it did.
- **Run in full, 2026-11-15.** `fetch` of every adopted specification imported 250 of 256: 48,944 pages and
  42,083 sections, all cut at numbered headings (none fell back to pages), 874 MB with the PDFs. The Core
  Specification 6.1 to 7.0 are about 3,800 pages and 1,800 to 2,000 sections each. The other six: five are HTML
  only (`advanced-audio-distribution-profile-1-2`, `dial-up-networking-profile-1-1`, `gaming-audio-profile-1-0`,
  `generic-object-exchange-profile-1-1`, `rfcomm-1-1`) and `basic-printing-profile-1-2` links a zip, not a PDF.
  The section counts were not checked against the PDFs' own contents pages.

## 4. Tests

`tests/test_bluetooth.py`: listing and spec-page parsing, an unparseable listing refused, the cache, selection,
the fetch (pin, no-PDF, unchanged, changed and `--repin`, one failure not stopping the rest), pacing and the host
allow-list, the offline setting, registration and the five prefixed tools. The pages and PDFs are invented and the
transport is a dictionary: no test touches the network. The supplements are tested the same way: their addresses and
versions, that a supplement is fetched from its PDF address without reading its page, that only the listed clauses
reach the corpus, that a missing clause is refused, and that a heading the splitter misses is found by its exact line
(`test_a_heading_the_splitter_misses_is_found_by_its_exact_line_and_a_contents_row_is_not`).

## 5. The GATT Specification Supplement and Assigned Numbers

Both are on the SIG's site as "Supplemental Document" pages, not as rows of the listing, so the catalogue adds them
by hand (`SUPPLEMENTS` in `primarysource/bluetooth/catalogue.py`). Read 2026-11-21.

| Document | Name in the collection | SIG page | PDF (fetched from) | Version date | Pages |
|---|---|---|---|---|---|
| GATT Specification Supplement (GSS) | `gatt-specification-supplement` | `https://www.bluetooth.com/specifications/gss/` | `https://btprodspecificationrefs.blob.core.windows.net/gatt-specification-supplement/GATT_Specification_Supplement.pdf` | 2026-09-09 | 207 |
| Assigned Numbers | `assigned-numbers` | `https://www.bluetooth.com/specifications/assigned-numbers/` | `https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Assigned_Numbers/out/en/Assigned_Numbers.pdf` | 2026-11-16 | 447 |

- **GSS** is the SIG's abbreviation for the GATT Specification Supplement. The Core Specification Supplement is a
  different document and is not in this collection. The GSS PDF is on the SIG's own storage account, which the SIG's
  page links; the fetch allow-list admits that one host and no other.
- **Pins.** `pins.json` holds the sha256 of each PDF as first fetched (trust on first use): the GSS
  `34ad6b5f…9150b8`, Assigned Numbers `c2c873c8…bf106`, both pinned 2026-11-21. Each PDF's front page carries the
  version date above; the SIG's pages give no status word, so the collection records `published`, and the tools warn
  on it like any non-final status.
- **Licence.** Both PDFs are marked "Bluetooth SIG Proprietary", and the same non-member evaluation terms as §2 apply.
  Stored only on the owner's volume, never in this repository.
- **Fetch.** `primarysource bluetooth catalogue`, then `primarysource bluetooth fetch gatt-specification-supplement
  assigned-numbers`. A plain `fetch` takes only `adopted` documents, so these two are not fetched by it.

### What is kept

The whole PDF is downloaded and pinned, but only the clauses below reach `text/` and the index. A listed clause
keeps its own text and its subsections. Everything else is read past, not indexed. Medical, health, bio and
body-sensor clauses are not listed, and `install.json` records how many sections were left out.

- **GSS, kept (10 sections):** 1 Introduction; 2.1 Data Types (2.1.1 Special medfloat32 and medfloat16 values);
  2.2 Units; 2.3 Values and represented values (2.3.1, 2.3.2); 2.4 Representation of multi-field characteristics or
  descriptors; 4 Descriptors; 4.1 Valid Range. **Left out:** §2 intro, §2.5 CRC calculation, all of §3 Characteristics
  (a catalogue of sensor and measurement characteristics, none needed for the bridge) and §5 References.
- **Assigned Numbers, kept (17 sections):** 1 Introduction; 2.3 Common Data Types; 2.4 Characteristic Presentation
  Format (2.4.1 GATT Format Types, 2.4.2 GATT Characteristic Presentation Format Name Space, 2.4.2.1 Bluetooth SIG GATT
  Characteristic Presentation Format Description); 2.5 PSMs and SPSMs; 2.6.1 Definition; 2.9 LE-U CID; 3.4 GATT
  Services (3.4.1 Services by Name, 3.4.2 Services by UUID); 3.6 Declarations; 3.7 Descriptors; 3.8 Characteristics
  (3.8.1 Characteristics by Name, 3.8.2 Characteristics by UUID). **Left out:** §2.1, §2.2, §2.6.2 and §2.6.3
  (appearance category ranges), §2.7 to §2.8 and §2.10 to §2.13 (classic Class of Device, HCI codec, MWS, AMP),
  §3.1 to §3.3 and §3.5 and §3.9 to §3.12 (SDP, units, object types, SDO and member services), §4 Mesh, §5 Service
  Discovery, §6 Profiles and Services, §7 Company Identifiers and §8 References.
- **Judgment on the identifier tables.** §3.4, §3.6 to §3.8 are single clauses that list every SIG service,
  characteristic and descriptor by identifier, so their rows for medical and health services come with them as
  identifiers only. No health or medical profile clause, and no text of one, is kept. Filtering the rows out would
  mean editing a table, which this cut does not do.
- **Located headings.** The PDF has no heading for chapter 3, and the splitter in `pdfcorpus/split.py` accepts a
  numbered heading only under a parent it has already seen. So it finds none of 3.4, 3.6, 3.7 or 3.8, though it does
  find their subsections. Those four are located by their exact heading line (`AN_LOCATED`). A contents row is not
  matched, since it has leaders and a page number. The splitter itself is unchanged.
- **Where the clauses do not match this document's content.** AN §2.9 "LE-U CID" lists only the reserved range
  `0x0020` to `0x003E`; the fixed LE channels (ATT, LE signalling) are not in this clause. The clause's own reference
  points to Core Specification Vol 3 Part A §2.1. Neither supplement names a serial or UART GATT service: the
  bridge's UART service is vendor-defined and is not covered here.
