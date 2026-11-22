"""What the webstore tells us, as plain data.

Catalog fields come from the search index's hits (only a few of its attributes are visible in the capture, see
docs/iso-webstore.md section 5); order fields from GraphQL. Money is `Decimal`, never float.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from primarysource.errors import LibError

STATUS_KEYS = {
    "ENT_ACTIVE": "active",
    "ENT_PROGRESS": "in-development",
    "ENT_INACTIVE": "inactive",
    "ENT_DELETED": "deleted",
}
"""The `statusKey` values the front end's status labels switch on. What the labels say is not in the capture."""


def money(value: Any, what: str) -> Decimal:
    """A price as `Decimal`, from a JSON number or string; anything else is an error naming `what`."""
    if isinstance(value, bool) or value is None:
        raise LibError(f"{what}: no amount", "the answer has no price; do not proceed")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise LibError(f"{what}: {value!r} is not an amount", "do not proceed") from exc


@dataclass(frozen=True, slots=True)
class Price:
    amount: Decimal
    currency: str

    @property
    def is_free(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


@dataclass(frozen=True, slots=True)
class ProductCode:
    """`iso:std:iso-iec:29341:-31-1` as the order summary prints it: organisation, number, optional part."""

    organisation: str
    number: str
    part: str = ""

    @classmethod
    def parse(cls, text: str) -> ProductCode | None:
        match = re.fullmatch(r"iso:std:([a-z0-9-]+):(\d{1,5})(?::(-[\d-]+))?", text.strip(), re.IGNORECASE)
        return cls(match[1].lower(), match[2], match[3] or "") if match else None

    def designation(self, year: int | str | None = None) -> str:
        """`ISO/IEC 29341-31-1:2017`, or without the year when it is not known."""
        publisher = "/".join(part.upper() for part in self.organisation.split("-"))
        tail = f":{year}" if year else ""
        return f"{publisher} {self.number}{self.part}{tail}"

    def __str__(self) -> str:
        return f"iso:std:{self.organisation}:{self.number}" + (f":{self.part}" if self.part else "")


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One catalog record. Any field the source did not state is empty, never guessed.

    `kind` is the search index's `category` (`standard`, `committee`, `ics`, ...). `price` is None for a catalog
    hit (the hits seen carry none); it is set from an order or basket line, where the price is real.
    """

    kind: str
    designation: str
    title: str
    url: str = ""
    status: str = ""
    status_key: str = ""
    edition: str = ""
    year: str = ""
    price: Price | None = None
    ics: tuple[str, ...] = ()
    committee: str = ""
    formats: tuple[str, ...] = ()
    product_code: str = ""
    abstract: str = ""
    language: str = ""
    pages: int | None = None
    published: str = ""
    """The publication date as the source states it (ISO 8601 when it is one), else empty."""
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    toc: tuple[str, ...] = ()
    """A public table of contents, if a source states one. The capture shows none; always empty today."""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_free(self) -> bool | None:
        """True or False when a price is known, None when it is not."""
        return None if self.price is None else self.price.is_free

    @property
    def key(self) -> str:
        """A stable file/doc key: the product code, else the designation, else the url path."""
        basis = self.product_code or self.designation or self.url or self.title
        return re.sub(r"[^A-Za-z0-9._-]+", "_", basis).strip("_").lower() or "entry"

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "designation": self.designation,
            "title": self.title,
            "url": self.url,
            "status": self.status,
            "status_key": self.status_key,
            "edition": self.edition,
            "year": self.year,
            "price": None
            if self.price is None
            else {"amount": str(self.price.amount), "currency": self.price.currency},
            "ics": list(self.ics),
            "committee": self.committee,
            "formats": list(self.formats),
            "product_code": self.product_code,
            "abstract": self.abstract,
            "language": self.language,
            "pages": self.pages,
            "published": self.published,
            "supersedes": list(self.supersedes),
            "superseded_by": list(self.superseded_by),
            "toc": list(self.toc),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> CatalogEntry:
        price = data.get("price")
        return cls(
            kind=str(data.get("kind", "standard")),
            designation=str(data.get("designation", "")),
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            status=str(data.get("status", "")),
            status_key=str(data.get("status_key", "")),
            edition=str(data.get("edition", "")),
            year=str(data.get("year", "")),
            price=Price(money(price["amount"], "price"), str(price["currency"])) if isinstance(price, dict) else None,
            ics=tuple(str(x) for x in data.get("ics", ())),
            committee=str(data.get("committee", "")),
            formats=tuple(str(x) for x in data.get("formats", ())),
            product_code=str(data.get("product_code", "")),
            abstract=str(data.get("abstract", "")),
            language=str(data.get("language", "")),
            pages=int(data["pages"]) if data.get("pages") is not None else None,
            published=str(data.get("published", "")),
            supersedes=tuple(str(x) for x in data.get("supersedes", ())),
            superseded_by=tuple(str(x) for x in data.get("superseded_by", ())),
            toc=tuple(str(x) for x in data.get("toc", ())),
        )


@dataclass(frozen=True, slots=True)
class OrderItem:
    description: str
    language: str
    format: str
    media: str
    unit_price: Decimal
    list_price: Decimal
    total: Decimal
    currency: str
    quantity: int
    is_shipping_charge: bool
    locked_for_user: bool

    @property
    def is_physical(self) -> bool:
        """A print item: it ships, so it is never part of a free order this client places."""
        return self.media.lower() == "print" or self.format.lower() == "paper" or self.is_shipping_charge


@dataclass(frozen=True, slots=True)
class Order:
    """The current (basket) order. `checksum` is what `processFreeOrder` must echo."""

    status: str
    currency: str
    total: Decimal
    total_tax: Decimal
    total_shipping: Decimal
    items: tuple[OrderItem, ...]
    checksum: str = field(repr=False, default="")


@dataclass(frozen=True, slots=True)
class SummaryItem:
    product_name: str
    product_code: str
    product_type: str
    format: str
    media: str
    language: str
    edition_year: str
    edition: str
    licenses: str
    unit_price: Decimal
    requires_shipping: bool


@dataclass(frozen=True, slots=True)
class OrderSummary:
    status: str
    currency: str
    total: Decimal
    items: tuple[SummaryItem, ...]
    messages: tuple[str, ...] = ()


def parse_order(raw: Mapping[str, Any]) -> Order:
    items: list[OrderItem] = []
    for item in raw.get("items") or ():
        items.append(
            OrderItem(
                description=str(item.get("description") or ""),
                language=str(item.get("language") or ""),
                format=str(item.get("format") or ""),
                media=str(item.get("media") or ""),
                unit_price=money(item.get("unitPrice"), "an order line's unit price"),
                list_price=money(item.get("listPrice"), "an order line's list price"),
                total=money(item.get("total"), "an order line's total"),
                currency=str(item.get("currency") or raw.get("currency") or ""),
                quantity=int(item.get("quantity") or 0),
                is_shipping_charge=bool(item.get("isShippingChargeLineItem")),
                locked_for_user=bool(item.get("lockedForUser")),
            )
        )
    return Order(
        status=str(raw.get("orderStatus") or ""),
        currency=str(raw.get("currency") or ""),
        total=money(raw.get("total"), "the order total"),
        total_tax=money(raw.get("totalTax"), "the order tax"),
        total_shipping=money(raw.get("totalShippingCharge"), "the order shipping charge"),
        items=tuple(items),
        checksum=str(raw.get("checksum") or ""),
    )


def parse_summary(raw: Mapping[str, Any]) -> OrderSummary:
    items = tuple(
        SummaryItem(
            product_name=str(item.get("productName") or ""),
            product_code=str(item.get("productCode") or ""),
            product_type=str(item.get("productType") or ""),
            format=str(item.get("format") or ""),
            media=str(item.get("media") or ""),
            language=str(item.get("language") or ""),
            edition_year=str(item.get("editionYear") or ""),
            edition=str(item.get("edition") or ""),
            licenses=str(item.get("licenses") or ""),
            unit_price=money(item.get("unitPrice"), "a summary line's unit price"),
            requires_shipping=bool(item.get("requiresShipping")),
        )
        for item in raw.get("items") or ()
    )
    return OrderSummary(
        status=str(raw.get("orderStatus") or ""),
        currency=str(raw.get("currency") or ""),
        total=money(raw.get("total"), "the order total"),
        items=items,
        messages=tuple(str(m) for m in raw.get("messages") or ()),
    )


def entries_from_summary(summary: OrderSummary) -> tuple[CatalogEntry, ...]:
    """A catalog record per standard in an order summary: the designation, edition year, format and the price paid.
    These are the only records with a real price and the product code in the capture."""
    entries: list[CatalogEntry] = []
    for item in summary.items:
        if item.product_type.lower() != "standard":
            continue
        code = ProductCode.parse(item.product_code)
        designation = code.designation(item.edition_year or None) if code else item.product_name
        entries.append(
            CatalogEntry(
                kind="standard",
                designation=designation,
                title="",
                edition=item.edition,
                year=item.edition_year,
                price=Price(item.unit_price, summary.currency),
                formats=(item.format,) if item.format else (),
                product_code=item.product_code,
            )
        )
    return tuple(entries)
