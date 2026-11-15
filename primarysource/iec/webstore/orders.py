"""What the owner has bought, and getting it: the order page, the download-status REST call, the download.

Observed in the capture (an order of one free item):

- `GET /en/sales/order/view/order_id/<id>/` is HTML. Its "Order summary" is a grid of `table-data-item` cells: the
  product reference (`item-title`), language, format, user/qty, then the per-item status script
  `getStatus<n>(<orderItemId>)`; the page header holds `orderDownloadDropdown(<orderId>)`;
- `GET /en/rest/V1/publications/mine/download-status/order/<orderId>` (the whole order) and
  `.../download-status/<orderItemId>` (one item) answer a JSON string holding JSON:
  `{status: "PROCESSING" | "COMPLETED", is_downloadable, download_url}`, and the item form adds
  `is_available_soon` and `is_outdated_prv`. The page polls every 5 seconds, at most 10 times;
- `download_url` is a pre-signed S3 URL on `storage-watermark-prd-iec-ch.s3.<region>.amazonaws.com`, an `.zip`,
  with the `X-Amz-*` query. The bucket name says the file is watermarked: each download is the owner's own copy.

Not in the capture: the order-history page (`/en/sales/order/history/`) and the "my products" page
(`/en/publication/customer/products/`); only links to them. `order_ids` reads `order_id/<n>` links from whatever
page it is given, which is the link shape the order-success page uses.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import CHUNK, replace
from primarysource.iec.webstore._secret import Secret
from primarysource.iec.webstore.session import IecSession
from primarysource.iec.webstore.transport import HttpRequest, download_host_allowed, ensure_outside_repository

__all__ = [
    "DownloadResult",
    "DownloadStatus",
    "OrderClient",
    "OrderItem",
    "OrderView",
    "parse_order_ids",
    "parse_order_view",
]

DOWNLOAD_STATUS = "rest/V1/publications/mine/download-status/"
_ORDER_LINK = re.compile(r"sales/order/view/order_id/(\d+)")
_DROPDOWN = re.compile(r"orderDownloadDropdown\((\d+)\)")
_ITEM_SCRIPT = re.compile(r"getStatus\d+\((\d+)\)")
_CELL = re.compile(r'<div class="table-data-item([^"]*)">(.*?)</div>', re.S)
_TAGS = re.compile(r"<!--.*?-->|<[^>]+>", re.S)
_PRICE = re.compile(r"([A-Z]{3})\s*([\d'.,]+)")


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAGS.sub(" ", fragment))).strip()


@dataclass(frozen=True, slots=True)
class OrderItem:
    reference: str
    language: str
    format: str
    quantity: int
    item_id: str
    price: str = ""


@dataclass(frozen=True, slots=True)
class OrderView:
    """The items of one order. The page's payment method and billing address are deliberately not read."""

    order_id: str
    items: tuple[OrderItem, ...]
    complete: bool = False


def parse_order_ids(html: str) -> tuple[str, ...]:
    """Every order id linked from `html`, in order, once each."""
    return tuple(dict.fromkeys(_ORDER_LINK.findall(html)))


def parse_order_view(html: str) -> OrderView:
    dropdown = _DROPDOWN.search(html)
    start = html.find("order-details-items")
    if dropdown is None or start < 0:
        raise LibError("this is not an order page the client understands", "see docs/iec-webstore.md, 'Orders'")
    body = html[start:]
    stop = body.find("Order information")
    body = body[: stop if stop > 0 else len(body)]
    items: list[OrderItem] = []
    titles = [m for m in re.finditer(r'<div class="table-data-item item-title[^"]*">', body)]
    for index, title in enumerate(titles):
        block = body[title.start() : titles[index + 1].start() if index + 1 < len(titles) else len(body)]
        no_script = re.sub(r"<script.*?</script>", "", block, flags=re.S)
        cells = [_clean(m.group(2)) for m in _CELL.finditer(no_script)]
        item_id = _ITEM_SCRIPT.search(block)
        price = ""
        match = re.search(r'class="price">(.*?)</span>', block, re.S)
        if match:
            price = _clean(match.group(1))
        if len(cells) < 4 or item_id is None:
            raise LibError("an order row has fewer cells than expected", "the page may have changed; see docs")
        try:
            quantity = int(cells[3])
        except ValueError:
            quantity = 0
        items.append(OrderItem(cells[0], cells[1], cells[2], quantity, item_id.group(1), price))
    complete = bool(re.search(r"Status:&nbsp;\s*</span>\s*Complete", html))
    return OrderView(dropdown.group(1), tuple(items), complete)


@dataclass(frozen=True, slots=True)
class DownloadStatus:
    status: str
    is_downloadable: bool
    download_url: Secret | None = field(default=None, repr=False)
    is_available_soon: bool = False
    is_outdated_prv: bool = False


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    size: int
    sha256: str


def _safe_name(url: str) -> str:
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "download.zip"


class OrderClient:
    def __init__(self, session: IecSession) -> None:
        self._session = session

    def order_view(self, order_id: str) -> OrderView:
        if not order_id.isdigit():
            raise LibError("an order id is digits", "copy it from the order page's address")
        response = self._session.get(f"sales/order/view/order_id/{order_id}/")
        if response.status != 200:
            raise LibError(
                f"the store answered HTTP {response.status} for the order page", "log in first, and check the id"
            )
        return parse_order_view(response.text())

    def order_ids(self, page: str = "sales/order/history/") -> tuple[str, ...]:
        response = self._session.get(page)
        if response.status != 200:
            raise LibError(f"the store answered HTTP {response.status} for {page}", "log in first")
        return parse_order_ids(response.text())

    def owned(self, *, max_orders: int = 10) -> tuple[tuple[str, OrderItem], ...]:
        """`(order_id, item)` for the items of up to `max_orders` orders, newest first as the history lists them.
        One request per order: the bound is the point."""
        found: list[tuple[str, OrderItem]] = []
        for order_id in self.order_ids()[:max_orders]:
            found.extend((order_id, item) for item in self.order_view(order_id).items)
        return tuple(found)

    def download_status(self, *, order_id: str | None = None, item_id: str | None = None) -> DownloadStatus:
        if (order_id is None) == (item_id is None):
            raise LibError("name an order or an item, not both and not neither", "pass order_id or item_id")
        ident = order_id if order_id is not None else item_id
        if not ident or not ident.isdigit():
            raise LibError("an id is digits", "copy it from the order page")
        path = f"{DOWNLOAD_STATUS}order/{ident}" if order_id is not None else f"{DOWNLOAD_STATUS}{ident}"
        response = self._session.get(path, self._session.ajax_headers(json_body=True))
        if response.status != 200:
            raise LibError(f"the store answered HTTP {response.status} for the download status", "log in first")
        data = response.json_twice()
        if not isinstance(data, dict):
            raise LibError("the download status is not an object", "the site may have changed; see docs")
        url = data.get("download_url")
        return DownloadStatus(
            str(data.get("status", "")),
            bool(data.get("is_downloadable")),
            Secret(str(url)) if url else None,
            bool(data.get("is_available_soon")),
            bool(data.get("is_outdated_prv")),
        )

    def download(
        self,
        destination: Path,
        *,
        order_id: str | None = None,
        item_id: str | None = None,
        poll_seconds: float = 5.0,
        max_polls: int = 10,
        sleep: Callable[[float], None] = time.sleep,
    ) -> DownloadResult:
        """Download what the owner has bought: wait for the store to say it is ready, stream it to
        `<name>.part` in `destination` (a directory outside every repository), check the size, hash it, and put
        it in place with `os.replace`. An existing file is never overwritten."""
        folder = ensure_outside_repository(destination)
        status = self.download_status(order_id=order_id, item_id=item_id)
        polls = 1
        while not (status.is_downloadable and status.download_url):
            if status.is_available_soon or polls >= max_polls:
                raise LibError(
                    f"the store has not made the file available (status {status.status or 'unknown'})",
                    "try again later; the store prepares a watermarked copy and may take minutes",
                )
            sleep(poll_seconds)
            status = self.download_status(order_id=order_id, item_id=item_id)
            polls += 1
        url = status.download_url.reveal() if status.download_url else ""
        if not download_host_allowed(urllib.parse.urlsplit(url).hostname):
            raise LibError("the download link is on a host this client does not follow", "report it; see docs")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / _safe_name(url)
        if target.exists():
            raise LibError(f"{target.name} already exists in the destination", "move it away or pick another folder")
        part = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        size = 0
        try:
            with self._session.transport.open_stream(HttpRequest("GET", url)) as response:
                if response.status != 200:
                    raise LibError(f"the download answered HTTP {response.status}", "ask for a fresh link and retry")
                expected = response.header("content-length")
                with part.open("wb") as out:
                    while chunk := response.read(CHUNK):
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if expected is not None and expected.isdigit() and int(expected) != size:
                raise LibError(f"the download is {size} bytes, the store said {expected}", "retry the download")
            replace(part, target)
        except BaseException:
            with contextlib.suppress(OSError):
                part.unlink()
            raise
        return DownloadResult(target, size, digest.hexdigest())
