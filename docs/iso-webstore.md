# iso-webstore: a client for the ISO webstore, from the owner's own browser capture

Recorded 2026-11-14. The owner supplied one browser capture of a session on `www.iso.org` (575 entries: registering an
account, browsing the Online Browsing Platform, filling a basket, placing a free order, assigning licences,
downloading three PDFs). This document records what that capture shows, what the client in
`primarysource/iso/webstore/` does with it, and what it does **not** show. Nothing here was checked against the live
site: no request was made to iso.org while writing it, and every test uses a fake transport and invented values.

The capture itself is the owner's: it holds session state and account details, so it is not in this repository and
no cookie, token, name, address, e-mail or order id appears below. Request shapes show header and field **names**
only.

```
python -m primarysource.iso.webstore load catalog.jsonl     # stubs under <iso home>/webstore/catalog/   (offline)
python -m primarysource.iso.webstore index                  # the FTS5 index over the stubs               (offline)
python -m primarysource.iso.webstore find widgets --free --ics-prefix 35.100
python -m primarysource.iso.webstore sync "widgets" --i-accept-the-terms --max-pages 2
python -m primarysource.iso.webstore owned | download "ISO/IEC 26136:2024" | plan-free-order | free-order ...
```

## 1. Hosts and endpoints seen

| Host | Path | Method | What it is |
| --- | --- | --- | --- |
| `www.iso.org` | `/store.html`, `/standard/<n>`, `/publication/PUB<n>.html`, `/sectors/*`, `/standards-catalogue/browse-by-ics.html`, `/standards-catalogue/browse-by-tc.html` | GET | Jahia content pages. Only `/store.html` was fetched; the others are links in it. |
| `www.iso.org` | `/webstore/graphql` | POST | The webstore GraphQL API (section 4). |
| `www.iso.org` | `/webstore/MiniShoppingBasket?memberId=<id>&purchaseId=<id>` | GET | Adds a line to the session's basket; answers `{itemCount, totalAmount, currency}`. |
| `www.iso.org` | `/webstore/shoppingbasket/summary?_=<ms>` | GET | The same answer, without adding. |
| `www.iso.org` | `/webstore/environments/idp-url`, `/webstore/environments/appconfig.json` | GET | Front-end configuration (the identity provider's origin; tenant `ISO`, languages `en fr ru es`). |
| `www.iso.org` | `/webstore/oauth2/authorization/iso`, `/webstore/login/oauth2/code/iso`, `/webstore/login` | GET | The webstore's sign-in client (section 3). |
| `www.iso.org` | `/obp/oauth2/authorization/iso`, `/obp/login/oauth2/code/iso` | GET | The browsing platform's sign-in client. |
| `www.iso.org` | `/obp/ui`, `/obp/ui/UIDL/?v-uiId=<n>`, `/obp/ui/HEARTBEAT/` | GET, POST | The Online Browsing Platform, a Vaadin 8.14.3 application (section 6). |
| `www.iso.org` | `/obp/ui/APP/connector/<ui>/<connector>/dl` | GET | A PDF download (section 6). |
| `idp.iso.org` | `/realms/ws-iso/protocol/openid-connect/auth`, `/realms/ws-iso/login-actions/{authenticate,registration,required-action}` | GET, POST | Keycloak, realm `ws-iso`, client `ui`. |

Third-party hosts also appear (analytics, a consent manager, a payment widget loader, a CDN). They are not part of
the client and are not contacted by it.

## 2. What the capture does NOT contain

Stated first because it limits everything else.

- **No catalog search request.** The store page loads the Algolia InstantSearch libraries and an inline settings block,
  but the capture holds no request to the search service. The search call in `search.py` is the service's documented
  REST shape, not an observed one.
- **No Jahia detail page** (`/standard/<n>`, `/committee/<n>`, the ICS and TC browse pages): only links to them. So no
  price list, edition table, ICS or TC field, supersession link, page count, publication date or table of contents
  was seen on a catalog page.
- **No sign-in form submission.** The owner registered a new account (a registration form, then a "required action"
  form with one field, `accept`) and later signed in through single sign-on that needed no form. The sign-in form
  itself was seen only as HTML.
- **No bearer token and no cookie.** The capture was saved without them. Every request is authenticated by a session
  cookie the browser held; the form is the only credential path the client implements.
- **No download link before a UI session**; the link only exists inside one (section 6).

## 3. Sign-in

Both the webstore and the browsing platform are server-side OAuth2 clients of one Keycloak realm.

1. `GET /webstore/oauth2/authorization/iso` redirects (302) to the realm's `.../openid-connect/auth` with
   `response_type=code`, `client_id=ui`, `scope=openid profile`, `state`, `redirect_uri` and `nonce`. There is **no PKCE
   challenge**: the front end never sees the code.
2. The realm answers 200 with a form: `<form id="login" method="post">` with fields `username`, `password` and a hidden
   `credentialId`, and an action under `.../login-actions/authenticate`.
3. Posting it redirects (302) to `/webstore/login/oauth2/code/iso?state&session_state&iss&code`, which the webstore
   exchanges server-side and answers with a redirect to `/webstore/`, setting its session cookie.
4. Once the realm's own session cookie exists, step 1 redirects straight back with a code and no form (seen for the
   webstore after the browsing platform's registration).
5. Account creation inserts a registration form (`firstName`, `lastName`, `email`, `password`, `password-confirm`) and a
   required-action form (`accept`). The client implements neither: creating an account and accepting terms are the
   owner's to do in a browser, and the client stops with a message when the realm asks.

`auth.login` follows exactly this, one hop at a time, with every redirect target checked against the allow-list
(`www.iso.org`, `idp.iso.org`). A password grant and PKCE were not seen and are not implemented.

**Environment variables**

| Variable | Use |
| --- | --- |
| `PRIMARYSOURCE_ISO_USERNAME` | The account's login name. Read into a `Secret`. |
| `PRIMARYSOURCE_ISO_PASSWORD` | The password. Read into a `Secret`, sent once in the form body, never written anywhere. |
| `PRIMARYSOURCE_ISO_TOKEN_FILE` | Optional. A path where the session cookies are cached between runs (owner-only permissions; refused inside a git work tree). The cookies are credentials: protect the file like a password. |
| `PRIMARYSOURCE_ISO_HOME` | Where the collection lives (`docs/iso.md` section 1). Stubs, the index and downloads go here. |
| `PRIMARYSOURCE_ISO_NETWORK`, `PRIMARYSOURCE_NETWORK`, `PRIMARYSOURCE_ISO_READONLY` | The collection's network settings (`primarysource/settings.py`). `offline` or read-only stops every request before it is made. |

`Secret.__repr__`, `__str__` and `__format__` print `Secret(<redacted>)`; a secret cannot be pickled. Error messages
never contain a credential.

## 4. The GraphQL API (`POST /webstore/graphql`)

Request body `{operationName, variables, query}`, `Content-Type: application/json`; the session cookie is the
authentication. An error is `{"errors": [{"message"}]}` with HTTP 200. Operations seen, with variables and the fields
the client reads (`graphql.py` holds the documents):

| Operation | Kind | Variables | Fields / use | Implemented |
| --- | --- | --- | --- | --- |
| `currentData` | query | none | `currentUser {username displayName preferredLanguage roles hasCredentials}`; `null` when signed out | read; only roles and language are kept |
| `currentOrder` | query | none | The basket: `orderStatus type currency total totalTax totalShippingCharge shippingMethod items[...] checksum`. Each item: `description language format media editionId edition paymentFrequency listPrice unitPrice currency quantity total licenses isShippingChargeLineItem lockedForUser itemId{priceBookId ratePlanId formatId editionId instanceId locked}` | yes |
| `checkoutData` | query | none | `currentUserProfile` (name, addresses, phone, VAT number, consents), `currentOrder`, `currentPromotions`, `webstoreUrl` | **no**: it returns the profile and addresses |
| `currentPaymentSelection` | query | none | saved cards (type, number, holder, address, e-mail) | **no**: payment data |
| `orderSummary` | query | `orderId: String!` | `orderNumber orderStatus total totalTax totalShippingCharge currency messages items[productName productType productCode language format media editionYear edition quantity licenses unitPrice description requiresShipping]` | yes |
| `tenantObpUrl` | query | none | the browsing platform's URL | document only |
| `countryStates` | query | `countryCode` | `[{key,label}]` | document only |
| *(unnamed)* | query | none | `organizationSizes industries preferredLanguages` `[{key,label}]` | document only |
| `processFreeOrder` | mutation | `isShareDataAccepted`, `isEmailNotificationAccepted`, `isWithdrawalConsentAccepted: Boolean!`, `orderChecksum: String!` | answers an `OrderSummary` | **yes, guarded** (section 8) |
| `deleteOrderItem` | mutation | `itemId: ItemIdInput!` (the five `itemId` fields) | answers the order | **no** (described only) |
| `updatePurchaseOrderNumber` | mutation | `purchaseOrderNumber: String` | answers the order | **no** |
| `updateUserDetails` | mutation | `personalInformation {firstName lastName preferredLanguage{key label} phone mobile fax organizationSize industry vatNumber}`, `address {company addressLine city zip country{key label} state{key label}}` | answers the profile | **no**: profile and address changes |
| `startUserSession` | mutation | `username: String!` | `Boolean` | **no** |

The order's money fields are JSON numbers; the client reads them as `Decimal`. The capture shows prices in `CHF`.
Zero-priced lines (the free JTC 1 publications) have `unitPrice` and `total` of `0.0`; a print edition appeared as a
line with `format: Paper`, `media: Print`.

## 5. Catalog search, categories and prices

**Search.** `/store.html` carries `algolia = { settings: { appID, apiKey, index: { name } } }`. The key is a
*secured* key (base64 text that spells out `validUntil=<unix>` and `restrictIndices=<index list>`), valid for about a
day and limited to the site's own indexes; `search.CatalogSearch` reads it from the page at run time, keeps it in a
`Secret`, decodes the expiry and re-reads the page when it has passed. The front end's code shows the index (English)
and an `_autocomplete` companion, an `empty query sends nothing` rule, a 20-page limit, and these hit attributes:
`reference`, `title`, `text`, `category`, `statusKey`, `seoURL`, `path`, `thumbnail`, `order`, `facet`.

- `category` values: `standard page news publication event sdg organization committee ics member`. The client
  filters on it after the search, because the capture does not show which attributes the service facets on.
- `statusKey`: `ENT_ACTIVE`, `ENT_PROGRESS`, `ENT_INACTIVE`, `ENT_DELETED`. The client maps them to `active`,
  `in-development`, `inactive`, `deleted`; what the site's labels say for each is not in the capture.
- **Subject (ICS) and technical-committee categories** exist as hit categories `ics` and `committee`, and as the
  two browse pages linked from the store page.

**Prices.** A catalog hit, as far as the capture shows, carries **no price**. The only prices seen are order and
basket lines (`listPrice`, `unitPrice`, `currency`, `format`). So a stub's price is set from an order or basket line
or from a loaded file, and is empty for a search hit.

### Catalog fields

What a `CatalogEntry` stub holds. "Seen" is whether the capture shows the field in any response; a field marked *assumed*
is read by `search.parse_hit` under the attribute name given, which the capture cannot confirm. An unstated field is
stored empty, never guessed.

| Field | Source | Seen |
| --- | --- | --- |
| `designation` | hit `reference`; order `description`; order summary `productCode` + `editionYear` | yes |
| `title` | hit `title`; the browsing platform's product list | yes |
| `kind` (category) | hit `category` | yes |
| `status` / `status_key` | hit `statusKey` | yes |
| `url` | hit `seoURL` (joined to `https://www.iso.org`) | yes |
| `abstract` | hit `text` | yes |
| `edition`, `year` | order summary `edition`, `editionYear`; hit `edition`, `year` | summary yes; hit *assumed* |
| `price` (`amount`, `currency`) and the free flag | order or basket line `unitPrice` and `currency`; free is `amount == 0` | yes, but not on a catalog hit |
| `formats` | order line `format` (`PDF`, `Paper`, `PDF + ePub`); hit `formats` | order yes; hit *assumed* |
| `product_code` | order summary `productCode` (`iso:std:iso-iec:29341:-31-1`) | yes |
| `ics` (codes) | hit `ics` | *assumed* |
| `committee` | hit `committee` | *assumed* |
| `language` | order line `language`; hit `language` | order yes; hit *assumed* |
| `pages` | hit `pages` | *assumed* |
| `published` | hit `publicationDate` or `published` | *assumed* |
| `supersedes`, `superseded_by` | hit `supersedes`, `supersededBy` | *assumed* |
| `toc` | hit `toc` | *assumed*; the capture shows no public table of contents anywhere |

The assumed names are guesses. The first sync shows what a hit really carries (`CatalogEntry.extra` keeps only a few
raw attributes; extend `parse_hit` once real hits are inspected). Public detail pages are the likelier home of price,
ICS, committee, pages, dates, supersession and contents; this client does not parse them, because their HTML is not in
the capture.

### Filtering

`CatalogStore.select(CatalogFilter(...), query=None)` and `python -m primarysource.iso.webstore find`:

| Condition | Meaning |
| --- | --- |
| `free=True` / `--free` | price known and zero |
| `free=False` / `--priced` | price known and above zero |
| `min_price`, `max_price` | on the amount; a record with no price never matches |
| `ics_prefix` | any ICS code starts with it (`35.100`, `01.`) |
| `committee_prefix` | the committee name starts with it (`ISO/IEC JTC 1`) |
| `status`, `category`, `language` | equality |

With a `query` the result is ranked by BM25 over the stub text (designation, title, abstract, ICS, committee, price,
status, supersession); without one it is ordered by designation and needs no index.

## 6. The Online Browsing Platform, and where a PDF comes from

The platform is a Vaadin 8.14.3 single-page application. It has no REST API: `/obp/ui` loads it, a form post of browser
details answers `{"v-uiId", "uidl"}` (the whole UI as JSON, with a `Vaadin-Security-Key` the later posts echo as
`csrfToken`), and each action is a post to `/obp/ui/UIDL/?v-uiId=<n>` of `{csrfToken, rpc, syncId, clientId}` where `rpc` is a
list of `[connectorId, interface, method, params]`. Routes are URL fragments: `#home`, `#search`, `#account/products`,
`#account/orders`, `#account/profile`, and content views under `/en/content/iso/pub/PUB<n>.xml`.

- **Owned products.** `#account/products` lists each publication: a designation label, a `(en)` language label, a
  title label, a **PDF** button, and "Assign licence #1 to **you** / someone else". Pressing *you* opens a dialog
  (Ok / Cancel); after Ok the row shows the PDF button with a `FileDownloader` extension whose resource is
  `app://APP/connector/<ui>/<connector>/dl`.
- **The download** is `GET /obp/ui/APP/connector/<ui>/<connector>/dl`: `200`, `Content-Type: application/octet-stream`,
  `Content-Disposition: attachment; filename=<name>`, a PDF body. The names follow `ISO_IEC_<number>_<year>(en).pdf`,
  the pattern `docs/iso.md` already imports. The link is valid for that UI session only, so it cannot be known without
  holding one. `obp.ObpSession` holds one and `obp.parse_products` reads the rows; `download.download_owned` streams the
  file to `<name>.part`, checks it starts with `%PDF-`, hashes it, and `os.replace`s it into the iso home (never into a
  repository). Everything in `obp.py` is reconstructed from one capture; treat it as unproven until run once.
- **Add to basket in the platform.** A click makes the server answer an `HttpRequestClientRpc.open` instruction with
  the `MiniShoppingBasket` URL, and the browser performs that GET. The `purchaseId` in it is four ids joined by `~`: the
  price book id, an id the capture does not name, the format id and the edition id (three of the four equal fields of the
  order line's `itemId`). `obp.basket_urls` only shows such an instruction; no code follows it.

**Out of scope, on purpose.** The platform's search, its content views, tables of contents and everything that shows a
standard's text are not implemented, and will not be: ISO's terms forbid scraping, harvesting and text-and-data-mining
of the platform and of the no-cost content (`docs/iso.md` section 3). The client reads the owner's own product list
and fetches the owner's own file, which is what the owner does in a browser; it never opens a standard.

## 7. The catalog sync: opt-in, bounded, metadata only

`sync_catalog` / `python -m primarysource.iso.webstore sync QUERY... --i-accept-the-terms`:

- **Metadata only.** It asks the site's catalog search for records and stores the fields in the table above. It never
  fetches a standard's text, a table of contents from the platform, or any document. If the search hit carries a public
  abstract or contents list, that is stored; nothing else is read.
- **Opt-in.** Refused unless `opt_in=True` (`--i-accept-the-terms`); it never runs from an import, a test or a default.
- **Bounded.** At most 25 queries per run, at most 20 pages per query (the site's own limit), default 2 pages of 20 hits;
  it stops at a query's last page and at the first error.
- **Polite.** One request per second (the session's throttle), `https` to the named hosts only (the two ISO hosts and
  the one search host that has the service's `<app>-dsn` shape), redirects re-checked, the collection's
  `PRIMARYSOURCE_ISO_NETWORK` / `READONLY` settings honoured before every request (offline stops before the first).
- **Anonymous and generic.** The catalog calls send no credentials and the User-Agent is the package's generic
  `primarysource-importer (+<project url>)`, with no personal data.
- It writes stubs under `<iso home>/webstore/catalog/`; `index` then rebuilds `catalog.sqlite`.

## 8. Basket and free orders (state-changing, guarded)

Two calls change anything: the basket GET and `processFreeOrder`. Both are dry-run unless given a confirmation object.

- `Basket.add(purchase_id, AddConfirmation(purchase_id, item, expected_total))`: without the confirmation it returns the
  request it would make (the id shown by length only). With it, it adds, then compares the answer's total with
  `expected_total`; on a difference it raises and says the item is already in the basket and must be removed in a browser.
- `Basket.plan_free_order()` reads the current order and lists why it is not free. `Basket.free_order(
  FreeOrderConfirmation(items, expected_total, accept_withdrawal_consent))` places it only if **the server's own figures
  are zero** (total, tax, shipping, every line's unit price and total), no line is a print item or a shipping charge, the lines
  are exactly the named descriptions, `expected_total` is zero and the withdrawal consent is accepted by the caller
  (never defaulted). The checksum is read just before the call. The optional data-sharing and e-mail consents default to
  refused.
- Paying, `deleteOrderItem`, profile, address and payment mutations are described in section 4 and not implemented. A test
  fails if another mutation document appears in the package.

The capture shows the sequence a free order follows: basket lines at `0.0`, `processFreeOrder` with
`isWithdrawalConsentAccepted: true` and the other two `false`, an `OrderSummary` with status `Complete`, then the products
page where each licence is assigned.

## 9. Terms caution

ISO's no-cost access agreement and the platform's terms forbid scraping, harvesting and text-and-data-mining, and use in
AI training or operation; ISO opts out of statutory mining exceptions (`docs/iso.md` section 3). The agreement for a
purchase was not read (its page refused an automated fetch). This client is for one owner, run by that owner, on their own
account, for their own purchases and for catalog metadata. The sync is the part most likely to be questioned: run it only
if the owner has read the current terms and accepts them, and keep it small.

## 10. Open questions: what could not be determined

1. The catalog search's real request and response (no traffic in the capture): the REST shape is documented but unobserved,
   and the facet attributes are unknown.
2. Every hit attribute beyond the ten the front end reads, hence the *assumed* rows in the table.
3. Whether a catalog page or hit ever shows a price, and the currency or VAT behaviour for other countries.
4. How a `purchaseId` is obtained for a given standard without the platform UI; what its second id is.
5. The sign-in form post, a captcha or second factor, and rate limits (never seen). Whether the session cookie
   lasts across runs (the token-file cache assumes it can).
6. Whether the platform's `#account/products` route can be opened by a fresh UI session as `ObpSession.open` does it
   (the capture shows the browser's own sequence of a resize, a resynchronise, then clicks), and whether the dialog's
   Ok needs the window-position RPCs the browser sent first.
7. The meaning of the status labels, the second `ratePlanId` form, `licenses`, `follow` and `instanceId`.
8. Whether `shoppingbasket/summary` and `MiniShoppingBasket` need `memberId=ISO` for the owner's account, and the
   order history route's content (`#account/orders` was visited, not decoded).
9. Public tables of contents and previews: none seen; the Jahia detail pages were not captured.
10. Whether the owner's terms allow a catalog sync at all; the purchase agreement was not read.
