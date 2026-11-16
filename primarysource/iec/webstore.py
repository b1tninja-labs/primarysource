"""IEC Webstore session: free publications are CHF 0 cart items, then a downloadable PDF.

The store is Magento. A free Electronic PDF is obtained by:

1. guest multipart add-to-cart with a matching `form_key` (language/format/1-user options);
2. REST customer token (`IEC_EMAIL` / `IEC_PASSWORD`) to assign that guest cart and place a `free` order;
3. HTML `loginPost` with a matching `form_key` (cookie session for the library download);
4. `GET /rest/V1/publications/mine/download-status/<orderItemId>` for a short-lived S3 URL.

The HTML session and the REST token see different carts, so the add must stay on a guest cookie jar.

Nothing here is redistributed: files land only under the user's `PRIMARYSOURCE_HOME/iec` volume.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from html import unescape
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Any

from primarysource.errors import LibError

HOSTS = ("webstore.iec.ch", "storage-watermark-prd-iec-ch.s3.eu-west-1.amazonaws.com")
BASE = "https://webstore.iec.ch"
UA = "primarysource-iec/0.1 (+https://github.com/b1tninja-labs/primarysource; free-publication sync)"
TIMEOUT = 120
STORE_ID = 6  # English store view observed on the live site


@dataclass(frozen=True, slots=True)
class FreePublication:
    publication_id: str
    reference: str
    title: str
    head: str


@dataclass(frozen=True, slots=True)
class DownloadResult:
    publication_id: str
    reference: str
    path: Path
    bytes: int
    order_item_id: str
    skipped: bool = False
    note: str = ""


class Webstore:
    """One cookie jar plus optional REST bearer token for the IEC Webstore."""

    def __init__(self, email: str, password: str) -> None:
        if not email or not password:
            raise LibError(
                "IEC webstore credentials are not set",
                "",
                "set IEC_EMAIL and IEC_PASSWORD in .env (see .env.example)",
            )
        self.email = email
        self.password = password
        self.jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self._token: str | None = None
        self._customer_id: int | None = None

    def _set_cookie(self, name: str, value: str) -> None:
        self.jar.set_cookie(
            Cookie(
                0,
                name,
                value,
                None,
                False,
                ".webstore.iec.ch",
                True,
                True,
                "/",
                True,
                True,
                None,
                True,
                None,
                None,
                {},
                False,
            )
        )

    def request(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        method: str | None = None,
        max_bytes: int = 8_000_000,
    ) -> tuple[int, dict[str, str], bytes, str]:
        hdrs = {"User-Agent": UA, "Accept": "*/*"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with self._opener.open(req, timeout=TIMEOUT) as resp:
                return (
                    resp.status,
                    {k.lower(): v for k, v in resp.headers.items()},
                    resp.read(max_bytes),
                    resp.geturl(),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(2_000_000), url
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LibError(f"{url}: {exc}", "check the network and retry") from exc

    def login_html(self) -> None:
        """Cookie session for download-status (REST token alone cannot open the library pages)."""
        status, _, page, _ = self.request(f"{BASE}/customer/account/login/")
        if status != 200:
            raise LibError(f"IEC login page HTTP {status}", "retry later")
        key = _form_key(page)
        self._set_cookie("form_key", key)
        self._set_cookie("last_visited_store", "en")
        status, _, body, url = self.request(
            f"{BASE}/customer/account/loginPost/",
            data=urllib.parse.urlencode(
                {"form_key": key, "login[username]": self.email, "login[password]": self.password, "send": ""}
            ).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE,
                "Referer": f"{BASE}/customer/account/login/",
            },
        )
        if "login" in url.rstrip("/").split("/")[-1].lower() and b"Welcome" not in body:
            raise LibError("IEC webstore login failed", "", "check IEC_EMAIL / IEC_PASSWORD")

    def token(self) -> str:
        if self._token:
            return self._token
        status, _, body, _ = self.request(
            f"{BASE}/rest/V1/integration/customer/token",
            data=json.dumps({"username": self.email, "password": self.password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if status != 200:
            raise LibError(f"IEC REST login HTTP {status}", "", "check IEC_EMAIL / IEC_PASSWORD")
        token = json.loads(body.decode())
        if not isinstance(token, str) or not token:
            raise LibError("IEC REST login returned no token", "", "check IEC_EMAIL / IEC_PASSWORD")
        self._token = token
        return token

    def customer_id(self) -> int:
        if self._customer_id is not None:
            return self._customer_id
        status, _, body, _ = self.request(
            f"{BASE}/rest/V1/customers/me",
            headers={"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"},
        )
        if status != 200:
            raise LibError(f"IEC customer profile HTTP {status}", "retry later")
        data = json.loads(body.decode())
        self._customer_id = int(data["id"])
        return self._customer_id

    def product_page(self, publication_id: str) -> tuple[str, str, str, str]:
        """action URL, form_key, Magento product entity id, and page text for `/publication/<id>`."""
        status, _, page, _ = self.request(f"{BASE}/en/publication/{publication_id}")
        if status != 200:
            raise LibError(f"publication {publication_id}: HTTP {status}", "retry later")
        text = page.decode("utf-8", "replace")
        action = re.search(r'action="(https://webstore\.iec\.ch/en/checkout/cart/add/[^"]+)"', text)
        product = re.search(r'name="product"\s+value="(\d+)"', text)
        if action is None or product is None:
            raise LibError(
                f"publication {publication_id}: add-to-cart form not found", "the page layout may have changed"
            )
        return action.group(1), _form_key(page), product.group(1), text

    def add_electronic(self, publication_id: str) -> str:
        """Add the free Electronic / 1-user option on this jar; return the guest masked cart id."""
        last: LibError | None = None
        for _attempt in range(2):
            try:
                return self._add_electronic_once(publication_id)
            except LibError as exc:
                last = exc
                if "forcibly closed" not in exc.message and "timed out" not in exc.message.lower():
                    raise
        if last is not None:
            raise last
        raise LibError(f"publication {publication_id}: add failed", "retry later")

    def _add_electronic_once(self, publication_id: str) -> str:
        action, key, product_id, text = self.product_page(publication_id)
        language = _select_option(text, "options[publication_language]", "English", contains=True)
        electronic = _electronic_for_language(text, language)
        users = _select_option(text, "options[license_price]", "1")
        before = int(self.section_cart().get("summary_count") or 0)
        self._set_cookie("form_key", key)
        self._set_cookie("last_visited_store", "en")
        body, ctype = _multipart(
            {
                "product": product_id,
                "selected_configurable_option": "",
                "related_product": "",
                "item": product_id,
                "form_key": key,
                "options[publication_language]": language,
                "options[publication_format]": electronic,
                "options[license_price]": users,
                "qty": "1",
            }
        )
        status, _, _, _ = self.request(
            action,
            data=body,
            headers={"Content-Type": ctype, "Origin": BASE, "Referer": f"{BASE}/en/publication/{publication_id}"},
        )
        if status not in (200, 302):
            raise LibError(f"publication {publication_id}: add-to-cart HTTP {status}", "retry later")
        cart = self.section_cart()
        after = int(cart.get("summary_count") or 0)
        if after <= before:
            raise LibError(f"publication {publication_id}: cart stayed empty after add", "retry later")
        cart_id = cart.get("cartId") or ""
        if not cart_id:
            raise LibError(f"publication {publication_id}: guest cart id missing", "retry later")
        return str(cart_id)

    def section_cart(self) -> dict[str, Any]:
        status, _, body, _ = self.request(
            f"{BASE}/customer/section/load/?sections=cart&force_new_section_timestamp=true",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if status != 200:
            raise LibError(f"IEC cart section HTTP {status}", "retry later")
        data = json.loads(body.decode())
        cart = data.get("cart")
        if not isinstance(cart, dict):
            raise LibError("IEC cart section had no cart", "retry later")
        return cart

    def assign_and_order(self, masked_cart_id: str) -> str:
        """Assign a guest cart to the customer and place a free order; return the order id."""
        auth = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
        status, _, body, _ = self.request(
            f"{BASE}/rest/V1/guest-carts/{masked_cart_id}",
            data=json.dumps({"customerId": self.customer_id(), "storeId": STORE_ID}).encode(),
            headers=auth,
            method="PUT",
        )
        if status != 200:
            raise LibError(f"IEC cart assign HTTP {status}: {body[:200]!r}", "retry later")
        status, _, me, _ = self.request(f"{BASE}/rest/V1/customers/me", headers=auth)
        if status != 200:
            raise LibError(f"IEC customer profile HTTP {status}", "retry later")
        customer = json.loads(me.decode())
        addresses = customer.get("addresses") or []
        if not addresses:
            raise LibError("IEC account has no address on file", "", "add a billing address in the webstore once")
        addr = addresses[0]
        region = addr.get("region")
        region_dict = region if isinstance(region, dict) else {}
        bill = {
            "address": {
                "region_id": addr.get("region_id"),
                "region": region_dict.get("region") if region_dict else region,
                "region_code": region_dict.get("region_code") if region_dict else None,
                "country_id": addr.get("country_id"),
                "street": addr.get("street"),
                "telephone": addr.get("telephone") or "000",
                "postcode": addr.get("postcode"),
                "city": addr.get("city"),
                "firstname": addr.get("firstname"),
                "lastname": addr.get("lastname"),
                "email": self.email,
            }
        }
        status, _, body, _ = self.request(
            f"{BASE}/rest/V1/carts/mine/billing-address",
            data=json.dumps(bill).encode(),
            headers=auth,
            method="POST",
        )
        if status != 200:
            raise LibError(f"IEC billing address HTTP {status}: {body[:200]!r}", "retry later")
        payloads = (
            {"paymentMethod": {"method": "free", "extension_attributes": {"agreement_ids": [1]}}},
            {"paymentMethod": {"method": "free", "extension_attributes": {"agreement_ids": ["1"]}}},
            {"paymentMethod": {"method": "free"}, "extension_attributes": {"agreement_ids": [1]}},
        )
        status, body = 0, b""
        for payload in payloads:
            status, _, body, _ = self.request(
                f"{BASE}/rest/V1/carts/mine/payment-information",
                data=json.dumps(payload).encode(),
                headers=auth,
                method="POST",
            )
            if status == 200:
                break
        if status != 200:
            raise LibError(
                f"IEC place-order HTTP {status}: {body[:300]!r}",
                "open the webstore cart and finish once by hand",
            )
        return json.loads(body.decode()) if body[:1] == b'"' else body.decode().strip()

    def order_free_batch(self, publication_ids: Sequence[str]) -> tuple[str, list[str]]:
        """Add every id to one guest cart, assign it, and place one free order.

        Returns `(order_id, publication ids that could not be added)`.
        """
        if not publication_ids:
            raise LibError("no publications to order", "")
        self.clear_mine_cart()
        guest = Webstore(self.email, self.password)
        failed: list[str] = []
        masked = ""
        total = len(publication_ids)
        for index, publication_id in enumerate(publication_ids, 1):
            try:
                masked = guest.add_electronic(publication_id)
            except LibError as exc:
                failed.append(publication_id)
                print(f"cart skip {index}/{total} {publication_id}: {exc.message}", file=sys.stderr)
                continue
            print(f"cart {index}/{total} {publication_id}", file=sys.stderr)
        if not masked:
            raise LibError(
                "none of the free publications could be added to the cart",
                "primarysource iec sync --free",
            )
        count = guest.section_cart().get("summary_count")
        print(f"cart has {count} item(s); checking out once", file=sys.stderr)
        return str(self.assign_and_order(masked)), failed

    def clear_mine_cart(self) -> None:
        """Drop every line in the customer's cart so a free order is only the publication just added."""
        auth = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
        status, _, body, _ = self.request(f"{BASE}/rest/V1/carts/mine/items", headers=auth)
        if status == 404:
            return
        if status != 200:
            raise LibError(f"IEC cart items HTTP {status}", "retry later")
        items = json.loads(body.decode())
        if not isinstance(items, list):
            return
        for item in items:
            item_id = item.get("item_id") if isinstance(item, dict) else None
            if item_id is None:
                continue
            status, _, _, _ = self.request(
                f"{BASE}/rest/V1/carts/mine/items/{item_id}",
                headers=auth,
                method="DELETE",
            )
            if status not in (200, 204):
                raise LibError(f"IEC cart clear HTTP {status}", "empty the webstore cart once by hand")

    def library_order_items(self, *, login: bool = True) -> list[tuple[str, str, str]]:
        """`(order_item_id, reference, product_entity_id)` from every page of My products."""
        if login:
            self.login_html()
        found: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        url: str | None = f"{BASE}/en/publication/customer/products/"
        pages = 0
        while url and url not in seen and pages < 40:
            seen.add(url)
            pages += 1
            status, _, body, _ = self.request(url)
            if status != 200:
                raise LibError(f"IEC library HTTP {status}", "retry later")
            text = body.decode("utf-8", "replace")
            found.extend(_library_rows(text))
            url = _next_page(text)
        seen_items: set[str] = set()
        unique: list[tuple[str, str, str]] = []
        for item_id, reference, product_id in found:
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            unique.append((item_id, reference, product_id))
        return unique

    def download_status(self, order_item_id: str) -> dict[str, Any]:
        status, _, body, _ = self.request(
            f"{BASE}/rest/V1/publications/mine/download-status/{order_item_id}",
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        if status != 200:
            raise LibError(f"IEC download-status {order_item_id}: HTTP {status}", "retry later")
        data: Any = json.loads(body.decode())
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise LibError(f"IEC download-status {order_item_id}: unexpected payload", "retry later")
        return data

    def fetch_pdf(self, order_item_id: str, dest: Path, *, waits: int = 12, interval: float = 5.0) -> int:
        """Poll download-status and write the PDF to `dest`. Returns byte length."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        last: dict[str, Any] = {}
        for _ in range(waits):
            last = self.download_status(order_item_id)
            url = last.get("download_url")
            if last.get("is_downloadable") and isinstance(url, str) and url.startswith("https://"):
                status, headers, body, _ = self.request(url, max_bytes=200_000_000)
                ctype = headers.get("content-type") or ""
                final = dest
                if status == 200 and (body.startswith(b"PK\x03\x04") or "zip" in ctype):
                    final = dest.with_suffix(".zip")
                elif status != 200 or not body.startswith(b"%PDF-"):
                    raise LibError(
                        f"IEC download for {order_item_id} was not a PDF (HTTP {status}, {ctype})",
                        "retry later",
                    )
                tmp = final.with_suffix(final.suffix + ".part")
                tmp.write_bytes(body)
                os.replace(tmp, final)
                return len(body)
            time.sleep(interval)
        raise LibError(
            f"IEC download for {order_item_id} was not ready ({last.get('status')!r})",
            "retry later, or download it once from the webstore library",
        )


def credentials_from_env(environ: dict[str, str] | None = None) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    return (env.get("IEC_EMAIL") or "").strip(), (env.get("IEC_PASSWORD") or "").strip()


def _electronic_for_language(text: str, language_value: str) -> str:
    """The Electronic format sold for the chosen language.

    A page can list two options both titled Electronic, one per language (`data-languages="en"`
    and `data-languages="fr"`). The first title match is then the wrong file and the cart stays empty.
    """
    block = re.search(r'<select[^>]*name="options\[publication_format\]"[\s\S]*?</select>', text)
    if block is None:
        raise LibError("publication form has no options[publication_format]", "the page layout may have changed")
    codes = _language_codes(text, language_value)
    electronics = [
        opt
        for opt in _option_tags(block.group(0))
        if opt.get("_caption", "").casefold() == "electronic" and opt.get("value")
    ]
    if not electronics:
        raise LibError("publication form has no 'Electronic' choice", "the page layout may have changed")
    matched = [opt for opt in electronics if _format_matches(opt, codes)] or electronics
    pdfs = [opt for opt in matched if (opt.get("data-option-code") or "").upper() == "PDF"]
    return str((pdfs or matched)[0]["value"])


def _language_codes(text: str, language_value: str) -> set[str]:
    block = re.search(r'<select[^>]*name="options\[publication_language\]"[\s\S]*?</select>', text)
    caption = ""
    declared = ""
    if block is not None:
        for opt in _option_tags(block.group(0)):
            if opt.get("value") == language_value:
                caption = opt.get("_caption", "").casefold()
                declared = (opt.get("data-languages") or "").casefold()
                break
    codes = {tok for tok in declared.replace(",", " ").split() if tok}
    if "english" in caption:
        codes.add("en")
    if "french" in caption and "english" not in caption:
        codes.add("fr")
    return codes


def _format_matches(opt: dict[str, str], codes: set[str]) -> bool:
    tokens = set((opt.get("data-languages") or "").casefold().replace(",", " ").split())
    if not tokens:
        return True
    return bool(tokens & codes)


def _option_tags(block: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for raw, caption in re.findall(r"<option\b([^>]*)>([^<]*)</option>", block, re.IGNORECASE):
        attrs = {key: unescape(value) for key, value in re.findall(r'([\w:-]+)="([^"]*)"', raw)}
        attrs["_caption"] = " ".join(unescape(caption).split())
        found.append(attrs)
    return found


def _select_option(text: str, name: str, label: str, *, contains: bool = False) -> str:
    block = re.search(rf'<select[^>]*name="{re.escape(name)}"[\s\S]*?</select>', text)
    if block is None:
        raise LibError(f"publication form has no {name}", "the page layout may have changed")
    wanted = label.casefold()
    exact = ""
    partial = ""
    for value, caption in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', block.group(0)):
        clean = " ".join(caption.split()).casefold()
        if not value or not clean or clean.startswith("--"):
            continue
        if clean == wanted and not exact:
            exact = value
        elif contains and wanted in clean and not partial:
            partial = value
    if exact or partial:
        return exact or partial
    raise LibError(f"publication form has no {label!r} choice for {name}", "the page layout may have changed")


def _form_key(page: bytes) -> str:
    match = re.search(rb'name="form_key"\s+type="hidden"\s+value="([^"]+)"', page)
    if match is None:
        match = re.search(rb'name="form_key"[^>]*value="([^"]+)"', page)
    if match is None:
        raise LibError("IEC page had no form_key", "retry later")
    return match.group(1).decode()


def _library_rows(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for block in re.finditer(
        r'<div class="font-bold">([^<]+)</div>[\s\S]*?getStatus(\d+)\((\d+)\)[\s\S]*?id="download_(\d+)"',
        text,
    ):
        found.append((block.group(2), unescape(block.group(1)).strip(), block.group(4)))
    if found:
        return found
    refs = re.findall(r'<div class="font-bold">([^<]+)</div>', text)
    ids = re.findall(r"getStatus(\d+)\((\d+)\)", text)
    for (item_id, _), ref in zip(ids, refs, strict=False):
        found.append((item_id, unescape(ref).strip(), ""))
    return found


_NEXT_PAGE = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*\baction\s+next\b[^"]*"|'
    r'<a[^>]*class="[^"]*\baction\s+next\b[^"]*"[^>]*href="([^"]+)"',
    re.IGNORECASE,
)


def _next_page(text: str) -> str | None:
    """The pager's Next link. A `page next jump` control skips ahead and is not this link."""
    match = _NEXT_PAGE.search(text)
    if match is None:
        return None
    href = unescape(match.group(1) or match.group(2))
    if href.startswith("http"):
        return href
    return urllib.parse.urljoin(f"{BASE}/en/publication/customer/products/", href)


def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "----WebKitFormBoundaryprimarysource"
    chunks = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
