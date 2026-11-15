# IEC webstore client

`primarysource.iec.webstore` is a client for <https://webstore.iec.ch> built from one browser capture (a HAR of
1931 entries, 2026-11). It searches the catalogue, reads catalogue and price metadata, lists what the owner has
bought, downloads what the owner owns, and can add to the cart and place a **zero-total** order, each only on an
explicit confirmation. Stdlib only.

Everything below is "as observed in the capture" unless it says **unobserved**. The capture belongs to one owner's
live session; nothing from it that identifies a person (cookies, form keys, tokens, name, address, e-mail, ids of
customers, carts or orders) is in this repository, its tests or this document. Tests use invented designations,
titles, prices and ids in the observed response shapes, through a fake transport.

## What this is not

- **It does not read a standard's text from an online reader**, and it does not extract text from anything. A
  download is the owner's own purchased file, saved as bytes.
- **It does not crawl the store.** A catalogue sync is opt-in, bounded and slow (see Terms).
- It does not create accounts, change addresses, or pay. Those are documented below and not implemented.
- It does not solve or bypass a CAPTCHA.

## Terms (read before a sync)

The capture holds no IEC terms text: the footer links `https://webstore.iec.ch/en/terms-conditions/` and
`/en/privacy/`, and neither page was in the capture. **IEC's position on automated access, scraping and
text-and-data mining is therefore unverified.** `docs/iso.md` section 3 records that ISO's terms forbid scraping,
harvesting, text and data mining and use in AI systems, and opts out of the statutory TDM exceptions; IEC and ISO
share standards and a joint committee but have separate stores, so do not assume either way. Read the terms page
in a browser before running a sync, and sync only a slice (a committee, a type), not the 17 000 entries.

The code enforces what can be enforced: `sync_catalog` refuses unless `opt_in=True` (CLI: `--i-have-read-the-terms`),
refuses more than 20 pages per run, honours `primarysource.settings` (`PRIMARYSOURCE_IEC_NETWORK=offline` or a
read-only process refuses before a request), and the polite transport sends one request per second with a generic
User-Agent (`primarysource-iec-client (+https://github.com/b1tninja-labs/primarysource)`, no personal data).

## Hosts in the capture

| Host | What it was |
| --- | --- |
| `webstore.iec.ch` | The shop: Magento 2 with the Hyva theme (Alpine.js), store code `en` (`/en/...`). |
| `webstore-search-api.iec.ch` | The catalogue search API the shop's JavaScript calls. Public, no cookie. |
| `storage-watermark-prd-iec-ch.s3.<region>.amazonaws.com` | Where a download link points: a pre-signed S3 URL. |
| `www.iso.org`, `standards.iso.org`, `web.archive.org` | ISO pages the owner also visited (committee and standard pages, the closed ITTF "publicly available standards" list). Out of scope here; see the ISO store. |
| `ruby.ops.iec.ch`, `iso.matomo.cloud`, `plausible.io`, Google, New Relic, usercentrics, Cloudflare | Analytics and consent. Not used. |

## Catalogue: search and categories

`POST https://webstore-search-api.iec.ch/api/search`, `Content-Type: application/json`. Header names the browser
sent: `accept`, `content-type`, `origin`, `referer`, `user-agent`, plus fetch metadata. **No `cookie` or
`authorization`**: it is public. The answer has `access-control-allow-origin: *` and is gzip JSON. An `OPTIONS`
preflight precedes it.

Request body (keys as sent; the client sends the same):

```
{"mode": "FULL", "query": "", "from": 0, "size": 100, "validOnly": true,
 "sortBy": [{"reference": "asc"}], "language": "en", "dateRanges": {},
 "terms": {"<facet>": {"1": ["<value>", ...]}}, "publicationIds": null,
 "showTrf": true, "collapsed": true}
```

- `from` / `size` page the results; the page's size menu is 10, 25, 50, 100 (the client caps at 100).
- `terms` is facet name, then tree level (`"1"`), then values. Seen: `header` = `ISO/IEC`, `ISO/IEC/IEEE`;
  `committee` = `ISO/IEC JTC 1`. The shop page puts the same filter, base64 JSON, in `/en/products/?p=<page>&f=...`.
- `collapsed` is what the page sends in list mode (it folds editions of one reference group together).
- `validOnly` hides withdrawn publications; `showTrf` includes test-report forms (IECEE); both seen `true`.

Answer: `{"primary": {...}, "secondary": {...}}`, each `{"hits": {"total": {"value": n}, "hits": [...]},
"aggregations": {...}}`. **`primary` is the unfiltered set, `secondary` the set the `terms` select** (with a committee
filter the two totals were 17653 and 3356). The storefront's list, and the client, use `secondary`.

Each hit's `_source` carries the metadata the client models (`primarysource/iec/webstore/models.py`):

| Field | Meaning |
| --- | --- |
| `id`, `urn` | Publication id (the `/en/publication/<id>` page) and `iec:pub:<id>`. |
| `reference`, `reference_object` | The designation (`... 12345-1:2099`) and its parts (`head`, `num`, `part`, `amendment`, `corrigendum`, `version`). |
| `title`, `edition`, `status`, `publication_date` | Edition is `"7"` or `"1.0"`; seen status `PUBLISHED`; date `YYYY-MM-DD`. |
| `publication_type` | `STANDARD`, `PUBLICATION`, `CONSOLIDATED`, `REDLINE`, `COMMENTED`, `EXTENDED`, `PRERELEASE`, `SERIES`, ... |
| `price` | `{amount, currency}`; `amount: 0` is a free item. Currency seen: `CHF`. |
| `committee` | `level_1`/`level_2` (`TC 86`, `SC 86A`) with `_details` names. |
| `ics`, `classifications` | ICS codes at three levels with titles; `classifications` lists `{type: "ICS", value}`. |
| `available_formats`, `available_files` | `PDF`, `XML`, `DOC`, `TRF`; per file `{format, language, type, hasFullPdf, ...}`; language may be `en/fr`. |
| `pdf_pages`, `isbn`, `artNum`, `deliverables` | Page count, ISBN, article number, file locations and `lastupdate`. |
| `lifecycle`, `related_pubs`, `referenced_by` | Earlier editions with `status` (`REVISED`...), related and citing publications. |
| `abstract`, `preview_languages` | The catalogue blurb. See "Public content" below. |

Facets (`aggregations["buckets#<name>"]`, nested `buckets` of `{key, doc_count, nested}` for each tree level):
`header` (IEC, ISO/IEC, IECEE, ISO, IECEx, ISO/IEC/IEEE ...), `committee` (131 values in one answer), `ics` (36
top-level fields), `type` (`IS`, `TRF`, `TR`, `TS`, `GUIDE`, `SRD`, ...), `publication_type`, `vap_type`,
`available_formats`, `status`. **Language is not a facet**: the request has a `language` field instead.

**Unobserved:** a non-empty `query` (every captured search was empty, so text-search behaviour is unverified; the
client passes `text` through); the `dateRanges` value format (the page's JavaScript reads
`dateRanges.publication_date.{min,max}`, formats unknown); the `GET /api/publications/autocomplete?query=&mode=
PUBLICATION&language=&validOnly=&showTrf=` answer (the call is in the page's JavaScript only); facet levels beyond
`"1"`; what `inner_hits.collapsed` holds when more than one edition is folded.

### Public content: TOC, preview, abstract

The only public descriptive text is the catalogue `abstract` in each hit (a few sentences, IEC's own words). The
publication page carries an "Edition / ICS / Pages / File size" table, a lifecycle tab and a referenced-by tab. **No
table of contents and no preview was in any response**, although `preview_languages` is listed per hit (the preview
itself is unobserved). Owner decision, 2026-11-14: the sync collects catalogue metadata only, never a standard's text, and the abstract
is part of that metadata, so stubs and index keep it (`--no-abstract` / `include_abstract=False` drops it).

## Account and login

Not a token flow. The browser makes a `form_key` cookie itself (the Hyva helper `getFormKey` stores 16 characters of
`0-9a-zA-Z`) and sends it as `formKey` / `form_key`. Login (read from the page's JavaScript; **the capture holds no
login request**, only an account creation):

`POST /en/customer/ajax/login/`, JSON `{username, password, formKey}` (plus `g-recaptcha-response` if the page has
that field), headers `Content-Type: application/json` and `X-Requested-With: XMLHttpRequest`. On failure the answer
has `errors` and `message`. After login the **session cookie is the credential**; REST calls under `/en/rest/` use
the same cookie plus `X-Requested-With`. `GET /en/customer/section/load/?sections=` returns every private-content
section as JSON: `customer` (name fields only when logged in), `cart` (`cartId`, `summary_count`, `items[]` with
`item_id`, `product_id`, `product_sku`, `product_name`, `product_price_value`, `options[]`), `messages`,
`directory-data`, `compare-products`, `last-ordered-items`.

Set-Cookie headers are not in the capture, so the session cookie's name is unobserved; the client never needs it by
name (the transport's cookie jar carries it).

Credentials: **only** the environment, never an argument or a file in a repository.

| Variable | Use |
| --- | --- |
| `PRIMARYSOURCE_IEC_USERNAME` | The shop login. |
| `PRIMARYSOURCE_IEC_PASSWORD` | The shop password. |
| `PRIMARYSOURCE_IEC_SESSION_FILE` | Optional cookie jar (LWP format) outside any repository; written `0600` after a login, reused to skip it. |
| `PRIMARYSOURCE_IEC_HOME` / `PRIMARYSOURCE_HOME` | Where the catalogue lives (`<home>/webstore`). |
| `PRIMARYSOURCE_IEC_NETWORK` | `offline` refuses every request (the settings module). |

Both are held as `Secret`, whose `repr`, `str` and format are `<redacted>`; a failed login's message and hint never
repeat the store's message or the credentials. If the store wants a CAPTCHA the client stops and says to log in in a
browser and pass the session file.

**Account creation** (`GET /en/customer/account/create/`, then `POST /en/customer/account/createpost/`, a form post
that answers 302 to `/en/customer/account/`), address-book and payment-method changes: observed or implied, **not
implemented** by design.

## Cart and the free order

All guarded in `cart.py`: a call with no `Confirmation` is a dry run and makes no state-changing request.

1. `GET /en/publication/<id>`: the form `product_addtocart_form`, `action=/en/checkout/cart/add/uenc/<b64 of the page
   URL>/product/<productId>/` (the Magento product id differs from the publication id). Hidden `product`,
   `selected_configurable_option`, `related_product`, `item`, `form_key`; selects `options[publication_language]`
   (e.g. `13` English, `16` French), `options[publication_format]` (`37` Electronic, `46` Hardcopy) and
   `options[license_price]`, the number of users (`2` is "1", then `2 - 3`, `4 - 5`, `6 - 10`, `11 - 15`, `16 - 20`).
   The head has `og:title` (the designation) and `product:price:amount` / `currency`. Option ids are the page's; the
   client matches by label.
2. `POST` that action, `multipart/form-data` with those fields and `qty=1`. Answer 302 to the publication page.
3. `GET /en/rest/en/V1/carts/mine/totals`: `grand_total`, `subtotal`, `tax_amount`, `shipping_amount`,
   `base_currency_code`, `quote_currency_code`, `items_qty`, `items[]`, `total_segments`. A free item totals 0.
4. `POST /en/rest/en/V1/carts/mine/set-payment-information` `{cartId, paymentMethod: {method: "free"}}` answers `true`.
   The methods offered were `free` ("No payment / Corporate account"), `datatrans_credit_debit_cards`,
   `datatrans_paypal`, `banktransfer`. Only `free` is used.
5. `POST /en/rest/en/V1/carts/mine/billing-address` `{cartId, address: {countryId, regionId, regionCode, region,
   street[], telephone, postcode, city, firstname, lastname, saveInAddressBook}}` answers the address id (string).
   The capture also shows `POST .../estimate-shipping-methods {address: {country_id, postcode}}` answering `[]` and
   `GET .../payment-information` (payment methods plus totals); neither is needed.
6. `POST /en/rest/en/V1/carts/mine/payment-information` `{cartId, billingAddress, paymentMethod: {method: "free",
   po_number, additional_data, extension_attributes: {agreement_ids: ["1"]}}}` answers the order id (integer). The
   agreement id is the terms-and-conditions checkbox; `"1"` is what that one capture sent and where it comes from
   (checkout configuration) is **unobserved**, so `order_free` takes it as a parameter.
7. The browser then loads `/en/checkout/onepage/success/` and `/en/sales/order/view/order_id/<id>/`.

Safety, in code and tested:

- `add_to_cart(publication_id, choice, confirm)` and `order_free(billing, confirm)` return a `Plan` when `confirm` is
  `None`. A `Confirmation(reference, expected_total, currency, accept_terms)` must name the item (matched to the
  page's designation) and the total the store shows, or nothing is posted.
- `order_free` refuses, as a dry run too, unless the server's `grand_total` is zero; refuses a confirmation whose
  expected total is not zero; refuses without `accept_terms=True` (placing the order accepts the store's terms, which
  is the owner's decision); refuses unless the cart holds exactly that one item.
- Nothing removes from a cart (the removal call is not in the capture), so `add_to_cart` refuses to start if the
  cart holds another item. The billing address is a `BillingAddress` the caller loads at run time (the CLI reads a
  JSON file outside every repository); its `repr` is redacted and it is never logged.
- The only payment method ever sent is `free`.

## Orders, licences and downloads

- `GET /en/sales/order/view/order_id/<id>/` (HTML): an "Order summary" grid (reference, language, format,
  user/qty, subtotal) with, per item, `getStatus<n>(<orderItemId>)`, and `orderDownloadDropdown(<orderId>)` in the
  header. `parse_order_view` reads items only; the page's payment method and billing address are not read.
- `GET /en/rest/V1/publications/mine/download-status/order/<orderId>` (the whole order) and `.../download-status/
  <orderItemId>` (one item): **a JSON string holding JSON** (`json_twice`): `{status: "PROCESSING" | "COMPLETED",
  is_downloadable, download_url}`; the item form adds `is_available_soon`, `is_outdated_prv` (a `NOT_REGISTRABLE`
  status is tested in the page too). The page polls every 5 s, at most 10 times, then opens `download_url`.
- `download_url` is a pre-signed S3 URL, an `.zip`, on a host named `storage-watermark-...`: **a watermarked copy**.
  `OrderClient.download` waits as the page does, follows only a host that starts `storage-watermark-` and ends
  `.amazonaws.com`, streams to `<name>.part` with the shared chunking, checks `Content-Length`, hashes with sha256,
  and `os.replace`s into place; it never overwrites, removes the `.part` on any failure, and refuses a destination
  inside any git working tree. The hash differs per download of a watermarked file; record it, do not pin it.
- "What am I licensed for": `OrderClient.owned(max_orders=n)` reads the order-history page for `order_id/<n>` links,
  then each order page, one request per order. **Unobserved:** the history page itself (`/en/sales/order/history/`)
  and "my products" (`/en/publication/customer/products/`) were links only, so the id-link scraping is a guess at a
  Magento-standard page; verify it against a real session. A multi-user licence appears as the `User/Qty` column.

## Local catalogue and index

`python -m primarysource.iec.webstore sync --i-have-read-the-terms --facet committee='TC 999' --max-pages 2`
writes one JSON stub per publication to `<collection home>/webstore/stubs/<id>.json` and rebuilds
`<collection home>/webstore/catalog.sqlite` through the core FTS5 index (`primarysource/index.py`). The home is
`primarysource.home.collection_home("iec")`, never the repository. The index holds the fields below, including the
catalogue abstract: no standard's text. `find <query>` searches it offline; a missing index is an error naming the rebuild command.

Other commands: `search` (one live page, public), `owned`, `download --order|--item --to <dir>`, `cart <id>
[--confirm-reference R --confirm-total N]`, `order --billing-json <file> [--confirm-reference R --confirm-total 0
--accept-terms]`. Without the confirm flags `cart` and `order` print a dry run. The coordinator wires this into the
main CLI and registry; this package does not edit them.

### Catalog fields

| Stub field | Source in the search hit | Notes |
| --- | --- | --- |
| `reference`, `title`, `edition`, `status` | `reference`, `title`, `edition`, `status` | Designation, title, edition, `PUBLISHED`... |
| `price` `{amount, currency}`, `is_free` | `price` | `is_free` is `amount == 0`; the index holds the word "free". |
| `committee` (`level_1`, `level_2`, names) | `committee` | Technical committee / subcommittee. |
| `ics` (`code`, `title`, `group`) | `ics` | ICS subject codes at up to three levels. |
| `publication_type`, `head` | `publication_type`, `reference_object.head` | `STANDARD`, `CONSOLIDATED`...; `IEC`, `ISO/IEC`... |
| `languages`, `formats`, `files` | `available_files`, `available_formats` | Per file format, language, kind. |
| `pages`, `isbn`, `urn`, `url` | `pdf_pages`, `isbn`, `urn`, `id` | |
| `publication_date` | `publication_date` | Date of this edition. |
| `lifecycle` (`reference`, `edition`, `status`, `date`) | `lifecycle` | Supersession links: earlier editions and what replaced them (`REVISED`...). |
| `abstract` | `abstract` | Catalogue blurb; no TOC was in any response. |
| `fetched` | (local) | UTC time of the sync. |

A stability date was not in any hit or page (unobserved), so none is stored. The `related_pubs` and
`referenced_by` lists are in the response but not stored.

### Filtering

`filter_catalog(home, free_only=, min_price=, max_price=, currency=, category_prefix=, status=)` returns the stubs
matching every condition, by designation, from the stubs only (no network). `category_prefix` is a
case-insensitive prefix of a committee (`TC 86`, `SC 86A`), an ICS code (`33.100` matches `33.100.10`), the
publication type or the reference head. A stub without a price never matches a price bound or `free_only`. The
shell form is `filter --free --max-price 500 --category 33.100 --status PUBLISHED`; free-text search stays
`find`.

## What the capture does not show (open questions)

1. IEC's terms on automated access and TDM (the terms page was not captured): **unverified**.
2. The login request and its success answer, the CAPTCHA behaviour, the session cookie's name, whether `form_key`
   is checked server-side against the cookie only, and any rate limit or bot rule on the store or the search API.
3. A non-empty text query, the autocomplete answer, `dateRanges` values, facet levels above 1, `collapsed` inner hits.
4. The order-history and "my products" pages; any pagination of them; any list of licences other than order pages.
5. Table of contents, preview and sample content: none appeared in a response.
6. How the agreement id for the terms checkbox is obtained, and whether a different free item needs other fields
   (the one free order captured used English, Electronic, one user).
7. Whether the order-confirmation e-mail or a refresh step precedes a download becoming ready for paid items
   (only a free item's download was captured).
8. Cart removal, a cart that carries coupons or gift wrapping, a paid checkout (`datatrans`, `banktransfer`): none
   observed, none implemented.
9. Whether `secondary` equals `primary` when `terms` is empty (inferred, not seen).
