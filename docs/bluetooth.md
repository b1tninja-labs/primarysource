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
- **Not covered:** the HTML editions, the test documents (TS, ICS, IXIT, TCRL), errata and the lists of changes;
  assigned numbers and the GATT supplement are separate documents on the SIG's site, listed there as links rather
  than rows. Tables are `pdftotext -layout` columns, so a wrapped cell is interleaved (see `docs/gm.md` §4).
- **Not run in full.** Only Battery Service was fetched live (2026-11-15, 3 requests). The other 255 adopted
  documents have not been fetched, so how well the splitter does on the Core Specification and on the larger
  profiles is not measured.

## 4. Tests

`tests/test_bluetooth.py`: listing and spec-page parsing, an unparseable listing refused, the cache, selection,
the fetch (pin, no-PDF, unchanged, changed and `--repin`, one failure not stopping the rest), pacing and the host
allow-list, the offline setting, registration and the five prefixed tools. The pages and PDFs are invented and the
transport is a dictionary: no test touches the network.
